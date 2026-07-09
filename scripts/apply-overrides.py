#!/usr/bin/env python3
"""
Apply skill-concierge's name-only budget overrides to ~/.claude/settings.json.

Every discovered skill → "name-only" EXCEPT the curated keep-on allowlist
(resolved by scripts/_keepon.py to the canonical home), which stay "on". Writes to **settings.json** (the global
single source), NOT settings.local.json — backs it up first and preserves every
other key.

Why NOT upstream `skill-search-overrides`: it targets settings.local.json with a
2-item keep-on default, silently reverting the hand-curated keep-on set (see
vendor/skill-search/VENDORED.md + the deployment readme). This applier is the
customization that keeps the curated policy intact.

Safety: refuses to write empty overrides (a failed discovery must not blank the
budget); always backs up before touching; UTF-8 preserved (ensure_ascii=False).

Test seams (env): SKILL_CONCIERGE_SETTINGS, SKILL_CONCIERGE_KEEPON, SKILL_CONCIERGE_HOME,
SKILL_CONCIERGE_SKILLS_FILE (newline-separated names → skips live discovery).
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

from _keepon import keepon_path      # sibling module (scripts/ is on sys.path at run)

ROOT = Path(__file__).resolve().parent.parent          # skill-concierge/
SETTINGS = Path(os.environ.get(
    "SKILL_CONCIERGE_SETTINGS", Path.home() / ".claude" / "settings.json"))
VENDOR = ROOT / "vendor" / "skill-search"


def discover_skill_names():
    """Skill names from the SAME source the index uses (vendored skills_discovery),
    so overrides and the retriever never drift. Test override: a newline file.

    Project-scoped skills are EXCLUDED. `skillOverrides` lives in the global
    ~/.claude/settings.json, but discovery's project dir is `Path.cwd()/.claude/skills`
    — so a map built in one project and a map built in another differ by that project's
    skills. Each session would see the other's keys as drift and rewrite the global file
    (churning a backup every time). Same failure the index had before ADR-0028: a
    CWD-scoped view driving a globally shared artifact. Project skills belong in that
    project's settings, not in every session's.
    """
    f = os.environ.get("SKILL_CONCIERGE_SKILLS_FILE")
    if f:
        return [ln.strip() for ln in Path(f).read_text(encoding="utf-8").splitlines() if ln.strip()]
    sys.path.insert(0, str(VENDOR))
    from skill_search.skills_discovery import discover_skills  # vendored engine
    return [s["name"] for s in discover_skills()
            if not str(s.get("scope", "")).startswith("project:")]


def _compute_overrides(keep_on, names):
    """Every discovered skill -> on|name-only. Sorted keys for deterministic comparison."""
    return {n: ("on" if n in keep_on else "name-only") for n in sorted(set(names))}


def _diff(new, cur):
    """(added, removed, flipped) between the computed map and what's on disk:
      added   = discovered skills with NO override yet (the name-only leak),
      removed = override keys no longer discovered (dead keys to prune),
      flipped = skills whose on<->name-only verdict changed (a keep-on.json edit)."""
    new_k, cur_k = set(new), set(cur)
    added = sorted(new_k - cur_k)
    removed = sorted(cur_k - new_k)
    flipped = sorted(k for k in (new_k & cur_k) if new[k] != cur[k])
    return added, removed, flipped


def _report_drift(overrides, added, removed, flipped):
    on = sum(1 for v in overrides.values() if v == "on")
    if not (added or removed or flipped):
        print(f"in sync: {on} on / {len(overrides) - on} name-only, no drift")
        return
    show = lambda ns: f"{len(ns)} ({', '.join(ns[:8])}{' …' if len(ns) > 8 else ''})"
    print("DRIFTED — skillOverrides out of date:")
    if added:
        print(f"  + {show(added)} discovered but un-overridden (leaking full description)")
    if removed:
        print(f"  - {show(removed)} stale override keys (skill gone)")
    if flipped:
        print(f"  ~ {show(flipped)} on/name-only verdict changed (keep-on edit)")
    print(f"  → drift: +{len(added)} added / -{len(removed)} stale / ~{len(flipped)} flipped")


def _write_settings(settings, overrides):
    """Backup (if a settings file already exists) + atomic write. Returns the on-count."""
    if SETTINGS.exists():
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{os.getpid()}"   # collision-safe
        bak = SETTINGS.parent / (SETTINGS.name + f".bak-skillconcierge-{stamp}")
        bak.write_text(SETTINGS.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"backup : {bak}")
    settings["skillOverrides"] = overrides
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write: serialize to a temp file in the same dir, then os.replace() — so a
    # crash/disk-full mid-write can NEVER leave the global settings.json truncated (B1).
    tmp = SETTINGS.parent / (SETTINGS.name + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, SETTINGS)
    return sum(1 for v in overrides.values() if v == "on")


def _selftest():
    """Pins the drift logic (--check / --if-changed) without touching live settings.
    Uses the env seams so it needs no engine import — runs under any Python."""
    import subprocess
    import tempfile

    ov = _compute_overrides({"skill-search"}, ["b", "a", "skill-search"])
    assert ov == {"a": "name-only", "b": "name-only", "skill-search": "on"}, ov

    cur = {"a": "name-only", "b": "on", "dead": "name-only"}
    new = {"a": "name-only", "b": "name-only", "c": "on"}
    added, removed, flipped = _diff(new, cur)
    assert added == ["c"] and removed == ["dead"] and flipped == ["b"], (added, removed, flipped)
    assert _diff(cur, cur) == ([], [], []), "identical map must show no drift"

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        (d / "skills.txt").write_text("skill-search\nalpha\nbeta\n", encoding="utf-8")
        (d / "keep.json").write_text(json.dumps({"keep_on": ["skill-search"]}), encoding="utf-8")
        settings = d / "settings.json"
        env = {**os.environ,
               "SKILL_CONCIERGE_SKILLS_FILE": str(d / "skills.txt"),
               "SKILL_CONCIERGE_KEEPON": str(d / "keep.json"),
               "SKILL_CONCIERGE_SETTINGS": str(settings)}
        run = lambda *a: subprocess.run([sys.executable, __file__, *a],
                                        env=env, capture_output=True, text=True)

        # settings absent -> everything is drift -> --check exits 1 and writes nothing
        r = run("--check")
        assert r.returncode == 1, f"--check on missing settings should drift: {r.stdout}{r.stderr}"
        assert not settings.exists(), "--check must never write"

        # default run reconciles for real
        r = run()
        assert r.returncode == 0, r.stderr
        got = json.loads(settings.read_text())["skillOverrides"]
        assert got == {"alpha": "name-only", "beta": "name-only", "skill-search": "on"}, got

        # now in sync -> --check exits 0, and --if-changed writes nothing (no backup churn)
        assert run("--check").returncode == 0
        before = sorted(p.name for p in d.iterdir())
        assert run("--if-changed").returncode == 0
        assert sorted(p.name for p in d.iterdir()) == before, "no-op --if-changed must not churn"

        # a keep-on edit is drift -> --if-changed rewrites (alpha flips to on)
        (d / "keep.json").write_text(json.dumps({"keep_on": ["skill-search", "alpha"]}),
                                     encoding="utf-8")
        assert run("--if-changed").returncode == 0
        assert json.loads(settings.read_text())["skillOverrides"]["alpha"] == "on"

    print("selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Apply/reconcile skill-concierge name-only overrides.")
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit (1=drifted, 0=in sync); never writes")
    ap.add_argument("--if-changed", dest="if_changed", action="store_true",
                    help="reconcile ONLY when drifted — no backup churn on a no-op session")
    ap.add_argument("--selftest", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.selftest:
        return _selftest()

    keepon = keepon_path(ROOT)     # stable user-state path, seeded from the shipped default
    raw = json.loads(keepon.read_text(encoding="utf-8"))
    keep_list = raw.get("keep_on")
    if not isinstance(keep_list, list) or not keep_list:
        print(f"keep-on policy invalid: '{keepon}' needs a non-empty \"keep_on\" list — "
              f"refusing (a missing/blank list would set EVERY skill to name-only).",
              file=sys.stderr)
        return 1
    keep_on = set(keep_list)
    if "skill-search" not in keep_on:
        print("WARN: 'skill-search' (the router) is not in keep_on — the retriever entry "
              "point would go name-only/dark. Add it unless that's intended.", file=sys.stderr)

    names = sorted(set(discover_skill_names()))
    if not names:
        print("no skills discovered — refusing to write empty overrides", file=sys.stderr)
        return 1

    overrides = _compute_overrides(keep_on, names)
    missing = sorted(keep_on - set(names))   # keep-on entries absent on this machine

    settings = {}
    if SETTINGS.exists():
        settings = json.loads(SETTINGS.read_text(encoding="utf-8"))
    added, removed, flipped = _diff(overrides, settings.get("skillOverrides", {}))
    drifted = bool(added or removed or flipped)

    # --check: read-only drift detector (doctor uses this). Exit code carries the verdict.
    if args.check:
        _report_drift(overrides, added, removed, flipped)
        return 1 if drifted else 0

    # --if-changed: the autonomous hook path — skip the write (and its backup) on a no-op.
    if args.if_changed and not drifted:
        on = sum(1 for v in overrides.values() if v == "on")
        print(f"skillOverrides in sync — {on} on / {len(overrides) - on} name-only; "
              f"no drift, not rewriting")
        return 0

    on = _write_settings(settings, overrides)
    print(f"wrote  : {SETTINGS}")
    print(f"applied: {on} on / {len(overrides) - on} name-only   (skills discovered: {len(names)})")
    if drifted:
        _report_drift(overrides, added, removed, flipped)
    if missing:
        print(f"NOTE   : {len(missing)} keep-on entr(ies) not present on this machine "
              f"(left unset — they'll apply if those skills get installed): {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
