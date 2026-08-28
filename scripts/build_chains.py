#!/usr/bin/env python3
"""
build_chains.py — mine real skill chains from the invocation ledger (Phase 1 of the
skill-chain-intelligence plan, plans/260628-…/plan.md — see repo plans/260828-0004-*).

The ADR-0029 CHAIN-HINT layer knows only what it is told: `next-skills:` frontmatter
(0.4% of the catalogue declares any) plus the operator's curated overrides. Meanwhile
the append-only ledger records ground truth — per-session ordered skill invocations —
and nothing reads it back. This miner closes that loop: ledger → successor map.

Output: ~/.claude/skill-concierge/mined-chains.json (durable home, survives plugin
updates — same convention as flywheel-manifest / thresholds). Shape:

    {"_meta": {"generated": ISO, "since": ISO|None, "events": N, "sessions": N,
               "params": {...}},
     "chains": {"ak-cook": ["ak-test", "ak-code-review"], ...}}

Scoring — support × lift, the pair filters that make sparse data honest:
  support(A→B)  how many sessions contain A immediately followed by B
                (consecutive repeats collapsed; subagent lanes excluded; names
                resolved against the reindex sidecar so built-in slashes and
                non-catalogue artifacts never enter);
  lift(A→B)     P(B | A-step) / P(B) over the same epoch. `session-handoff`-style
                closure skills follow nearly everything — their baseline P(B) is huge,
                so lift ≈ 1 and the pair dies without a hand-maintained drop-list.

Precedence (enforced at the ENFORCER's read seam, not here): operator overrides >
declared frontmatter > mined. This file only ever FILLS empty successor slots.

Usage:
  python3 scripts/build_chains.py                # mine with defaults, write map
  python3 scripts/build_chains.py --since 2026-08-20
  python3 scripts/build_chains.py --dry-run      # print, don't write
  python3 scripts/build_ch.py --selftest
"""
import argparse
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = Path(os.environ.get(
    "SKILL_CONCIERGE_LEDGER",
    Path.home() / ".claude" / "skill-concierge" / "logs" / "skill-invocation-ledger.log"))
SIDECAR = Path(os.environ.get(
    "SKILL_CONCIERGE_NEXT_SKILLS",
    Path.home() / ".claude" / "skill-concierge" / "next-skills.json"))
OUT = Path(os.environ.get(
    "SKILL_CONCIERGE_MINED_CHAINS",
    Path.home() / ".claude" / "skill-concierge" / "mined-chains.json"))

MIN_SUPPORT = 2          # a pair seen once is an anecdote, not a chain
MIN_LIFT = 1.5           # B must be ≥1.5× more likely after A than at baseline
MAX_GAP_S = 120 * 60     # adjacent steps >2h apart in one session are different sittings
MAX_SUCC = 3             # successors per skill, best-first — a menu, not a firehose

# ADR-0045 option (a), 0.38.1: get_skill body-pulls count toward MINED sequences (they
# are real usage — the agent chose to read the manual) but the pull is one step weaker
# than an invocation, so the CHAIN-HINT SEED stays invocation-only by design (enforcer's
# _last_used_skill is untouched). CHAIN_MINE_PULLS=0 reverts to invocations-only mining.
MINE_PULLS = os.environ.get("CHAIN_MINE_PULLS", "1") != "0"
_MINABLE_EV = ("auto", "manual", "get_skill") if MINE_PULLS else ("auto", "manual")


def _parse_when(s):
    """'YYYY-MM-DD'[:HH[:MM]] (local) -> epoch seconds, or None."""
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d:%H", "%Y-%m-%d:%H:%M"):
        try:
            return time.mktime(time.strptime(s, fmt))
        except ValueError:
            continue
    raise SystemExit(f"bad --since value: {s!r}")


def catalogue_names():
    """Union of every scope's name keys in the reindex-built sidecar — the same
    catalogue membership the enforcer's chain-hint filters against. Dangling names
    (built-in slashes, file-path artifacts the ledger's manual lane records) are not
    skills and never enter the map."""
    try:
        data = json.loads(SIDECAR.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError):
        return set()
    out = set()
    if isinstance(data, dict):
        for scope in data.values():
            if isinstance(scope, dict):
                out.update(k for k in scope if isinstance(k, str))
    return out


def load_sequences(ledger_path, catalogue, since=None):
    """Per-sid ordered [name] lists. Main-session invocation rows (auto/manual) plus —
    since 0.38.1, ADR-0045 option (a) — `get_skill` body-pull rows (CHAIN_MINE_PULLS=0
    reverts; subagent lanes are a different lane, ADR-0020, always excluded); names must
    resolve in the catalogue; consecutive repeats collapse (a re-invoked skill is one
    node)."""
    seqs = {}
    events = 0
    try:
        lines = ledger_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}, 0
    cutoff = since or 0.0
    for line in lines:
        line = line.strip()
        if not line or '"ev"' not in line:
            continue
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        if e.get("ev") not in _MINABLE_EV or e.get("sub"):
            continue
        t = float(e.get("t") or 0)
        if t < cutoff:
            continue
        name = e.get("name")
        if not isinstance(name, str) or not name or name == "?" or name not in catalogue:
            continue
        seq = seqs.setdefault(e.get("sid") or "", [])
        if seq and seq[-1][1] == name:
            continue          # consecutive repeat — one node, not a new event
        seq.append((t, name))  # (a gap > MAX_GAP_S is still adjacency: same session)
        events += 1
    return {sid: [n for _t, n in items] for sid, items in seqs.items()}, events


def mine(sequences, min_support=MIN_SUPPORT, min_lift=MIN_LIFT, max_succ=MAX_SUCC):
    """{name: [successors]} — support × lift filtered, best-first, capped.

    Baseline P(B) = sessions containing B / sessions. Signal P(B|A-step) =
    support(A→B) / steps-out-of-A. Lift = that ratio; a successor that just tracks
    B's own popularity lands near 1.0 and dies.
    """
    n_sess = max(len(sequences), 1)
    appears = Counter()
    steps_out = Counter()
    pairs = Counter()
    for seq in sequences.values():
        appears.update(set(seq))
        for a, b in zip(seq, seq[1:]):
            steps_out[a] += 1
            pairs[(a, b)] += 1
    base = {n: c / n_sess for n, c in appears.items()}
    out = {}
    for (a, b), sup in pairs.items():
        if sup < min_support:
            continue
        p_b = base.get(b, 0.0) or 1e-9
        lift = (sup / steps_out[a]) / p_b
        if lift < min_lift:
            continue
        out.setdefault(a, []).append((b, sup * lift))
    return {a: [n for n, _s in sorted(succ, key=lambda kv: (-kv[1], kv[0]))][:max_succ]
            for a, succ in out.items()}


def build(ledger_path=LEDGER, since=None, dry_run=False,
          min_support=MIN_SUPPORT, min_lift=MIN_LIFT, max_succ=MAX_SUCC):
    catalogue = catalogue_names()
    seqs, events = load_sequences(ledger_path, catalogue, since)
    chains = mine(seqs, min_support, min_lift, max_succ)
    doc = {
        "_meta": {
            "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "since": since,
            "events": events,
            "sessions": len(seqs),
            "params": {"min_support": min_support, "min_lift": min_lift,
                       "max_gap_s": MAX_GAP_S, "max_succ": max_succ},
        },
        "chains": chains,
    }
    if not dry_run:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        tmp = OUT.with_suffix(".tmp")
        tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(OUT)
    return doc


def _selftest():
    import tempfile

    real_ledger, real_sidecar, real_out = LEDGER, SIDECAR, OUT
    tmp = Path(tempfile.mkdtemp())
    try:
        # sidecar: catalogue with 6 skills
        (tmp / "sidecar.json").write_text(json.dumps(
            {"personal": {"a": [], "b": [], "c": [], "tail": [], "x": [], "y": []}}), encoding="utf-8")
        ledger = tmp / "ledger.jsonl"
        rows = []
        # 3 sessions of a->b (support 3) — real chain
        for i in range(3):
            sid = f"s{i}"
            rows += [{"t": 1000 + i * 10, "sid": sid, "ev": "auto", "name": "a"},
                     {"t": 1001 + i * 10, "sid": sid, "ev": "auto", "name": "b"}]
        # `tail` models a closure skill (like session-handoff): it follows MANY different
        # predecessors — x in 4 sessions, y in 4, a in 2 — so P(tail) is huge and every
        # ?->tail pair dies on lift (follows-everything is not a semantic successor).
        for i in range(4):
            sid = f"t{i}"
            rows += [{"t": 3000 + i * 10, "sid": sid, "ev": "auto", "name": "x"},
                     {"t": 3001 + i * 10, "sid": sid, "ev": "auto", "name": "tail"}]
        for i in range(4):
            sid = f"u{i}"
            rows += [{"t": 4000 + i * 10, "sid": sid, "ev": "auto", "name": "y"},
                     {"t": 4001 + i * 10, "sid": sid, "ev": "auto", "name": "tail"}]
        # a->tail twice more (support 2 — passes the floor, must die on lift)
        for i in range(2):
            sid = f"s{i}"
            rows += [{"t": 2000 + i, "sid": sid, "ev": "manual", "name": "tail"}]
        # noise that must never enter: subagent row, unknown name, non-invocation row, repeat
        rows += [{"t": 5000, "sid": "s2", "ev": "auto", "name": "c", "sub": True},
                 {"t": 5001, "sid": "s2", "ev": "auto", "name": "not-a-skill"},
                 {"t": 5002, "sid": "s2", "ev": "offer", "name": "a"},
                 {"t": 5003, "sid": "s2", "ev": "auto", "name": "a"},
                 {"t": 5004, "sid": "s2", "ev": "auto", "name": "a"}]  # consecutive repeat collapse
        ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

        import build_chains
        build_chains.SIDECAR = tmp / "sidecar.json"
        build_chains.LEDGER = ledger
        build_chains.OUT = tmp / "mined.json"

        # sequences: noise excluded, repeats collapsed
        cat = build_chains.catalogue_names()
        assert cat == {"a", "b", "c", "tail", "x", "y"}, cat
        seqs, events = build_chains.load_sequences(ledger, cat)
        assert events == 3 * 2 + 4 * 2 + 4 * 2 + 2 + 1, events  # 25 nodes; sub/unknown/offer/repeat excluded
        assert seqs["s0"] == ["a", "b", "tail"], seqs.get("s0")
        assert seqs["s2"] == ["a", "b", "a"], seqs.get("s2")    # trailing repeat collapsed to one a

        # ADR-0045 option (a): get_skill pulls join the mined sequences as full nodes;
        # sub-stamped pulls do not; CHAIN_MINE_PULLS=0 reverts to invocations-only.
        rows += [{"t": 6000, "sid": "p1", "ev": "get_skill", "name": "a"},
                 {"t": 6001, "sid": "p1", "ev": "get_skill", "name": "b", "sub": True},
                 {"t": 6002, "sid": "p1", "ev": "auto", "name": "c"}]
        ledger.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
        seqs, events = build_chains.load_sequences(ledger, cat)
        assert seqs["p1"] == ["a", "c"], seqs.get("p1")     # pull is a node; sub-pull dropped
        assert events == 25 + 2, events
        _saved_mp = (build_chains.MINE_PULLS, build_chains._MINABLE_EV)
        build_chains.MINE_PULLS, build_chains._MINABLE_EV = False, ("auto", "manual")
        try:
            seqs, events = build_chains.load_sequences(ledger, cat)
            assert seqs["p1"] == ["c"], seqs.get("p1")      # flag off: pulls invisible again
            assert events == 25 + 1, events                 # only p1's invocation row remains
        finally:
            build_chains.MINE_PULLS, build_chains._MINABLE_EV = _saved_mp

        chains = build_chains.mine(seqs)
        # a->b: support 3, P(b)=3/11 sessions, lift=(3/3)/(3/11)=3.67 -> kept
        assert chains.get("a") == ["b"], chains.get("a")
        # tail is closure: P(tail)=10/11 -> every ?->tail lift < 1.5 -> suppressed
        assert "tail" not in json.dumps(chains), chains
        assert "x" not in chains and "y" not in chains, chains
        # gap: two events 3h apart are still adjacent nodes (session-bounded), pin the contract
        rows2 = [{"t": 0, "sid": "g", "ev": "auto", "name": "a"},
                 {"t": 3 * 3600 + 1, "sid": "g", "ev": "auto", "name": "c"},
                 {"t": 3 * 3600 + 2, "sid": "g", "ev": "auto", "name": "a"},
                 {"t": 3 * 3600 + 3, "sid": "g", "ev": "auto", "name": "c"},
                 {"t": 3 * 3600 + 4, "sid": "g", "ev": "auto", "name": "a"},
                 {"t": 3 * 3600 + 5, "sid": "g", "ev": "auto", "name": "c"}]
        l2 = tmp / "l2.jsonl"
        l2.write_text("\n".join(json.dumps(r) for r in rows2), encoding="utf-8")
        seqs2, _ = build_chains.load_sequences(l2, cat)
        assert seqs2["g"] == ["a", "c"] * 3, seqs2["g"]

        # build() writes the document atomically
        doc = build_chains.build(ledger_path=ledger, dry_run=False)
        assert (tmp / "mined.json").exists()
        assert doc["chains"].get("a") == ["b"]
        assert doc["_meta"]["params"]["min_support"] == 2
        assert not (tmp / "mined.json.tmp").exists()
        # min_support=3 kills a->b (support 3 passes; use 4 to prove the floor bites)
        doc2 = build_chains.build(ledger_path=ledger, dry_run=True, min_support=4)
        assert "a" not in doc2["chains"] or "b" not in doc2["chains"].get("a", []), doc2["chains"]
    finally:
        build_chains.LEDGER, build_chains.SIDECAR, build_chains.OUT = \
            real_ledger, real_sidecar, real_out
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
    print("PASS")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Mine real skill chains from the invocation ledger")
    ap.add_argument("--since", default=None, help="epoch floor YYYY-MM-DD[:HH[:MM]] (local)")
    ap.add_argument("--min-support", type=int, default=MIN_SUPPORT)
    ap.add_argument("--min-lift", type=float, default=MIN_LIFT)
    ap.add_argument("--max-succ", type=int, default=MAX_SUCC)
    ap.add_argument("--dry-run", action="store_true", help="print the map, don't write")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        _selftest()
    else:
        d = build(since=_parse_when(args.since), dry_run=args.dry_run,
                  min_support=args.min_support, min_lift=args.min_lift, max_succ=args.max_succ)
        print(f"mined {len(d['chains'])} chained skills from "
              f"{d['_meta']['events']} events / {d['_meta']['sessions']} sessions")
        for k, v in list(d["chains"].items())[:20]:
            print(f"  {k} -> {', '.join(v)}")
        if args.dry_run:
            print(json.dumps(d["_meta"], indent=1))
