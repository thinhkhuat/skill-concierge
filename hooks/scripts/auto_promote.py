#!/usr/bin/env python3
"""
skill-concierge — usage-promotion self-heal (SessionStart hook, ADR-0032 Phase 3).

External catalog skills (ADR-0031) are search-only + annex citizens (ADR-0032): retrievable
and consumable via get_skill, but NOT registered with Claude Code, so the Skill tool can't
invoke them. When the agent USES one repeatedly, it has earned first-class status. This hook
graduates it: a catalog skill whose external `get_skill` takes span ≥ PROMOTE_MIN_TAKES
DISTINCT sessions is symlink-promoted into ~/.claude/skills via `catalogs.py promote`, becoming
a real installed (Skill-tool-invocable) skill under the concierge's name-only budget. Organic
curation — the resident set grows only by demonstrated usage, never by mass install.

Design contract (mirrors auto_flywheel.py):
  • FAIL-OPEN — no ledger, no catalog config, promote error -> silent no-op, exit 0.
  • NON-BLOCKING — promotion is a symlink (cheap); runs inline but is bounded + throttled.
  • THROTTLED — at most one pass per AUTO_PROMOTE_THROTTLE_S (default 21600s = 6h).
  • IDEMPOTENT — an already-promoted skill (name exists in ~/.claude/skills) is refused by
    catalogs.py promote and skipped; re-running never double-promotes.
  • GATED — PROMOTE_ENABLED=0 disables the hook (default "1" = ON).

Distinct-session counting uses ledger `sid` uniqueness and EXCLUDES subagent rows (`sub`).
"""
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

LOGDIR = Path(os.environ.get("SKILL_CONCIERGE_LOG", Path.home() / ".claude/skill-concierge/logs"))
LEDGER = LOGDIR / "skill-invocation-ledger.log"
STAMP = LOGDIR / ".auto-promote-stamp"
LOGFILE = LOGDIR / "auto-promote.log"
THROTTLE_S = int(os.environ.get("AUTO_PROMOTE_THROTTLE_S", "21600"))
MIN_TAKES = int(os.environ.get("PROMOTE_MIN_TAKES", "3"))
ENABLED = os.environ.get("PROMOTE_ENABLED", "1") != "0"
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT", Path(__file__).resolve().parent.parent.parent))
CATALOGS_PY = PLUGIN_ROOT / "scripts" / "catalogs.py"
CATALOG_ROOTS = Path(os.environ.get(
    "SKILL_CONCIERGE_CATALOG_ROOTS",
    Path.home() / ".claude" / "skill-concierge" / "catalog-roots.json"))
LEDGER_TAIL_BYTES = 1_048_576   # scan at most the last 1 MB of the ledger


def _aliases() -> tuple:
    """Configured catalog alias prefixes (`antigravity:` …), or () when none/unreadable."""
    try:
        cfg = json.loads(CATALOG_ROOTS.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(cfg, dict):
        return ()
    return tuple(f"{a}:" for a in cfg if isinstance(a, str) and not a.startswith("_"))


def _distinct_session_takes(aliases: tuple) -> dict:
    """{external_skill_name: set(distinct sids)} from external get_skill takes (sub excluded)."""
    takes = defaultdict(set)
    if not aliases:
        return takes
    try:
        size = LEDGER.stat().st_size
        with LEDGER.open("rb") as f:
            f.seek(max(0, size - LEDGER_TAIL_BYTES))
            lines = f.read().decode("utf-8", "replace").splitlines()
        if size > LEDGER_TAIL_BYTES:
            lines = lines[1:]           # drop the partial first line
    except OSError:
        return takes
    for line in lines:
        try:
            e = json.loads(line)
            if not isinstance(e, dict):
                continue
        except ValueError:
            continue
        if e.get("ev") != "get_skill" or e.get("sub"):
            continue
        name = e.get("name") or ""
        sid = e.get("sid") or ""
        if isinstance(sid, str) and sid and isinstance(name, str) and name.startswith(aliases):
            takes[name].add(sid)
    return takes


def _promote(name: str) -> tuple:
    """Run catalogs.py promote for one <alias>:<name>. Returns (ok, message)."""
    try:
        r = subprocess.run(
            [sys.executable, str(CATALOGS_PY), "promote", name],
            capture_output=True, text=True, timeout=15, check=False,
            env={**os.environ, "SKILL_CONCIERGE_CATALOG_ROOTS": str(CATALOG_ROOTS)})
        out = (r.stdout or r.stderr or "").strip()
        return r.returncode == 0, (out.splitlines()[0] if out else "")
    except (OSError, UnicodeError, subprocess.SubprocessError) as e:
        return False, str(e)


def _log(msg: str) -> None:
    try:
        LOGDIR.mkdir(parents=True, exist_ok=True)
        with LOGFILE.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    except (OSError, UnicodeError):
        return


def _recent(path: Path, window: int) -> bool:
    try:
        return (time.time() - path.stat().st_mtime) < window
    except OSError:
        return False


def run_once() -> int:
    """Promote every external skill at/over the distinct-session threshold. Returns count promoted."""
    aliases = _aliases()
    takes = _distinct_session_takes(aliases)
    _write_takes_digest(takes)
    promoted = 0
    for name, sids in sorted(takes.items()):
        if len(sids) < MIN_TAKES:
            continue
        ok, msg = _promote(name)
        if ok:
            promoted += 1
            _log(f"promoted {name} ({len(sids)} sessions): {msg}")
        else:
            # collision / already promoted / error — idempotent skip, logged at debug volume
            _log(f"skip {name} ({len(sids)} sessions): {msg}")
    return promoted


# Both digests default to the folder that holds the ledger they are built from (the durable home
# for the default ledger). A run on another ledger (SKILL_CONCIERGE_LOG, e.g. a smoke test's empty
# temp folder) then writes beside it and can never overwrite the live digests: on 2026-10-10 smoke
# runs did exactly that and emptied the live 🔥 badges and external-take counts.
TAKES_DIGEST = Path(os.environ.get(
    "SKILL_CONCIERGE_TAKES_DIGEST", LOGDIR.parent / "external-takes.json"))


def _write_takes_digest(takes: dict) -> None:
    """ADR-0048: dump {name: distinct-session take count} for the enforcer's annex
    usage ranking. Advisory only — a failed write leaves the previous digest, and an
    absent digest ranks the annex by score alone (fail-open both sides)."""
    try:
        data = {name: len(sids) for name, sids in sorted(takes.items()) if sids}
        tmp = TAKES_DIGEST.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, TAKES_DIGEST)
    except (OSError, UnicodeError, ValueError):
        return


# ADR-0083 🔥 proven: an installed skill invoked (Skill tool, auto or manual; subagent rows
# excluded) in at least PROVEN_MIN_SESSIONS distinct sessions within PROVEN_WINDOW_DAYS. The
# enforcer reads the digest live and badges those rows; the badge never moves a row. 5 sessions
# in 30 days was the owner's pick (2026-10-07): 28 of the 169 skills used in that window.
REPUTATION_ON = os.environ.get("SKILL_REPUTATION", "1") != "0"
PROVEN_DIGEST = Path(os.environ.get("SKILL_CONCIERGE_PROVEN", LOGDIR.parent / "proven.json"))
def _env_int(name, default):
    """A malformed tunable falls back to its default: a session-start hook never dies over an env typo."""
    try:
        return max(1, int(os.environ.get(name, default)))
    except ValueError:
        return default


PROVEN_MIN_SESSIONS = _env_int("SKILL_PROVEN_MIN_SESSIONS", 5)
PROVEN_WINDOW_DAYS = _env_int("SKILL_PROVEN_WINDOW_DAYS", 30)


SKILLS_ROOT = Path(os.environ.get("SKILL_CONCIERGE_SKILLS_ROOT", Path.home() / ".claude" / "skills"))


def _personal_aliases() -> dict:
    """{frontmatter name: directory name} for personal skills whose two names differ. The menu
    names a personal skill by its directory; the ledger records whatever name the Skill tool got
    (both `ak-cook` and `ak:cook` arrive), so usage is folded onto the directory name."""
    out = {}
    for p in SKILLS_ROOT.glob("*/SKILL.md"):
        try:
            with p.open(encoding="utf-8", errors="replace") as f:
                for i, line in enumerate(f):
                    if i > 30:
                        break
                    if line.startswith("name:"):
                        fm = line.split(":", 1)[1].strip().strip("\"'")
                        if fm and fm != p.parent.name:
                            out[fm] = p.parent.name
                        break
        except OSError:
            continue
    return out


def _ledger_start(evs=("auto", "manual")):
    """Epoch time of the oldest counted event (the ledger is append-only, so the first one), or None."""
    try:
        with LEDGER.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("ev") in evs and isinstance(e.get("t"), (int, float)):
                    return float(e["t"])
    except OSError:
        return None
    return None


def _proven_counts(now=None, evs=("auto", "manual"), window_days=None, aliases=None) -> dict:
    """{skill: distinct-session count} over the window, from the whole ledger (fail-open: {}).
    `evs`: the ledger events that count as a use (🔥 counts Skill-tool loads only). Frontmatter
    names fold onto the directory name the menu shows (`aliases`, default read from disk)."""
    days = PROVEN_WINDOW_DAYS if window_days is None else window_days
    since = (now or time.time()) - days * 86400
    sids = defaultdict(set)
    try:
        with LEDGER.open(encoding="utf-8", errors="replace") as f:
            for line in f:
                if not any(f'"{ev}"' in line for ev in evs):
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                t = e.get("t")
                if (e.get("ev") in evs and not e.get("sub") and isinstance(t, (int, float))
                        and t >= since and isinstance(e.get("name"), str) and e.get("sid")):
                    sids[e["name"]].add(e["sid"])
    except OSError:
        return {}
    if aliases is None:
        try:   # a bare plugin-skill name (`bro`) folds onto the menu's `pstack:bro`
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from skill_names import plugin_bare_aliases
            aliases = {**plugin_bare_aliases(), **_personal_aliases()}
        except Exception:  # noqa: BLE001 — the 🔥 digest is advisory, never fatal
            aliases = _personal_aliases()
    folded = defaultdict(set)
    for n, s in sids.items():
        folded[aliases.get(n, n)] |= s
    return {n: len(s) for n, s in folded.items()}


def _write_proven(counts: dict) -> None:
    """Atomic digest write; a failed write leaves the previous digest (the badge is advisory)."""
    keep = {n: c for n, c in sorted(counts.items()) if c >= PROVEN_MIN_SESSIONS}
    data = {"_note": "Written by auto_promote.py (ADR-0083). Skills invoked in at least "
                     f"{PROVEN_MIN_SESSIONS} distinct sessions in the last {PROVEN_WINDOW_DAYS} days; "
                     "the enforcer badges them 🔥.",
            "window_days": PROVEN_WINDOW_DAYS, "min_sessions": PROVEN_MIN_SESSIONS,
            "proven": sorted(keep), "counts": keep}
    try:
        PROVEN_DIGEST.parent.mkdir(parents=True, exist_ok=True)
        tmp = PROVEN_DIGEST.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp, PROVEN_DIGEST)
    except (OSError, UnicodeError, ValueError):
        return


def main() -> int:
    try:
        promote = ENABLED and CATALOGS_PY.exists() and CATALOG_ROOTS.exists()
        if not (promote or REPUTATION_ON):
            return 0                                  # both features off / not installed
        if _recent(STAMP, THROTTLE_S):
            return 0                                  # throttled
        LOGDIR.mkdir(parents=True, exist_ok=True)
        STAMP.write_text(str(int(time.time())), encoding="utf-8")   # stamp before work
        if REPUTATION_ON:
            _write_proven(_proven_counts())
        if promote:
            n = run_once()
            if n:
                _log(f"pass complete: {n} promoted")
    except OSError:
        return 0                                      # fail-silent — never block session start
    return 0


def _selftest() -> int:
    import tempfile
    global LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES
    saved = (LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES)
    ok = True
    try:
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            CATALOG_ROOTS = tdp / "catalog-roots.json"
            CATALOG_ROOTS.write_text(json.dumps({"anti": {"path": str(tdp / "cat")}}))
            aliases = _aliases()
            ok &= aliases == ("anti:",)
            LEDGER = tdp / "ledger.log"
            rows = [
                {"ev": "get_skill", "sid": "s1", "name": "anti:x"},
                {"ev": "get_skill", "sid": "s2", "name": "anti:x"},
                {"ev": "get_skill", "sid": "s3", "name": "anti:x"},   # x: 3 distinct sids
                {"ev": "get_skill", "sid": "s1", "name": "anti:x"},   # dup sid -> not counted twice
                {"ev": "get_skill", "sid": "s1", "name": "anti:y"},
                {"ev": "get_skill", "sid": "s2", "name": "anti:y"},   # y: 2 distinct sids
                {"ev": "get_skill", "sid": "s9", "name": "anti:z", "sub": True},  # subagent -> excluded
                {"ev": "get_skill", "sid": "s4", "name": "installed"},            # non-external
            ]
            LEDGER.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
            takes = _distinct_session_takes(aliases)
            ok &= takes.get("anti:x") == {"s1", "s2", "s3"}
            ok &= takes.get("anti:y") == {"s1", "s2"}
            ok &= "anti:z" not in takes            # subagent row excluded
            ok &= "installed" not in takes         # non-external excluded
            # threshold: at MIN_TAKES=3, only x qualifies; at 2, x and y
            MIN_TAKES = 3
            q3 = sorted(n for n, s in takes.items() if len(s) >= MIN_TAKES)
            ok &= q3 == ["anti:x"]
            MIN_TAKES = 2
            q2 = sorted(n for n, s in takes.items() if len(s) >= MIN_TAKES)
            ok &= q2 == ["anti:x", "anti:y"]
            # empty ledger / no aliases -> no takes, no crash
            ok &= _distinct_session_takes(()) == {}
            # ADR-0048 digest: run_once dumps {name: count} for EVERY counted external
            # (not only ≥ threshold) to TAKES_DIGEST — rebound as the MODULE global
            # (the env seam resolves at import; a real operator digest must not be
            # touched by the selftest, and the selftest must not write the real one).
            global TAKES_DIGEST
            _saved_digest = TAKES_DIGEST
            TAKES_DIGEST = tdp / "takes-digest.json"
            try:
                _write_takes_digest(takes)
                got = json.loads(TAKES_DIGEST.read_text(encoding="utf-8"))
                ok &= got == {"anti:x": 3, "anti:y": 2}   # counts, not sid sets; sub/non-external absent
            finally:
                TAKES_DIGEST = _saved_digest
            # ADR-0083 🔥: distinct sessions per installed skill inside the window, subagents and
            # stale rows excluded; the digest lists only skills at/over PROVEN_MIN_SESSIONS.
            global PROVEN_DIGEST, PROVEN_MIN_SESSIONS
            _saved_proven = (PROVEN_DIGEST, PROVEN_MIN_SESSIONS)
            PROVEN_DIGEST, PROVEN_MIN_SESSIONS = tdp / "proven.json", 2
            try:
                now = time.time()
                LEDGER.write_text("\n".join(json.dumps(r) for r in [
                    {"ev": "auto", "sid": "a", "name": "hot", "t": now},
                    {"ev": "manual", "sid": "b", "name": "hot", "t": now},
                    {"ev": "auto", "sid": "a", "name": "hot", "t": now},            # same sid
                    {"ev": "auto", "sid": "c", "name": "warm", "t": now},
                    {"ev": "auto", "sid": "d", "name": "warm", "t": now, "sub": True},  # subagent
                    {"ev": "auto", "sid": "e", "name": "warm", "t": now - 400 * 86400},  # stale
                    {"ev": "get_skill", "sid": "f", "name": "warm", "t": now},     # not an invocation
                ]) + "\n")
                counts = _proven_counts(now, aliases={})
                ok &= counts == {"hot": 2, "warm": 1}
                # a frontmatter-name use folds onto the directory name the menu shows
                ok &= _proven_counts(now, aliases={"warm": "hot"}) == {"hot": 3}
                # the default aliases include unique bare plugin names (`bro` -> `pstack:bro`)
                import skill_names
                d = tdp / "pl" / "skills" / "hot"
                d.mkdir(parents=True)
                (d / "SKILL.md").write_text("x")
                (tdp / "reg.json").write_text(json.dumps({"plugins": {"pl@m": [{"installPath": str(tdp / "pl")}]}}))
                _seams = (skill_names.REGISTRY, skill_names.SKILLS_ROOT, SKILLS_ROOT)
                skill_names.REGISTRY, skill_names.SKILLS_ROOT = tdp / "reg.json", tdp / "none"
                globals()["SKILLS_ROOT"] = tdp / "none"
                try:
                    ok &= _proven_counts(now) == {"pl:hot": 2, "warm": 1}
                finally:
                    skill_names.REGISTRY, skill_names.SKILLS_ROOT, _r = _seams
                    globals()["SKILLS_ROOT"] = _r
                ok &= _ledger_start() is not None
                _write_proven(counts)
                got = json.loads(PROVEN_DIGEST.read_text(encoding="utf-8"))
                ok &= got["proven"] == ["hot"] and got["counts"] == {"hot": 2}
            finally:
                PROVEN_DIGEST, PROVEN_MIN_SESSIONS = _saved_proven
    finally:
        LEDGER, CATALOG_ROOTS, CATALOGS_PY, MIN_TAKES = saved
    print("auto-promote --selftest " + ("OK" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    sys.exit(main())
