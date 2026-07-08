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

import flywheel_llm  # noqa: E402 — shared OpenAI-compatible client (ping/live_skills/config)
import flywheel_manifest  # noqa: E402 — shared global run-manifest writer/reader
import llm_eval_gen  # noqa: E402 — scenario (positive/negative) generator
import llm_triggers  # noqa: E402 — utterance-trigger generator

VENV = Path(os.environ.get("SKILL_CONCIERGE_VENV", Path.home() / ".claude/skill-concierge/venv"))
TRIGGERS_FILE = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
PROVIDERS_DOC = ROOT / "references" / "flywheel-llm-providers.md"
SS_BIN = VENV / "bin" / "skill-search"
PY_BIN = VENV / "bin" / "python3"


def _engine_env():
    """Merge the embedder/store env from .mcp.json (single source of truth) under any
    process-env overrides — same seams doctor.py uses so a manual reindex matches the MCP."""
    env = {}
    try:
        env = json.loads((ROOT / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["skill-search"]["env"]
    except Exception:
        pass
    merged = dict(os.environ)
    for k in ("SKILL_QDRANT_URL", "SKILL_EMBED_BACKEND", "SKILL_EMBED_MODEL"):
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


def print_status():
    ok, detail = flywheel_llm.ping()
    print("Flywheel LLM endpoint")
    print(f"  endpoint : {flywheel_llm.ENDPOINT}")
    print(f"  model    : {flywheel_llm.MODEL}")
    print(f"  api key  : {'set' if flywheel_llm.API_KEY else 'none'}")
    print(f"  schema   : {flywheel_llm.SCHEMA_MODE}")
    print(f"  reachable: {'YES' if ok else 'NO'} — {detail}")
    print()

    indexed, _covered, missing = coverage()
    have = len(indexed) - len(missing)
    print("Utterance coverage (llm_triggers)")
    print(f"  {have}/{len(indexed)} indexed skills have utterances; {len(missing)} missing")
    for m in missing:
        print(f"    - {m}")
    if missing:
        print()
        print("  fix: python3 scripts/flywheel.py --generate  (or run the skill-concierge:flywheel skill)")

    # Last recorded run (manual or the background auto_flywheel hook) from the global manifest.
    try:
        import flywheel_manifest
        lr = flywheel_manifest.last_run()
    except Exception:
        lr = None
    print()
    print("Last flywheel run (global manifest ~/.claude/skill-concierge/flywheel-manifest.json)")
    if lr:
        t = lr.get("totals", {})
        print(f"  when: {lr.get('timestamp','?')}  via {lr.get('endpoint','?')} ({lr.get('model','?')})")
        print(f"  generated {t.get('generated',0)}  error {t.get('error',0)}  skipped {t.get('skipped',0)}"
              + (f"  | last_error: {lr.get('last_error')}" if lr.get("last_error") else ""))
    else:
        print("  none recorded yet (fresh install, or the auto_flywheel hook has not fired)")
    return ok, missing


def _write_manifest(skills=None, coverage_dict=None, last_error=None):
    """Append one run record to the global manifest. Called on every --generate exit
    path (success or failure) so `last_error` is always visible to doctor / other agents."""
    ok, _ = flywheel_llm.ping()
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


def generate(rate=None, limit=None, triggers_only=False):
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

    _, _, before = coverage()
    print(f"Before: {len(before)} indexed skills missing utterances")
    rate = rate if rate is not None else 6.0

    results = {}  # name -> worst status seen across the generators run this pass

    def _note(records):
        for r in records:
            if r["status"] == "error" or results.get(r["name"]) != "error":
                results[r["name"]] = r["status"]

    if not triggers_only:
        print("Generating eval scenarios for new/changed skills (llm_eval_gen.py)...")
        try:
            _note(llm_eval_gen.run(out_dir=llm_eval_gen.DEFAULT_OUT, limit=limit, rate=rate))
        except Exception as e:
            print(f"FAIL: scenario generator crashed: {e}", file=sys.stderr)
            _print_run_summary(_write_manifest(last_error=f"llm_eval_gen crashed: {e}"))
            return 1

    print("Generating utterance triggers for new/changed skills (llm_triggers.py)...")
    try:
        _note(llm_triggers.run(limit=limit, rate=rate))
    except Exception as e:
        print(f"FAIL: trigger generator crashed: {e}", file=sys.stderr)
        _print_run_summary(_write_manifest(last_error=f"llm_triggers crashed: {e}"))
        return 1

    print("Reindexing so the new utterance points go live...")
    rr = subprocess.run([str(SS_BIN), "--reindex"], env=_engine_env())
    if rr.returncode != 0:
        print("FAIL: reindex exited non-zero", file=sys.stderr)
        _print_run_summary(_write_manifest(
            skills=[{"name": n, "status": s, "when": None} for n, s in results.items()],
            last_error="reindex exited non-zero"))
        return rr.returncode

    indexed, _covered, after = coverage()
    print(f"After: {len(after)} indexed skills missing utterances")

    when = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    skills_manifest = [{"name": n, "status": s, "when": when} for n, s in sorted(results.items())]
    totals = {
        "generated": sum(1 for s in results.values() if s == "generated"),
        "error": sum(1 for s in results.values() if s == "error"),
        "skipped": len(indexed) - len(results),
    }
    run = flywheel_manifest.write_run(
        endpoint=flywheel_llm.ENDPOINT, model=flywheel_llm.MODEL,
        skills=skills_manifest, coverage={"have": len(indexed) - len(after), "total": len(indexed)},
        totals=totals,
    )
    _print_run_summary(run)
    return 0


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
    args = ap.parse_args()
    if args.generate:
        sys.exit(generate(rate=args.rate, limit=args.limit, triggers_only=args.triggers_only))
    print_status()


if __name__ == "__main__":
    main()
