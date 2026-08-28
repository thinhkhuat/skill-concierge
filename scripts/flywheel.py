#!/usr/bin/env python3
"""
flywheel.py — status + incremental generation for the retrieval flywheel
(ADR-0026 utterance layer). Stdlib only; the LLM generation + reindex run under
the engine venv.

The utterance layer teaches the retriever how users actually ASK for a skill
(EN+VN). New skills get no utterances until the generator runs — this wrapper
makes that visible (status) and self-service (--generate) from the slash menu.

Modes:
  python3 scripts/flywheel.py                   # status (read-only): coverage + reachability
  python3 scripts/flywheel.py --generate         # scenarios + triggers for new/changed skills
  python3 scripts/flywheel.py --generate --triggers-only  # triggers only (skip scenario regen)

Coverage = live-index skill names (Qdrant claude_skills, kind=base) vs the skills
in eval/triggers.json that carry a non-empty `llm_triggers.triggers` list.

Every --generate run appends a record to the global run manifest
(~/.claude/skill-concierge/flywheel-manifest.json, scripts/flywheel_manifest.py) — same
manifest the SessionStart auto-hook (hooks/scripts/auto_flywheel.py) writes to.
"""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm  # shared OpenAI-compatible client (ping/live_skills/config)
import build_triggers     # live-index scroll (catalog= for external catalogs, ADR-0031)
import flywheel_lock      # cross-process mutual exclusion (auto vs manual)
import flywheel_manifest  # shared global run-manifest writer/reader
import llm_eval_gen  # scenario (positive/negative) generator
import llm_triggers  # utterance-trigger generator

VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
TRIGGERS_FILE = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
PROVIDERS_DOC = ROOT / "references" / "flywheel-llm-providers.md"
SS_BIN = VENV / "bin" / "skill-search"
PY_BIN = VENV / "bin" / "python3"


def _engine_env():
    """Merge the embedder/store env from .mcp.json (single source of truth) under any
    process-env overrides — same seams doctor.py uses so a manual reindex matches the MCP.

    Forwards the TRIGGER-LAYER keys too, on the same 7-key tuple auto_reindex._mcp_env()
    uses: this env drives the reindex at the end of generate(), and without SKILL_TRIGGERS
    (plus SKILL_LLM_TRIGGERS/TRIGGERS_MAX/SKILL_BODY_TRIGGERS) that reindex rebuilds at
    engine defaults and prunes the utterance layer the run just generated — the exact
    0.16.1/0.20.5 drift class (ADR-0026)."""
    env = {}
    try:
        env = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
    except (KeyError, OSError, TypeError, UnicodeError, json.JSONDecodeError):
        env = {}
    merged = dict(os.environ)
    for k in ("SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL",
              "SKILL_LLM_TRIGGERS", "TRIGGERS_MAX", "SKILL_TRIGGERS", "SKILL_BODY_TRIGGERS"):
        if k in env and k not in os.environ:
            merged[k] = env[k]
    return merged


def coverage():
    """(indexed sorted, covered set, missing sorted). indexed = live-index base names;
    covered = triggers.json keys with a non-empty llm_triggers.triggers list."""
    indexed = set(flywheel_llm.live_skill_names())
    covered = set()
    if TRIGGERS_FILE.exists():
        data = json.loads(TRIGGERS_FILE.read_text(encoding="utf-8"))
        for name, entry in data.items():
            if isinstance(entry, dict) and (entry.get("llm_triggers", {}) or {}).get("triggers"):
                covered.add(name)
    missing = sorted(indexed - covered)
    return sorted(indexed), covered, missing


def catalog_coverage(alias):
    """(indexed sorted, missing sorted) for ONE external catalog (ADR-0031 D10).
    Same covered-test as coverage(), over the catalog's alias-namespaced skills."""
    indexed = sorted({n for n, _ in build_triggers.scroll_all_points(catalog=alias)})
    covered = set()
    if TRIGGERS_FILE.exists():
        data = json.loads(TRIGGERS_FILE.read_text(encoding="utf-8"))
        for name, entry in data.items():
            if isinstance(entry, dict) and (entry.get("llm_triggers", {}) or {}).get("triggers"):
                covered.add(name)
    return indexed, sorted(set(indexed) - covered)


def _config_home():
    return Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))


def _configured_aliases():
    """External catalog aliases from the operator's catalog-roots.json (ADR-0031),
    fail-open to [] — status must never crash on a malformed config."""
    try:
        data = json.loads((_config_home() / "catalog-roots.json").read_text(encoding="utf-8"))
        return sorted(k for k, v in data.items() if isinstance(v, dict))
    except (OSError, ValueError):
        return []


def _utterance_covered_count(alias=None):
    """Raw count of triggers.json entries carrying a non-empty llm_triggers block,
    optionally scoped to one catalog's alias-namespaced keys. Fast snapshot source
    for live-progress sampling (live index membership is not re-checked per sample)."""
    try:
        data = json.loads(TRIGGERS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    if alias is None:
        return sum(1 for v in data.values()
                   if isinstance(v, dict) and (v.get("llm_triggers") or {}).get("triggers"))
    prefix = f"{alias}:"
    return sum(1 for k, v in data.items()
               if isinstance(k, str) and k.startswith(prefix)
               and isinstance(v, dict) and (v.get("llm_triggers") or {}).get("triggers"))


def _print_live_progress(scope_targets):
    """While the lock is HELD, sample utterance coverage twice (5s apart) and print
    throughput + ETA against the scope totals the caller computed. This is the only
    way to observe a DETACHED run's progress (auto_flywheel spawns into background
    with no terminal attached) — one command answers 'is it running, how fast, when done'."""
    def _snap():
        return sum(_utterance_covered_count(a) for a in scope_targets)
    first, t0 = _snap(), time.time()
    time.sleep(5)
    second, t1 = _snap(), time.time()
    per_s = (second - first) / max(t1 - t0, 0.001)
    total = sum(t for t in scope_targets.values())
    print(f"  live     : {second}/{total} utterances across all scopes")
    if per_s > 0.01:
        remain = max(total - second, 0)
        print(f"  rate     : ~{per_s * 60:.0f} skills/min — ETA ~{remain / per_s / 60:.0f} min "
              f"for the remaining {remain}")
    else:
        print("  rate     : ~0/min — embedding/reindex phase, or no generation throughput")


def print_status():
    ok, detail = flywheel_llm.ping()
    print("Flywheel LLM endpoint")
    print(f"  endpoint : {flywheel_llm.ENDPOINT}")
    print(f"  model    : {flywheel_llm.MODEL}")
    print(f"  api key  : {'set' if flywheel_llm.API_KEY else 'none'}")
    print(f"  schema   : {flywheel_llm.SCHEMA_MODE}")
    print(f"  reachable: {'YES' if ok else 'NO'} — {detail}")
    print()

    # --- coverage: installed base + every configured external catalog ----------
    indexed, _covered, missing = coverage()
    have = len(indexed) - len(missing)
    aliases = _configured_aliases()
    scope_targets = {"(installed)": len(indexed)}
    for alias in aliases:
        cat_indexed, _cat_missing = catalog_coverage(alias)
        scope_targets[alias] = len(cat_indexed)
    print("Utterance coverage (llm_triggers)")
    print(f"  installed: {have}/{len(indexed)}; {len(missing)} missing")
    for m in missing[:10]:
        print(f"    - {m}")
    if len(missing) > 10:
        print(f"    ... and {len(missing) - 10} more")
    for alias in aliases:
        cat_indexed, cat_missing = catalog_coverage(alias)
        print(f"  {alias}: {len(cat_indexed) - len(cat_missing)}/{len(cat_indexed)}; "
              f"{len(cat_missing)} missing")
        for m in cat_missing[:5]:
            print(f"    - {m}")
        if len(cat_missing) > 5:
            print(f"    ... and {len(cat_missing) - 5} more")
    print("  fix: python3 scripts/flywheel.py --generate [--catalog <alias>]  "
          "(or run the skill-concierge:flywheel skill)")
    print()

    # --- state: lock + live progress for a DETACHED run -------------------------
    running = False
    try:
        running = flywheel_lock.is_locked()
    except Exception:
        pass
    print("State")
    if running:
        pid, since = flywheel_lock.holder()
        hint = f" (pid {pid} since {since:.0f})" if pid and since else ""
        print(f"  run      : IN PROGRESS{hint} — --generate would skip (exit 4)")
        try:
            _print_live_progress(scope_targets)
        except (OSError, ValueError) as e:
            print(f"  live     : unavailable ({e})")
    else:
        print("  run      : idle (lock free)")
    print()

    # --- auto-flywheel: gate + throttle window + last hook log line -------------
    print("Auto-flywheel (SessionStart hook)")
    gate = os.environ.get("SKILL_AUTO_FLYWHEEL", "1")
    print(f"  gate     : SKILL_AUTO_FLYWHEEL={gate} ({'ON' if gate != '0' else 'OFF'})")
    print(f"  workers  : {os.environ.get('AUTO_FLYWHEEL_WORKERS', '4')}  "
          f"cap/run: {os.environ.get('AUTO_FLYWHEEL_MAX_PER_RUN', '25')}  "
          f"throttle: {int(os.environ.get('AUTO_FLYWHEEL_THROTTLE_S', '21600')) // 60} min")
    try:
        logdir = Path(os.environ.get("SKILL_CONCIERGE_LOG", _config_home() / "logs"))
        stamp = logdir / ".auto-flywheel-stamp"
        window = int(os.environ.get("AUTO_FLYWHEEL_THROTTLE_S", "21600"))
        if stamp.exists():
            age = time.time() - stamp.stat().st_mtime
            if age >= window:
                print(f"  throttle : eligible now (last auto run {age / 3600:.1f}h ago)")
            else:
                print(f"  throttle : {age / 60:.0f}min into the {window // 60}min window — "
                      f"eligible in {(window - age) / 60:.0f}min")
        else:
            print("  throttle : no auto run recorded yet — eligible now")
        logfile = logdir / "auto-flywheel.log"
        if logfile.exists():
            lines = [ln for ln in logfile.read_text(encoding="utf-8", errors="replace")
                     .splitlines() if ln.strip()]
            if lines:
                print(f"  last hook: {lines[-1][:120]}")
    except OSError as e:
        print(f"  throttle : unknown ({e})")
    print()

    # --- recent runs from the global manifest ----------------------------------
    print("Recent runs (global manifest ~/.claude/skill-concierge/flywheel-manifest.json)")
    try:
        runs = (json.loads(flywheel_manifest.MANIFEST_PATH.read_text(encoding="utf-8"))
                or {}).get("runs", [])
    except (OSError, ValueError, AttributeError):
        runs = []
    if not runs:
        print("  none recorded yet (fresh install, or the auto_flywheel hook has not fired)")
    for lr in runs[-3:][::-1]:
        t = lr.get("totals", {})
        line = (f"  {lr.get('timestamp','?')}  via {lr.get('model','?')}: "
                f"generated {t.get('generated',0)}  error {t.get('error',0)}  "
                f"skipped {t.get('skipped',0)}")
        cov = lr.get("coverage") or {}
        if cov.get("total"):
            line += f"  | coverage {cov.get('have')}/{cov.get('total')}"
        if lr.get("last_error"):
            line += f"  | last_error: {lr['last_error']}"
        print(line)
    errs = [s for s in ((runs[-1] if runs else {}).get("skills") or [])
            if s.get("status") == "error" and s.get("detail")]
    if errs:
        print(f"  per-skill errors in last run ({len(errs)}):")
        for s in errs[:10]:
            print(f"    - {s['name']}: {s['detail']}")
        if len(errs) > 10:
            print(f"    ... and {len(errs) - 10} more (see manifest)")
    return ok, missing


def _write_manifest(skills=None, coverage_dict=None, last_error=None):
    """Append one run record to the global manifest. Called on every --generate exit
    path (success or failure) so `last_error` is always visible to doctor / other agents."""
    return flywheel_manifest.write_run(
        endpoint=flywheel_llm.ENDPOINT, model=flywheel_llm.MODEL,
        skills=skills or [], coverage=coverage_dict or {"have": 0, "total": 0},
        last_error=last_error,
    )


def _print_run_summary(run):
    print(f"Manifest: {flywheel_manifest.MANIFEST_PATH}")
    print(f"  generated={run['totals']['generated']} error={run['totals']['error']} "
          f"skipped={run['totals']['skipped']}; "
          f"coverage {run['coverage']['have']}/{run['coverage']['total']}")
    if run["last_error"]:
        print(f"  last_error: {run['last_error']}")
    # (b) surface per-skill error detail when present
    errs = [s for s in (run.get("skills") or []) if s.get("status") == "error" and s.get("detail")]
    if errs:
        print(f"  per-skill errors ({len(errs)}):")
        for s in errs[:8]:
            print(f"    - {s['name']}: {s['detail']}")
        if len(errs) > 8:
            print(f"    ... and {len(errs) - 8} more")


def generate(rate=None, limit=None, triggers_only=False, catalog=None, workers=1):
    if not SS_BIN.exists() or not PY_BIN.exists():
        msg = f"engine venv missing at {VENV}"
        print(f"FAIL: {msg} — run the skill-concierge:setup skill (./setup.sh) first", file=sys.stderr)
        _print_run_summary(_write_manifest(last_error=msg))
        return 3

    ok, detail = flywheel_llm.ping()
    if not ok:
        print(f"FAIL: flywheel LLM endpoint unreachable — {detail}", file=sys.stderr)
        print(f"Configure a reachable endpoint before generating — see {PROVIDERS_DOC}", file=sys.stderr)
        _print_run_summary(_write_manifest(last_error=f"unreachable: {detail}"))
        return 2

    # --- lock (a): auto vs manual mutual exclusion ---
    # Acquire BEFORE any LLM work or the final reindex so two concurrent
    # invocations (SessionStart auto + manual `flywheel --generate`) cannot
    # double the request rate or race on triggers.json / the index. Early
    # exits above (venv missing / unreachable) do NOT hold the lock.
    if not flywheel_lock.acquire(block=False):
        pid, since = flywheel_lock.holder()
        held = f" (pid {pid} since {since:.0f})" if pid and since else ""
        print(f"SKIP: flywheel already running{held} — another run holds {flywheel_lock.LOCK_PATH}",
              file=sys.stderr)
        return 4

    try:
        run_cov = None
        if catalog is not None:
            cat_indexed, before = catalog_coverage(catalog)
            if not cat_indexed:
                print(f"FAIL: catalog {catalog!r} has no indexed skills — check "
                      f"`catalogs.py list` and reindex first", file=sys.stderr)
                _print_run_summary(_write_manifest(last_error=f"catalog {catalog}: no indexed skills"))
                return 5
            print(f"Catalog {catalog!r}: {len(cat_indexed)} indexed skills, "
                  f"{len(before)} missing utterances")
        else:
            _, _, before = coverage()
            print(f"Before: {len(before)} indexed skills missing utterances")
        rate = rate if rate is not None else 6.0

        results = {}  # name -> {"status": "generated"|"error", "detail": str|None}

        def _note(records):
            for r in records:
                cur = results.get(r["name"])
                # "error" is the worst status — it sticks even if a later generator
                # reports "generated" for the same skill (two generators run per pass).
                if r["status"] == "error" or cur is None or cur.get("status") != "error":
                    results[r["name"]] = {"status": r["status"], "detail": r.get("detail")}

        if not triggers_only:
            print("Generating eval scenarios for new/changed skills (llm_eval_gen.py)...")
            try:
                _note(llm_eval_gen.run(out_dir=llm_eval_gen.DEFAULT_OUT, limit=limit,
                                       rate=rate, catalog=catalog, workers=workers))
            except (AttributeError, IndexError, KeyError, OSError, TypeError, json.JSONDecodeError) as e:
                print(f"FAIL: scenario generator crashed: {e}", file=sys.stderr)
                _print_run_summary(_write_manifest(last_error=f"llm_eval_gen crashed: {e}"))
                return 1

        print("Generating utterance triggers for new/changed skills (llm_triggers.py)...")
        try:
            _note(llm_triggers.run(limit=limit, rate=rate, catalog=catalog, workers=workers))
        except (AttributeError, IndexError, KeyError, OSError, TypeError, json.JSONDecodeError) as e:
            print(f"FAIL: trigger generator crashed: {e}", file=sys.stderr)
            _print_run_summary(_write_manifest(last_error=f"llm_triggers crashed: {e}"))
            return 1

        print("Reindexing so the new utterance points go live...")
        rr = subprocess.run([str(SS_BIN), "--reindex"], env=_engine_env(), check=False)
        if rr.returncode != 0:
            print("FAIL: reindex exited non-zero", file=sys.stderr)
            _print_run_summary(_write_manifest(
                skills=[{"name": n, "status": s["status"], "when": None,
                         **({"detail": s["detail"]} if s.get("detail") else {})}
                        for n, s in results.items()],
                last_error="reindex exited non-zero"))
            return rr.returncode

        if catalog is not None:
            cat_indexed, after = catalog_coverage(catalog)
            print(f"After: {len(after)} {catalog}:* skills missing utterances")
            run_cov = {"have": len(cat_indexed) - len(after), "total": len(cat_indexed)}
        else:
            indexed, _covered, after = coverage()
            print(f"After: {len(after)} indexed skills missing utterances")

        when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        skills_manifest = [
            {"name": n, "status": v["status"], "when": when,
             **({"detail": v["detail"]} if v.get("detail") else {})}
            for n, v in sorted(results.items())
        ]
        totals = {
            "generated": sum(1 for v in results.values() if v["status"] == "generated"),
            "error": sum(1 for v in results.values() if v["status"] == "error"),
            "skipped": (run_cov["total"] if run_cov is not None else len(indexed)) - len(results),
        }
        run = flywheel_manifest.write_run(
            endpoint=flywheel_llm.ENDPOINT, model=flywheel_llm.MODEL,
            skills=skills_manifest,
            coverage=run_cov or {"have": len(indexed) - len(after), "total": len(indexed)},
            totals=totals,
        )
        _print_run_summary(run)
        return 0
    finally:
        flywheel_lock.release()


def main():
    ap = argparse.ArgumentParser(description="Retrieval-flywheel status + incremental generation")
    ap.add_argument("--generate", action="store_true",
                    help="run the incremental generator + reindex (default: read-only status)")
    ap.add_argument("--rate", type=float, default=None,
                    help="seconds between LLM calls, passed through to the generators")
    ap.add_argument("--triggers-only", action="store_true",
                    help="with --generate: skip the scenario (llm_eval_gen) regen, triggers only")
    ap.add_argument("--limit", type=int, default=None,
                    help="with --generate: cap the number of skills processed this run")
    ap.add_argument("--catalog", default=None,
                    help="with --generate: run against ONE external catalog "
                         "(<alias>:* skills, ADR-0031) instead of installed skills")
    ap.add_argument("--workers", type=int, default=1,
                    help="with --generate: concurrent LLM calls (network phase "
                         "only; file writes stay single-threaded). Default 1.")
    args = ap.parse_args()
    if args.generate:
        sys.exit(generate(rate=args.rate, limit=args.limit, triggers_only=args.triggers_only,
                          catalog=args.catalog, workers=args.workers))
    print_status()


if __name__ == "__main__":
    main()
