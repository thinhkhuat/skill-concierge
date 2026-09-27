"""skill-concierge findability sweep and ratchet (ADR-0074, v0.55.0).

Measures whether a skill can be found by its OWN words, and remembers the answer so a
regression — or a new skill that was never findable to begin with — gets reported instead
of silently sitting in the index. Two probes, both read-only against the local index owner:

  1. Name-word probe (PRIMARY, Thinh's decision 2026-09-27). Every installed, non-catalog,
     claude-invocable skill contributes one DISTINCTIVE name token (>=4 chars, not generic,
     not a digit run, appearing in <=5 skills' name+description — the same rule
     `scripts/precision_eval.py`'s `findability` mode uses for its W set). The token is
     embedded via the owner's `/embed` and its skill's RANK is read in the `search_skills`
     SHAPE: `group_by=name`, the engine's own `_scope_filter()`, no tier exclusion (externals
     compete, exactly as `search_skills` lets them).
  2. Own-phrase score (SECONDARY). Leave-one-out over each of the skill's TRIGGER points'
     stored vectors (fetched via `scroll` with `with_vector=true`): query with that vector,
     `group_by=name`, `group_size=2`, excluding the probe's own point by id (`has_id`) and
     excluding external-tier rows — the enforcer's installed-only shape. The skill's score is
     the fraction of its own trigger points for which its group still lands in the top 6.

Ratchet: baselines only move up (lower name-word rank, higher own-phrase score), or via
`--accept <skill>`. The FIRST sweep ever (no prior findability.json) seeds the baseline and
warns about nothing. After that:
  (a) a NEW skill not in the top 3 for its own name word -> WARN, naming the current #1.
  (b) a KNOWN skill whose name-word rank falls from (ever having been) top-3 to outside it,
      OR whose own-phrase score falls >= 0.25 below its best AND below 0.5 -> WARN.
A skill whose probe TOKEN changes between sweeps (a rename, or the document-frequency count
shifting which word is rarest) restarts that skill's name-word ratchet from the new token's
current rank — comparing ranks of two different words would not mean anything.

CLI:
  python -m skill_search.findability --sweep     run a sweep, update the baseline (idempotent,
                                                  self-throttled to one sweep per 10 minutes,
                                                  quiet exit (0) when throttled, lock-contended,
                                                  or the owner is unreachable; NEVER raises)
  python -m skill_search.findability --report    human-readable summary of the last sweep
  python -m skill_search.findability --json      the last sweep's findability.json, verbatim
  python -m skill_search.findability --accept X   reset skill X's baseline to its current state

Output: SKILL_FINDABILITY_PATH, else ~/.claude/skill-concierge/findability.json:
  {"version": 1, "swept_at": <epoch>, "harness": "claude",
   "skills": {name: {"name_word": {"token", "rank", "best"}?,
                      "own_phrase": {"score", "best"}?,
                      "first_seen": <epoch>}},
   "warnings": [<str>, ...], "backlog": <int>}
`backlog` = the count of skills with a name-word probe that are not in the top 3 for it.

`--sweep` always runs pinned to the `claude` harness and from a FIXED cwd (`~`), regardless
of the caller's own cwd or ambient `SKILL_CONCIERGE_HARNESS` — so the view it measures never
depends on which project's session happened to trigger the reindex that launched it (the
engine's `build_index` hook launches it with `cwd=~` already; `--sweep` re-asserts this
itself so a manual invocation from anywhere behaves identically). Owner URLs use the
owner's own bind ports, from the same `skill_search.ports` rule the owner applies, because
this module talks to the owner directly, the same way the owner talks to itself.

Approximation, disclosed (v4 adversarial review, "the ratchet does not pin the project
directory"): running from a fixed `~` with no project scope neutralizes cross-harness/project
isolation for the overwhelming majority of installed skills, so the own-phrase probe's
competing-group filter is `tier != external` only (the same filter `_retrieve`/`_jev_catalog`
apply), not a full per-row `_row_invocable` re-check of every OTHER skill in the ranking. The
skill being probed IS filtered through the real `_row_invocable` (see `_installed_skills`).
"""
from __future__ import annotations

import argparse
import fcntl
import importlib.util
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path

# ── name-word probe: token selection (mirrors evidence/rare_token_probe.py, the proven
# probe this design measured 179/236 with; scripts/precision_eval.py's `findability` mode
# reuses these same functions/constants for its own W set — "the same rule as D") ──────────
GENERIC_NAME_WORDS = {"skill", "skills", "doctor", "helper", "tool", "tools", "agent",
                       "agents", "plugin", "manager", "expert", "pro"}
NAME_TOKEN_MIN_LEN = 4
DF_MAX = 5                       # a token qualifies when <= this many skills carry it
_NAME_SPLIT_RE = re.compile(r"[-_./]")
_WORD_RE = re.compile(r"\w+", re.UNICODE)

# ── ratchet thresholds (design.md v4.1 SS4 D) ───────────────────────────────────────────────
TOPN_NAME = 3                    # the name-word "top 3" gate
TOPN_OWNPHRASE = 6               # the own-phrase "top 6" gate
LOO_GROUP_SIZE = 2                # group_size for the leave-one-out query
NAME_RANK_DEPTH = 60              # how deep the search_skills-shape rank query looks
HYSTERESIS_DELTA = 0.25
HYSTERESIS_FLOOR = 0.5
THROTTLE_S = 600                  # at most one sweep per 10 minutes

COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")


def _findability_path() -> Path:
    return Path(os.environ.get("SKILL_FINDABILITY_PATH")
                or (Path.home() / ".claude" / "skill-concierge" / "findability.json"))


def _lock_path() -> Path:
    p = _findability_path()
    return p.with_name(p.name + ".lock")


# ── owner URLs: the owner's own bind ports, derived by the one shared rule
# (skill_search.ports) — this module is a PEER of the owner talking to it directly. ────────
def _owner_urls() -> tuple:
    from skill_search import ports
    return (f"http://127.0.0.1:{ports.query_port()}",
            f"http://127.0.0.1:{ports.embed_port()}")


# ── thin stdlib HTTP client for the owner's Qdrant-compatible REST subset + /embed ──────────
def _post(url: str, body: dict, timeout: float = 10.0) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read() or b"{}")


def _owner_embed(embed_base: str, text: str, timeout: float = 5.0) -> list:
    return _post(embed_base + "/embed", {"text": text}, timeout)["vector"]


def _owner_alive(embed_base: str, timeout: float = 2.0) -> bool:
    """GET /health on the embed port — the owner's OWN readiness signal, not an actual embed
    call: cheaper, and correctly distinguishes "down/still loading" (503, or refused/timeout)
    from "up" without spending a real embedding on every throttle-adjacent probe."""
    try:
        with urllib.request.urlopen(embed_base + "/health", timeout=timeout):
            pass
    except Exception:  # noqa: BLE001 — refused, timeout, or a non-2xx (still loading) = down
        return False
    return True


def _query_groups(query_base: str, collection: str, vector: list, group_by: str, limit: int,
                  group_size: int = 1, filt: dict | None = None, timeout: float = 10.0) -> list:
    body = {"query": list(vector), "group_by": group_by, "limit": limit,
            "group_size": group_size, "with_payload": True}
    if filt is not None:
        body["filter"] = filt
    res = _post(query_base + f"/collections/{collection}/points/query/groups", body, timeout)
    return (res.get("result") or {}).get("groups", [])


def _scroll_trigger_points(query_base: str, collection: str, name: str,
                          timeout: float = 10.0) -> list:
    """[(point_id, vector), ...] for every `kind=trigger` point of `name`."""
    flt = {"must": [{"key": "name", "match": {"value": name}},
                    {"key": "kind", "match": {"value": "trigger"}}]}
    points, offset = [], None
    while True:
        body = {"limit": 64, "with_payload": False, "with_vector": True, "filter": flt}
        if offset is not None:
            body["offset"] = offset
        res = _post(query_base + f"/collections/{collection}/points/scroll", body, timeout)
        result = res.get("result") or {}
        for p in result.get("points") or []:
            v = p.get("vector")
            if v:
                points.append((p["id"], v))
        offset = result.get("next_page_offset")
        if offset is None:
            break
    return points


# ── skill enumeration + name-token selection ────────────────────────────────────────────────
def _load_enforcer():
    """Load hooks/scripts/enforcer.py the way scripts/calibrate_jev_gate.py's `load_enforcer`
    does, pinned to the `claude` harness so `_row_invocable`'s cross-harness twin test and
    project isolation resolve deterministically regardless of the ambient environment (the
    PLAN.md interface contract: "harness pinned to claude"). Returns None (never raises) when
    the enforcer cannot be found or fails to import — callers must treat that as "nothing safe
    to sweep" and exit quietly, the same as an unreachable owner."""
    root = Path(__file__).resolve().parents[3]
    path = root / "hooks" / "scripts" / "enforcer.py"
    if not path.exists():
        return None
    os.environ["SKILL_CONCIERGE_HARNESS"] = "claude"
    os.environ.setdefault("SKILL_CONCIERGE_LOG", tempfile.mkdtemp(prefix="findability-"))
    try:
        spec = importlib.util.spec_from_file_location("skill_concierge_findability_enforcer", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:  # noqa: BLE001 — a sweep must never crash on a bad enforcer copy
        return None


def _installed_skills(enf, sd) -> list:
    """Non-catalog, claude-invocable skills — reuses the enforcer's own `_row_invocable`
    (project isolation, cross-harness twin, plugin gate) rather than re-deriving it."""
    out = []
    for s in sd.discover_skills():
        scope = s.get("scope", "personal")
        if scope.startswith("catalog:"):
            continue
        if enf._row_invocable(s["name"], scope):
            out.append(s)
    return out


def _name_tokens(name: str) -> list:
    base = name.split(":")[-1].lower()
    return [t for t in _NAME_SPLIT_RE.split(base)
            if len(t) >= NAME_TOKEN_MIN_LEN and t not in GENERIC_NAME_WORDS and not t.isdigit()]


def document_frequency(skills: list) -> Counter:
    """token -> number of DISCOVERED skills (every scope, catalog included — the whole
    universe a word must be rare ACROSS, not just the claude-invocable subset) whose
    name+description contains it as a whole word."""
    df = Counter()
    for s in skills:
        text = (re.sub(r"[-_:./]", " ", s["name"]) + " " + (s.get("description") or "")).lower()
        for t in set(_WORD_RE.findall(text)):
            df[t] += 1
    return df


def probe_token(name: str, df) -> str | None:
    """The skill's single most distinctive name token (lowest document frequency, ties
    broken by left-to-right position in the name) that qualifies (<=DF_MAX skills carry it),
    or None when the name carries no qualifying word. Exposed (no leading underscore) because
    scripts/precision_eval.py's `findability` mode reuses it verbatim for its own W set."""
    candidates = [(df.get(t, 0), i, t) for i, t in enumerate(_name_tokens(name))
                 if 0 < df.get(t, 0) <= DF_MAX]
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][2]


# ── the two probes ───────────────────────────────────────────────────────────────────────────
def name_word_rank(query_base: str, collection: str, scope_filter: dict, vector: list,
                   name: str, depth: int = NAME_RANK_DEPTH) -> tuple:
    """(rank, winner) in the search_skills SHAPE: group_by=name, the real scope filter, no
    tier exclusion (externals compete). rank = depth + 1 when not found within `depth` groups.
    winner = whichever skill's group currently ranks #1 for this query."""
    groups = _query_groups(query_base, collection, vector, "name", depth,
                           group_size=1, filt=scope_filter)
    winner = groups[0].get("id") if groups else None
    for i, g in enumerate(groups, 1):
        if g.get("id") == name:
            return i, winner
    return depth + 1, winner


def _tier_rows(groups: list) -> list:
    """[{"name","score"}] from a groups response — the row shape `srv._arrange_tiers` expects."""
    rows = []
    for g in groups:
        hits = g.get("hits") or []
        if hits:
            rows.append({"name": g.get("id"), "score": float(hits[0].get("score", 0.0))})
    return rows


def complement_rank(query_base: str, collection: str, srv, vector: list, name: str,
                    depth: int = NAME_RANK_DEPTH) -> tuple:
    """(rank, winner) as `search_skills()` ACTUALLY ranks it once the installed/
    external complement rule (SKILL_SEARCH_COMPLEMENT) is on: two separate queries (`srv._installed_only_filter`/
    `srv._external_only_filter`), each ranked to `depth`, then arranged by `srv._arrange_tiers`
    — the SAME functions `search_skills()` itself calls, reused rather than re-derived, just
    at a depth deeper than its own hardcoded TOP_K so a rank beyond the visible offer is still
    measured. Callers must gate this on the loaded `srv` actually carrying that machinery AND
    having it turned on (`search_skills_rank` does this automatically); calling it against a
    `srv` without that rule raises AttributeError on purpose — there is no reasonable arrangement to fall
    back to from inside this function without silently hiding that the code it was asked to
    measure does not exist."""
    inst = _tier_rows(_query_groups(query_base, collection, vector, "name", depth,
                                    group_size=1, filt=srv._installed_only_filter()))
    ext = _tier_rows(_query_groups(query_base, collection, vector, "name", depth,
                                   group_size=1, filt=srv._external_only_filter()))
    arranged = srv._arrange_tiers(inst, ext, depth)
    winner = arranged[0]["name"] if arranged else None
    for i, row in enumerate(arranged, 1):
        if row["name"] == name:
            return i, winner
    return depth + 1, winner


def search_skills_rank(query_base: str, collection: str, scope_filter: dict, srv, vector: list,
                       name: str, depth: int = NAME_RANK_DEPTH) -> tuple:
    """(rank, winner) matching whatever `search_skills()` ACTUALLY does for this `srv` instance:
    the installed/external complement arrangement (`complement_rank`) when `srv` carries it and it is
    turned on, else the plain single-query shape every release before the rule used
    (`name_word_rank`). Measuring an owner without the rule (or with it switched off) through the plain shape and
    an owner with it on through the complement shape is not an inconsistency to paper over — it is
    the one honest way to compare what `search_skills()` truly returns on each side, which is
    the whole point of a base-vs-candidate rank comparison."""
    if getattr(srv, "_search_complement_on", lambda: False)():
        return complement_rank(query_base, collection, srv, vector, name, depth)
    return name_word_rank(query_base, collection, scope_filter, vector, name, depth)


def own_phrase_score(query_base: str, collection: str, name: str, points: list) -> float | None:
    """Fraction of `name`'s own trigger points (leave-one-out, installed-only) for which its
    group still lands in the top TOPN_OWNPHRASE. None when the skill has no trigger points."""
    if not points:
        return None
    hits = 0
    for pid, vec in points:
        filt = {"must_not": [{"key": "tier", "match": {"value": "external"}}, {"has_id": [pid]}]}
        groups = _query_groups(query_base, collection, vec, "name", TOPN_OWNPHRASE,
                               group_size=LOO_GROUP_SIZE, filt=filt)
        if any(g.get("id") == name for g in groups):
            hits += 1
    return hits / len(points)


# ── ratchet (pure — no I/O; the whole point of decomposing it this way is that it is
# testable without any owner, real or stubbed) ──────────────────────────────────────────────
def apply_ratchet(prev: dict | None, measured: dict, now: float) -> tuple:
    """(skills_out, warnings, backlog). `prev` is the PREVIOUS findability.json (or None on
    the very first sweep, which seeds every baseline and warns about nothing). `measured` is
    {name: {"name_word": {"token","rank","winner"} | None, "own_phrase": {"score"} | None}} —
    THIS sweep's fresh reading, with no "best" yet (that is this function's job)."""
    first_sweep = prev is None            # seeds every baseline; never warns, regardless of p
    prev_skills = (prev or {}).get("skills") or {}
    warnings = []
    out = {}
    for name in sorted(measured):
        m = measured[name]
        p = prev_skills.get(name)
        entry = {"first_seen": (p.get("first_seen", now) if p else now)}

        nw = m.get("name_word")
        if nw is not None:
            tok, rank, winner = nw["token"], nw["rank"], nw.get("winner")
            prev_nw = p.get("name_word") if p else None
            # A probe token change (rename, or the DF count shifting which word is rarest)
            # restarts the ratchet for this mechanism: comparing ranks of two different
            # words is not a regression, it is a different question.
            carries = prev_nw is not None and prev_nw.get("token") == tok
            best = min(prev_nw["best"], rank) if carries else rank
            entry["name_word"] = {"token": tok, "rank": rank, "best": best}
            if first_sweep:
                pass
            elif p is None:
                if rank > TOPN_NAME:
                    warnings.append(
                        f"new skill {name!r}: rank {rank} for its own name word {tok!r} "
                        f"(top: {winner!r})")
            elif carries and prev_nw["best"] <= TOPN_NAME and rank > TOPN_NAME:
                warnings.append(
                    f"{name!r} fell out of the top {TOPN_NAME} for its name word {tok!r}: "
                    f"now rank {rank} (top: {winner!r})")

        op = m.get("own_phrase")
        if op is not None:
            score = op["score"]
            prev_op = p.get("own_phrase") if p else None
            best = max(prev_op["best"], score) if prev_op is not None else score
            entry["own_phrase"] = {"score": score, "best": best}
            if (prev_op is not None and (prev_op["best"] - score) >= HYSTERESIS_DELTA
                    and score < HYSTERESIS_FLOOR):
                warnings.append(
                    f"{name!r} own-phrase score dropped to {score:.2f} "
                    f"(best {prev_op['best']:.2f})")

        out[name] = entry
    backlog = sum(1 for e in out.values()
                 if e.get("name_word") and e["name_word"]["rank"] > TOPN_NAME)
    return out, warnings, backlog


# ── JSON I/O ──────────────────────────────────────────────────────────────────────────────
def _read_json(path: Path) -> dict | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)          # atomic within the directory: old or new, never torn


# ── lock ──────────────────────────────────────────────────────────────────────────────────
def _acquire_lock():
    lock_path = _lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "w", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    return fh


def _release_lock(fh) -> None:
    if fh is None:
        return
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    finally:
        fh.close()


# ── the sweep itself ──────────────────────────────────────────────────────────────────────
def _run_sweep(enf, sd, srv, query_base: str, embed_base: str, collection: str) -> dict:
    """{name: {"name_word": {...} | absent, "own_phrase": {...} | absent}} — the measurement,
    with no ratchet applied yet."""
    skills = _installed_skills(enf, sd)
    df = document_frequency(sd.discover_skills())
    scope_filter = srv._scope_filter()
    measured = {}
    for s in skills:
        name = s["name"]
        entry = {}
        tok = probe_token(name, df)
        if tok is not None:
            vector = _owner_embed(embed_base, tok)
            rank, winner = search_skills_rank(query_base, collection, scope_filter, srv,
                                              vector, name)
            entry["name_word"] = {"token": tok, "rank": rank, "winner": winner}
        points = _scroll_trigger_points(query_base, collection, name)
        score = own_phrase_score(query_base, collection, name, points)
        if score is not None:
            entry["own_phrase"] = {"score": score}
        measured[name] = entry
    return measured


def cmd_sweep() -> int:
    now = time.time()
    path = _findability_path()
    lock_fh = _acquire_lock()
    if lock_fh is None:
        return 0                                       # another sweep is already running
    try:
        prev = _read_json(path)
        if prev is not None and (now - float(prev.get("swept_at", 0) or 0)) < THROTTLE_S:
            return 0                                   # throttled
        query_base, embed_base = _owner_urls()
        if not _owner_alive(embed_base):
            return 0                                   # owner unreachable
        os.chdir(Path.home())                          # pin the view before ANY engine import
        enf = _load_enforcer()
        if enf is None:
            return 0
        try:
            from skill_search import server as srv
            from skill_search import skills_discovery as sd
            measured = _run_sweep(enf, sd, srv, query_base, embed_base, COLLECTION)
            skills_out, warnings, backlog = apply_ratchet(prev, measured, now)
            data = {"version": 1, "swept_at": now, "harness": "claude",
                    "skills": skills_out, "warnings": warnings, "backlog": backlog}
            _write_json(path, data)
        except Exception:  # noqa: BLE001 — runs detached, stdio to devnull: never surface
            return 0
        return 0
    finally:
        _release_lock(lock_fh)


def cmd_report() -> int:
    data = _read_json(_findability_path())
    if data is None:
        print(f"findability: not yet swept ({_findability_path()})")
        return 0
    when = time.strftime("%Y-%m-%d %H:%M", time.localtime(data.get("swept_at", 0) or 0))
    print(f"findability sweep at {when} (harness {data.get('harness', '?')})")
    print(f"backlog: {data.get('backlog', '?')} skill(s) not in the top {TOPN_NAME} for their "
          "own name word")
    warnings = data.get("warnings") or []
    if warnings:
        print(f"{len(warnings)} warning(s):")
        for w in warnings:
            print(f"  - {w}")
    else:
        print("no warnings")
    return 0


def cmd_json() -> int:
    data = _read_json(_findability_path())
    print(json.dumps(data if data is not None else {"swept": False}, indent=1, ensure_ascii=False))
    return 0


def cmd_accept(name: str) -> int:
    path = _findability_path()
    data = _read_json(path)
    if data is None or name not in (data.get("skills") or {}):
        print(f"findability: no record for {name!r}", file=sys.stderr)
        return 1
    entry = data["skills"][name]
    if "name_word" in entry:
        entry["name_word"]["best"] = entry["name_word"]["rank"]
    if "own_phrase" in entry:
        entry["own_phrase"]["best"] = entry["own_phrase"]["score"]
    _write_json(path, data)
    print(f"accepted the current state for {name!r} as its new baseline")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m skill_search.findability",
                                 description="Findability sweep and ratchet (ADR-0074).")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sweep", action="store_true", help="run a sweep and update the baseline")
    g.add_argument("--report", action="store_true", help="human-readable summary of the last sweep")
    g.add_argument("--json", action="store_true", help="the last sweep's findability.json, verbatim")
    g.add_argument("--accept", metavar="SKILL", help="accept SKILL's current state as its new baseline")
    args = ap.parse_args(argv)
    if args.sweep:
        return cmd_sweep()
    if args.report:
        return cmd_report()
    if args.json:
        return cmd_json()
    return cmd_accept(args.accept)


if __name__ == "__main__":
    sys.exit(main())
