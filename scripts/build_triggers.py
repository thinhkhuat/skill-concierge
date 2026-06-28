#!/usr/bin/env python3
"""
build_triggers.py — derive per-skill trigger phrases for vector enrichment (Phase 1 step 2).

Source strategy (v1, uniform): PROSE-PHRASE. Each skill's indexed `description`
(which already includes `when_to_use`, appended by skills_discovery.parse_skill) is
split into intent-bearing phrases. Step-0 proved that splitting the description into
phrases, embedding each, and centroiding them (done in enrich_index.py) flips inverted
skills positive — it is the phrase-split-centroid MECHANISM, not new text, that extracts
intent. Uniform prose-phrase for ALL 495 is deliberate: it removes the source-strength
confound from precision_eval (a mixed utterance/prose shadow makes the 14 fire harder on
cross-domain negatives purely because their source is stronger, misread as cannibalization).
Utterances (the ceiling) are layered separately later to isolate the delta.

The authoritative skill set is the LIVE INDEX (claude_skills payloads), not disk — so the
names here match exactly what enrich_index.py / precision_eval.py key on.

Output: eval/triggers.json  { name: {source, triggers:[...], n} }

Pure stdlib. Usage:
  python3 scripts/build_triggers.py            # build eval/triggers.json from live index
  python3 scripts/build_triggers.py --dry-run  # report counts, write nothing
  python3 scripts/build_triggers.py --selftest # phrase-split self-check (no network)
"""
import os
import re
import sys
import json
import argparse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
QDRANT = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_COLLECTION", "claude_skills")

MAX_TRIGGERS = int(os.environ.get("TRIGGERS_MAX", "12"))   # m2: cap N so desc weight stays consistent
MIN_WORDS = 3                                              # drop fragments too generic to discriminate
MIN_CHARS = 12

# Split on sentence/clause boundaries, em/en dashes, semicolons, newlines, and list bullets.
_SPLIT_RE = re.compile(r"(?:[.;!?]\s+|\s+[—–]\s+|\n+|^\s*[-*•]\s+)", re.MULTILINE)
# Strip leading meta-labels the engine prose uses ("Triggers:", "Use when", "Examples:").
_LABEL_RE = re.compile(r"^\s*(triggers?|examples?|use when|also use|use this skill)\b[:\-]?\s*", re.I)
_WS_RE = re.compile(r"\s+")


def _post(url, payload, timeout=30.0):
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def split_phrases(description: str) -> list[str]:
    """Description -> deduped, intent-bearing phrases (order-preserving)."""
    if not description:
        return []
    parts = _SPLIT_RE.split(description)
    out, seen = [], set()
    for p in parts:
        p = _LABEL_RE.sub("", p or "")
        p = _WS_RE.sub(" ", p).strip().strip("\"'`()[]")
        if len(p) < MIN_CHARS or len(p.split()) < MIN_WORDS:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:MAX_TRIGGERS]


def scroll_all_points():
    """Yield (name, description) for every live-index point (paged scroll)."""
    nxt = None
    while True:
        body = {"limit": 256, "with_payload": True, "with_vector": False}
        if nxt is not None:
            body["offset"] = nxt
        res = _post(f"{QDRANT}/collections/{COLLECTION}/points/scroll", body)["result"]
        for pt in res.get("points", []):
            pl = pt.get("payload", {})
            yield pl.get("name", ""), pl.get("description", "")
        nxt = res.get("next_page_offset")
        if nxt is None:
            break


def run(dry_run):
    out, empty = {}, []
    total = 0
    for name, desc in scroll_all_points():
        total += 1
        if not name:
            continue
        triggers = split_phrases(desc)
        if not triggers:
            empty.append(name)
            continue
        out[name] = {"source": "prose-phrase", "triggers": triggers, "n": len(triggers)}
    ns = [v["n"] for v in out.values()]
    print(f"[build_triggers] {total} live points  ->  {len(out)} skills with triggers, "
          f"{len(empty)} empty")
    if ns:
        ns.sort()
        print(f"  triggers/skill: min {ns[0]}  median {ns[len(ns)//2]}  max {ns[-1]}  "
              f"mean {sum(ns)/len(ns):.1f}")
    if empty:
        print(f"  empty (no usable phrase, will fall back to bare description in enrich): "
              f"{', '.join(empty[:8])}{' …' if len(empty) > 8 else ''}")
    if dry_run:
        print("[dry-run] no file written.")
        return 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {OUT}  ({len(out)} skills)")
    return 0


def _selftest():
    bad = []
    desc = ("Force an agent to own a rule-dodge. Use when the user catches an agent "
            "weaseling around their rules; also auto-invoke the moment you catch yourself. "
            "Triggers: come clean, self-report — short")
    ph = split_phrases(desc)
    if not (2 <= len(ph) <= MAX_TRIGGERS):
        bad.append(f"phrase count off: {ph}")
    if any(len(p.split()) < MIN_WORDS for p in ph):
        bad.append(f"kept a too-short fragment: {ph}")
    if any(p.lower().startswith("triggers") for p in ph):
        bad.append(f"label not stripped: {ph}")
    if len(set(p.lower() for p in ph)) != len(ph):
        bad.append(f"dupes present: {ph}")
    # empty / tiny input -> no phrases, no crash
    if split_phrases("") != [] or split_phrases("hi") != []:
        bad.append("empty/tiny not handled")
    if bad:
        print("build_triggers --selftest FAIL:")
        for b in bad:
            print("  " + b)
        return 1
    print(f"build_triggers --selftest OK: phrase split ({len(ph)} phrases, labels stripped, deduped)")
    return 0


def main():
    ap = argparse.ArgumentParser(description="derive per-skill trigger phrases (Phase 1 step 2)")
    ap.add_argument("--dry-run", action="store_true", help="report counts, write nothing")
    ap.add_argument("--selftest", action="store_true", help="phrase-split self-check, no network")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    return run(args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
