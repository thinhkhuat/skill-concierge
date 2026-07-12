#!/usr/bin/env python3
"""
openwiki_parity_guard.py — PreToolUse(Bash) gate: no commit while the wiki is out of parity.

WHY THIS EXISTS
    openwiki/ is documentation ABOUT this codebase, so it goes stale the moment the
    codebase moves. Two failure modes were observed live, and both are silent:

      1. VERSION DRIFT — plugin.json / marketplace.json / CHANGELOG say 0.20.0 while the
         wiki still says 0.19.x. The wiki then confidently describes a release that is
         not the one shipping.
      2. CORRUPTION — a botched wiki edit clobbered a sentence and left a broken link.
         Because those edits were never committed, the damage survived into the next run.

    A stale wiki is worse than no wiki: it gets read as authoritative. The commit is the
    checkpoint where parity is enforced — code must not land while the docs lie about it.

WHAT IT DOES
    Fires on PreToolUse for Bash. If the command is not a `git commit`, it exits 0 silently
    and the call proceeds through the normal permission flow (per the hooks spec, exit 0
    with no output = "no decision to report"; silence is not approval). If it IS a commit,
    it runs two DETERMINISTIC checks — no LLM, no network, sub-second:

      A. driftcheck.py  — version parity across plugin.json (SSOT), marketplace.json,
                          CHANGELOG.md, README.md, and openwiki/quickstart.md.
      B. link integrity — every relative link inside openwiki/ resolves on disk.

    Any failure -> permissionDecision "deny", naming the specific drift and the fix.

DELIBERATELY NOT CHECKED
    Whether the wiki's PROSE is semantically current. No cheap check can know that, and a
    guard pretending otherwise would be theater. This enforces what is mechanically
    decidable; refreshing the prose is what `/openwiki:wiki update` is for.

ESCAPE HATCH
    OPENWIKI_GUARD=0 -> skip entirely (emergency, or surgery unrelated to the docs).

FAIL-OPEN
    Any internal error exits 0 (allow). A broken guard must never wedge the repo — it is a
    safety net, not a tollbooth.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# `git commit`, tolerating compound commands and intervening flags:
#   git commit -m x   |   git add . && git commit   |   git -C path commit
COMMIT_RE = re.compile(r"\bgit\b(?:\s+-[^\s]+(?:\s+[^\s-][^\s]*)?)*\s+commit\b")


def _emit_deny(reason):
    """PreToolUse decision control: hookSpecificOutput.permissionDecision (hooks spec)."""
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _repo_root():
    """Project root, from the CLAUDE_PROJECT_DIR placeholder Claude Code exports."""
    root = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(root) if root else None


def _is_skill_concierge(root):
    """Guard only this repo. Defensive — project settings shouldn't load elsewhere anyway."""
    try:
        manifest = root / ".claude-plugin" / "plugin.json"
        return json.loads(manifest.read_text()).get("name") == "skill-concierge"
    except Exception:
        return False


def _driftcheck(root):
    """Version parity. Returns a failure message, or None when in sync."""
    if not (root / "driftcheck.json").exists():
        return None
    r = subprocess.run(
        [sys.executable, "scripts/driftcheck.py", "driftcheck.json"],
        cwd=str(root), capture_output=True, text=True, timeout=30,
    )
    if r.returncode == 0:
        return None
    drifts = [ln.strip() for ln in r.stdout.splitlines() if "[DRIFT]" in ln]
    return "\n".join("  " + d for d in drifts) or "  driftcheck.py reported drift"


def _broken_links(root):
    """Every relative link inside openwiki/ must resolve. Catches corrupted edits."""
    wiki = root / "openwiki"
    if not wiki.is_dir():
        return []
    bad = []
    link_re = re.compile(r"\[[^\]]*\]\(((?!https?:|#|mailto:)[^)]+)\)")
    for md in sorted(wiki.rglob("*.md")):
        try:
            text = md.read_text(encoding="utf-8")
        except Exception:
            continue
        for m in link_re.finditer(text):
            target = m.group(1).split("#")[0].strip()
            if target and not (md.parent / target).resolve().exists():
                bad.append("  %s -> %s" % (md.relative_to(root), target))
    return bad


def main():
    if os.environ.get("OPENWIKI_GUARD") == "0":
        return 0

    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0  # unparseable input: not our business, allow

    if payload.get("tool_name") != "Bash":
        return 0

    command = (payload.get("tool_input") or {}).get("command") or ""
    if not COMMIT_RE.search(command):
        return 0

    root = _repo_root()
    if not root or not _is_skill_concierge(root):
        return 0

    failures = []

    drift = _driftcheck(root)
    if drift:
        failures.append("VERSION PARITY — the wiki does not carry the shipping version:\n" + drift)

    broken = _broken_links(root)
    if broken:
        failures.append(
            "WIKI INTEGRITY — broken links in openwiki/ (a corrupted or half-finished edit):\n"
            + "\n".join(broken)
        )

    if not failures:
        return 0

    _emit_deny(
        "Commit blocked: openwiki/ is out of parity with the codebase.\n\n"
        + "\n\n".join(failures)
        + "\n\nFIX — refresh the wiki, then commit again:\n"
          "  1. Run  /openwiki:wiki update   — refreshes the pages against current source.\n"
          "  2. Ensure openwiki/quickstart.md's **Version:** line carries the version in\n"
          "     .claude-plugin/plugin.json (the SSOT).\n"
          "  3. Verify:  python3 scripts/driftcheck.py driftcheck.json   (must exit 0)\n\n"
          "A stale wiki gets read as authoritative — that is why this gate exists.\n"
          "Genuine emergency override: OPENWIKI_GUARD=0."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        sys.exit(0)  # fail-open: a broken guard must never wedge the repo
