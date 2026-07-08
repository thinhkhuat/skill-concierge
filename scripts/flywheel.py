#!/usr/bin/env python3
"""
flywheel.py — status + incremental generation for the retrieval flywheel
(ADR-0026 utterance layer). Stdlib only; the LLM generation + reindex run under
the engine venv.

The utterance layer teaches the retriever how users actually ASK for a skill
(EN+VN). New skills get no utterances until the generator runs — this wrapper
makes that visible (status) and self-service (--generate) from the slash menu.

Modes:
  python3 scripts/flywheel.py            # status (read-only): coverage + endpoint reachability
  python3 scripts/flywheel.py --generate # run incremental generator + reindex, print before/after

Coverage = live-index skill names (Qdrant claude_skills, kind=base) vs the skills
in eval/triggers.json that carry a non-empty `llm_triggers.triggers` list.
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm  # noqa: E402 — shared OpenAI-compatible client (ping/live_skills/config)

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
    return ok, missing


def generate(rate=None):
    if not SS_BIN.exists() or not PY_BIN.exists():
        print(f"FAIL: engine venv missing at {VENV} — run the skill-concierge:setup skill (./setup.sh) first",
              file=sys.stderr)
        return 3

    ok, detail = flywheel_llm.ping()
    if not ok:
        print(f"FAIL: flywheel LLM endpoint unreachable — {detail}", file=sys.stderr)
        print(f"Configure a reachable endpoint before generating — see {PROVIDERS_DOC}", file=sys.stderr)
        return 2

    _, _, before = coverage()
    print(f"Before: {len(before)} indexed skills missing utterances")

    cmd = [str(PY_BIN), str(ROOT / "scripts" / "llm_triggers.py")]
    if rate is not None:
        cmd += ["--rate", str(rate)]
    print(f"Running incremental generator (only new/changed skills hit the LLM): {' '.join(cmd)}")
    r = subprocess.run(cmd, env=_engine_env())
    if r.returncode != 0:
        print("FAIL: generator exited non-zero", file=sys.stderr)
        return r.returncode

    print("Reindexing so the new utterance points go live...")
    rr = subprocess.run([str(SS_BIN), "--reindex"], env=_engine_env())
    if rr.returncode != 0:
        print("FAIL: reindex exited non-zero", file=sys.stderr)
        return rr.returncode

    _, _, after = coverage()
    print(f"After: {len(after)} indexed skills missing utterances")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Retrieval-flywheel status + incremental generation")
    ap.add_argument("--generate", action="store_true",
                    help="run the incremental generator + reindex (default: read-only status)")
    ap.add_argument("--rate", type=float, default=None,
                    help="seconds between LLM calls, passed through to llm_triggers.py")
    args = ap.parse_args()
    if args.generate:
        sys.exit(generate(rate=args.rate))
    print_status()


if __name__ == "__main__":
    main()
