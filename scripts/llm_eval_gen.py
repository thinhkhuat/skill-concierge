#!/usr/bin/env python3
"""
llm_eval_gen.py — generate dense per-skill eval scenarios (positive/negative
utterances) via the LAN Qwen client, one JSON file per skill matching the
gold schema in eval/scenarios/*.json.

See plans/2026-07-08-local-llm-retrieval-flywheel.md, Task 1.

Usage:
  python3 scripts/llm_eval_gen.py --selftest
  python3 scripts/llm_eval_gen.py --limit 10 --out eval/scenarios-shadow
  python3 scripts/llm_eval_gen.py --out eval/scenarios-shadow --rate 6
  python3 scripts/llm_eval_gen.py --only ck:ai-artist
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm  # noqa: E402

DEFAULT_OUT = ROOT / "eval" / "scenarios-shadow"
CACHE_FILE = flywheel_llm.CACHE_FILE  # canonical durable home (ADR-0025), shared with llm_triggers.py

SYSTEM_PROMPT = (
    "You generate a retrieval eval set for a developer-tool skill. Output STRICT "
    'JSON: {"positive": [...], "negative": [...]}. positive = 10-12 realistic first-person '
    "user utterances that SHOULD trigger this skill, natural phrasing. "
    "IMPORTANT: at least 3 of the positive utterances MUST be written in natural "
    "Vietnamese (tiếng Việt), the rest in English — never skip the Vietnamese ones. "
    "negative = 4-6 utterances that are "
    "plausibly confusable but belong to a DIFFERENT skill (near-miss, same domain). "
    "No skill names in the utterances. No markdown. Return valid JSON with double-quoted keys."
)

MIN_POSITIVE = 8
MIN_NEGATIVE = 3

SCHEMA = {
    "type": "object",
    "properties": {
        "positive": {"type": "array", "items": {"type": "string"}, "minItems": MIN_POSITIVE},
        "negative": {"type": "array", "items": {"type": "string"}, "minItems": MIN_NEGATIVE},
    },
    "required": ["positive", "negative"],
}


def user_prompt(name, description):
    return f"Skill: {name}\nDescription: {description}"


def vn_count(strings):
    """Count strings containing any non-ASCII char (a reliable proxy for Vietnamese —
    English utterances are pure ASCII, Vietnamese carries diacritics)."""
    return sum(1 for s in strings if any(ord(c) > 127 for c in s))


VN_RETRY = (
    " Your previous reply had too few Vietnamese utterances. Return the full set again "
    "with AT LEAST 3 of the positive utterances written in natural Vietnamese (tiếng Việt)."
)


def validate_reply(reply):
    """Return an error string if `reply` doesn't meet the gold schema shape, else None."""
    if not isinstance(reply, dict):
        return "reply is not a dict"
    if set(reply) - {"positive", "negative"} or "positive" not in reply or "negative" not in reply:
        return f"missing/extra keys: {sorted(reply)}"
    pos, neg = reply["positive"], reply["negative"]
    if not isinstance(pos, list) or not isinstance(neg, list):
        return "positive/negative must be lists"
    if not all(isinstance(x, str) for x in pos + neg):
        return "positive/negative must contain only strings"
    if len(pos) < MIN_POSITIVE:
        return f"only {len(pos)} positives (need >={MIN_POSITIVE})"
    if len(neg) < MIN_NEGATIVE:
        return f"only {len(neg)} negatives (need >={MIN_NEGATIVE})"
    return None


def write_scenario(name, reply, out_dir):
    """Validate `reply` against the gold schema and write it to out_dir/<slug>.json.
    Returns True if written, False if rejected (malformed reply)."""
    err = validate_reply(reply)
    if err:
        print(f"WARN: skipping {name}: {err}")
        return False
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = {"skill": name, "positive": reply["positive"], "negative": reply["negative"]}
    (out_dir / f"{flywheel_llm.slug(name)}.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def run(out_dir, limit=None, only=None, rate=6.0):
    """Returns a list of {"name", "status": "generated"|"error", "detail"} records —
    one per skill actually attempted this call (cache-hit/unchanged skills are skipped
    silently and produce no record, consumed by flywheel.py's manifest writer)."""
    skills = flywheel_llm.live_skills()
    names = sorted(skills) if only is None else [only]
    if limit:
        names = names[:limit]

    cache = load_cache()
    out_dir = Path(out_dir)
    results = []
    for name in names:
        desc = skills.get(name, "")
        h = flywheel_llm.body_hash(desc)
        out_file = out_dir / f"{flywheel_llm.slug(name)}.json"
        if cache.get(name) == h and out_file.exists():
            continue  # unchanged + already generated
        try:
            reply = flywheel_llm.chat(SYSTEM_PROMPT, user_prompt(name, desc), rate_s=rate, schema=SCHEMA)
            # VN coverage is core (VN-heavy retrieval): if the model skipped Vietnamese,
            # re-ask once forcefully. Keep-and-warn if still short — don't lose the skill.
            if isinstance(reply, dict) and vn_count(reply.get("positive", [])) < 2:
                reply = flywheel_llm.chat(SYSTEM_PROMPT + VN_RETRY, user_prompt(name, desc),
                                          rate_s=rate, schema=SCHEMA)
                if vn_count(reply.get("positive", [])) < 2:
                    print(f"WARN: {name}: still <2 Vietnamese positives after retry (kept)")
        except Exception as e:
            print(f"WARN: skipping {name}: chat failed ({e})")
            results.append({"name": name, "status": "error", "detail": f"chat failed: {e}"})
            continue
        if write_scenario(name, reply, out_dir):
            cache[name] = h
            save_cache(cache)
            results.append({"name": name, "status": "generated", "detail": None})
        else:
            results.append({"name": name, "status": "error", "detail": "malformed reply"})
    return results


def _selftest():
    import shutil
    import tempfile

    assert SCHEMA["required"] == ["positive", "negative"], "SCHEMA required keys wrong"
    assert set(SCHEMA["properties"]) == {"positive", "negative"}, "SCHEMA properties wrong"

    tmp = Path(tempfile.mkdtemp())
    try:
        good = {
            "positive": [
                "generate a product mockup", "create marketing visuals", "concept art for a scene",
                "make a brand image", "generate a hero banner", "produce social graphics",
                "create a vintage poster", "make an illustration for the blog",
                "tạo ảnh mockup sản phẩm", "tạo bộ ảnh quảng cáo",
            ],
            "negative": ["resize these photos in batch", "publish the site to production", "plan the campaign"],
        }
        assert write_scenario("test:skill", good, tmp) is True
        f = tmp / "test-skill.json"
        assert f.exists()
        doc = json.loads(f.read_text())
        assert set(doc) == {"skill", "positive", "negative"}, doc
        assert doc["skill"] == "test:skill"
        assert len(doc["positive"]) >= MIN_POSITIVE
        assert len(doc["negative"]) >= MIN_NEGATIVE
        assert all(isinstance(x, str) for x in doc["positive"] + doc["negative"])

        bad = {"positive": ["only one", "two"], "negative": ["one"]}
        assert write_scenario("test:bad", bad, tmp) is False
        assert not (tmp / "test-bad.json").exists()
    finally:
        shutil.rmtree(tmp)
    print("PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=str(DEFAULT_OUT))
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", default=None)
    p.add_argument("--rate", type=float, default=6.0)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        _selftest()
    else:
        run(args.out, limit=args.limit, only=args.only, rate=args.rate)
