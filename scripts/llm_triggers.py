#!/usr/bin/env python3
"""
llm_triggers.py — generate short LLM utterance-style trigger phrases via the LAN
Qwen client and merge them additively into eval/triggers.json alongside the
existing prose-phrase layer build_triggers.py writes.

See plans/2026-07-08-local-llm-retrieval-flywheel.md, Task 3.

Merge shape: enrich_index.py only ever reads triggers[name]["triggers"] as one
flat list (scripts/enrich_index.py:143 `ts = triggers[n]["triggers"]`) — it has
no notion of layers. So to be additive AND actually consumed without touching
enrich_index.py, the prose-phrase list is kept verbatim under `prose_triggers`,
the new utterance list is kept verbatim (capped) under `llm_triggers`, and the
top-level `triggers`/`n`/`source` become the union of both so the existing
consumer picks up both layers unchanged.

Usage:
  python3 scripts/llm_triggers.py --selftest
  python3 scripts/llm_triggers.py --limit 10
  python3 scripts/llm_triggers.py --rate 6
  python3 scripts/llm_triggers.py --only ck:ai-artist
"""
import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm  # noqa: E402
from build_triggers import MAX_TRIGGERS  # noqa: E402 — same per-skill cap build_triggers.py uses

TRIGGERS_FILE = Path(os.environ.get("SKILL_TRIGGERS", ROOT / "eval" / "triggers.json"))
CACHE_FILE = ROOT / "eval" / ".flywheel-cache.json"
CACHE_PREFIX = "triggers:"  # namespaced — cache file is shared with llm_eval_gen.py

SYSTEM_PROMPT = (
    "You generate short retrieval trigger phrases for a developer-tool skill. Output "
    'STRICT JSON: {"triggers": [...]}. 6-8 short intent phrases (3-8 words) a user might '
    "type to invoke this skill, natural phrasing. IMPORTANT: at least 2 of the phrases "
    "MUST be in natural Vietnamese (tiếng Việt), the rest in English. No skill names in "
    "the phrases. No markdown. Return valid JSON with double-quoted keys."
)

VN_RETRY = (
    " Your previous reply had too few Vietnamese phrases. Return the full set again with "
    "AT LEAST 2 of the trigger phrases in natural Vietnamese (tiếng Việt)."
)


def vn_count(strings):
    """Count strings with any non-ASCII char (proxy for Vietnamese; English is pure ASCII)."""
    return sum(1 for s in strings if any(ord(c) > 127 for c in s))


MIN_TRIGGERS = 4

SCHEMA = {
    "type": "object",
    "properties": {
        "triggers": {"type": "array", "items": {"type": "string"}, "minItems": MIN_TRIGGERS},
    },
    "required": ["triggers"],
}


def user_prompt(name, description):
    return f"Skill: {name}\nDescription: {description}"


def validate_reply(reply):
    """Return an error string if `reply` doesn't meet the expected shape, else None."""
    if not isinstance(reply, dict) or "triggers" not in reply:
        return f"missing 'triggers' key: {reply!r}"
    trig = reply["triggers"]
    if not isinstance(trig, list) or not all(isinstance(x, str) for x in trig):
        return "triggers must be a list of strings"
    if len(trig) < MIN_TRIGGERS:
        return f"only {len(trig)} triggers (need >={MIN_TRIGGERS})"
    return None


def merge_utterance_layer(triggers, name, utterances, cap=MAX_TRIGGERS):
    """Additively merge an llm-utterance trigger layer into triggers[name].
    Mutates and returns `triggers`. See module docstring for the shape rationale."""
    utterances = utterances[:cap]
    existing = triggers.get(name)
    # re-derive from the TRUE original prose layer, never the already-combined
    # list -- else a re-run (cache-miss on a description change) treats last
    # run's utterances as prose and stacks a new layer on top every regen.
    prose = existing.get("prose_triggers", existing["triggers"]) if existing else []
    combined, seen = [], set()
    for p in prose + utterances:
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        combined.append(p)
    combined = combined[:cap]
    triggers[name] = {
        "source": "prose-phrase+llm-utterance" if prose else "llm-utterance",
        "triggers": combined,
        "n": len(combined),
        "prose_triggers": prose,
        "llm_triggers": {"source": "llm-utterance", "triggers": utterances, "n": len(utterances)},
    }
    return triggers


def load_triggers():
    if TRIGGERS_FILE.exists():
        return json.loads(TRIGGERS_FILE.read_text(encoding="utf-8"))
    return {}


def save_triggers(triggers):
    TRIGGERS_FILE.write_text(json.dumps(triggers, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def run(limit=None, only=None, rate=6.0):
    skills = flywheel_llm.live_skills()
    names = sorted(skills) if only is None else [only]
    if limit:
        names = names[:limit]

    triggers = load_triggers()
    cache = load_cache()
    for name in names:
        desc = skills.get(name, "")
        h = flywheel_llm.body_hash(desc)
        key = CACHE_PREFIX + name
        if cache.get(key) == h and "llm_triggers" in triggers.get(name, {}):
            continue  # unchanged + already merged
        try:
            reply = flywheel_llm.chat(SYSTEM_PROMPT, user_prompt(name, desc), rate_s=rate, schema=SCHEMA)
            # VN parity with llm_eval_gen: re-ask once if the model skipped Vietnamese,
            # keep-and-warn if still short (don't lose the skill).
            if isinstance(reply, dict) and vn_count(reply.get("triggers", [])) < 2:
                reply = flywheel_llm.chat(SYSTEM_PROMPT + VN_RETRY, user_prompt(name, desc),
                                          rate_s=rate, schema=SCHEMA)
                if vn_count(reply.get("triggers", [])) < 2:
                    print(f"WARN: {name}: still <2 Vietnamese triggers after retry (kept)")
        except Exception as e:
            print(f"WARN: skipping {name}: chat failed ({e})")
            continue
        err = validate_reply(reply)
        if err:
            print(f"WARN: skipping {name}: {err}")
            continue
        merge_utterance_layer(triggers, name, reply["triggers"])
        cache[key] = h
        save_triggers(triggers)
        save_cache(cache)


def _selftest():
    assert SCHEMA["required"] == ["triggers"], "SCHEMA required keys wrong"
    assert set(SCHEMA["properties"]) == {"triggers"}, "SCHEMA properties wrong"

    before = TRIGGERS_FILE.read_bytes() if TRIGGERS_FILE.exists() else None

    triggers = {
        "come-clean": {
            "source": "prose-phrase",
            "triggers": ["force an agent to own a rule-dodge", "the user catches an agent weaseling"],
            "n": 2,
        }
    }
    utterances = [
        "why did you skip that step", "call yourself out on this",
        "did you dodge the rule", "own up to the mistake",
        "tự nhận lỗi đi", "sao lại né bước này",
    ]
    merge_utterance_layer(triggers, "come-clean", utterances, cap=MAX_TRIGGERS)

    entry = triggers["come-clean"]
    assert entry["prose_triggers"] == ["force an agent to own a rule-dodge", "the user catches an agent weaseling"], \
        f"prose-phrase entry not preserved: {entry['prose_triggers']}"
    assert entry["llm_triggers"]["source"] == "llm-utterance", "utterance layer not tagged"
    assert entry["llm_triggers"]["triggers"] == utterances, "utterance layer not stored verbatim"
    assert len(entry["llm_triggers"]["triggers"]) <= MAX_TRIGGERS, "utterance layer exceeds cap"
    for p in entry["prose_triggers"]:
        assert p in entry["triggers"], f"prose phrase missing from merged flat list: {p}"
    for u in utterances:
        assert u in entry["triggers"], f"utterance missing from merged flat list: {u}"

    # cap enforcement on an oversized utterance list
    triggers2 = {}
    merge_utterance_layer(triggers2, "no-prose-skill", [f"phrase {i}" for i in range(MAX_TRIGGERS + 5)])
    assert len(triggers2["no-prose-skill"]["llm_triggers"]["triggers"]) == MAX_TRIGGERS, "cap not enforced"
    assert triggers2["no-prose-skill"]["prose_triggers"] == [], "no-prose case should have empty prose_triggers"

    # regression: re-run on a description change (cache-miss) must not treat
    # last run's utterances as prose, must not stack, must stay capped
    pristine_prose = ["force an agent to own a rule-dodge", "the user catches an agent weaseling"]
    run2_utterances = [
        "flag the skipped step", "admit the shortcut", "point out the dodge",
        "gọi tên lỗi ra", "thừa nhận đã né luật", "sửa ngay trong lượt này",
    ]
    merge_utterance_layer(triggers, "come-clean", run2_utterances, cap=MAX_TRIGGERS)
    entry2 = triggers["come-clean"]
    assert entry2["prose_triggers"] == pristine_prose, \
        f"prose_triggers polluted by a prior run's utterances: {entry2['prose_triggers']}"
    assert len(entry2["triggers"]) <= MAX_TRIGGERS, f"combined list exceeds cap after re-run: {len(entry2['triggers'])}"
    for u in utterances:  # run 1's utterances
        assert u not in entry2["triggers"], f"run-1 utterance stacked into run-2 triggers: {u}"

    after = TRIGGERS_FILE.read_bytes() if TRIGGERS_FILE.exists() else None
    assert before == after, "selftest mutated the real eval/triggers.json on disk!"

    print("PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", default=None)
    p.add_argument("--rate", type=float, default=6.0)
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        _selftest()
    else:
        run(limit=args.limit, only=args.only, rate=args.rate)
