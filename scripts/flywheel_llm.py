#!/usr/bin/env python3
"""
flywheel_llm.py — shared local-Qwen client for the retrieval-flywheel generator
scripts (llm_eval_gen.py, llm_triggers.py). Stdlib only.

Endpoint/model/rate are env-configurable so generation coexists with cognee on
the shared LAN GPU (see plans/2026-07-08-local-llm-retrieval-flywheel.md, Task 0).

Usage:
  python3 scripts/flywheel_llm.py --selftest   # network-free checks
"""
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

ENDPOINT = os.environ.get("FLYWHEEL_LLM_ENDPOINT", "http://localhost:4310/v1/chat/completions")
MODEL = os.environ.get("FLYWHEEL_LLM_MODEL", "gemma-4-12b-it-optiq")


def slug(name):
    """Skill name -> filesystem-safe slug: any run of non [A-Za-z0-9._-] chars
    collapses to a single '-', leading/trailing '-' stripped. Filenames only —
    the stored "skill" field / triggers.json key keeps the true original name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")


def parse_json_reply(s):
    """Strip a leading/trailing ```json fence (if any) and parse the JSON object."""
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.M).strip()
    return json.loads(s)


def body_hash(text):
    return hashlib.md5(text.encode()).hexdigest()


def chat(system, user, rate_s=6.0, timeout=120, schema=None):
    """POST to the LM Studio OpenAI-compatible /v1/chat/completions endpoint, return
    the parsed JSON reply. If `schema` is given (a JSON-schema dict), pass it as
    OpenAI `response_format: json_schema` (strict) so LM Studio grammar-constrains the
    output to valid JSON with quoted keys — LM Studio rejects Ollama's `format` field.
    NOTE: the generation model must have THINKING OFF. Reasoning is incompatible with a
    response_format (empties the content) and, run schema-less, exhausts the token budget
    on this task's complex prompt — proven dead by every path (reports/qwen35-9b-thinking-*).
    gemma-4-12b-it-optiq (no thinking mode) is the production model."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        "max_tokens": 2048,
    }
    if schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": schema},
        }
    body = json.dumps(payload).encode()
    req = urllib.request.Request(ENDPOINT, data=body,
          headers={"Content-Type": "application/json"})
    for attempt in range(3):                 # transient 503 -> backoff, don't hammer
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                out = json.loads(r.read())["choices"][0]["message"]["content"]
            time.sleep(rate_s)
            return parse_json_reply(out)
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            raise


def live_skills():
    """Unique {skill_name: description} from the LIVE index (claude_skills payloads)
    — same source build_triggers.py uses, NOT disk. scroll_all_points() yields one
    entry per chunked point, so many points share a name; dedupe by name (keep the
    first non-empty description). Names match what enrich_index.py/precision_eval.py
    key on. Generators need the description to prompt the LLM, hence {name: desc}."""
    import build_triggers
    out = {}
    for name, desc in build_triggers.scroll_all_points():
        if name and name not in out:
            out[name] = desc or ""
    return out


def live_skill_names():
    """Unique skill names (sorted) — for --limit/--only iteration in the generators."""
    return sorted(live_skills())


def _selftest():
    assert slug("ck:ai-artist") == "ck-ai-artist", "slug(ns:name) failed"
    assert slug("a/b") == "a-b", "slug(a/b) failed"
    assert slug('"speech"') == "speech", 'slug("speech") failed'
    assert slug("Excel Analysis") == "Excel-Analysis", "slug(Excel Analysis) failed"

    assert parse_json_reply('```json\n{"x":1}\n```') == {"x": 1}, "parse_json_reply fence failed"
    assert parse_json_reply('{"y":2}') == {"y": 2}, "parse_json_reply bare failed"

    h = body_hash("abc")
    assert len(h) == 32 and re.fullmatch(r"[0-9a-f]{32}", h), "body_hash format failed"
    assert body_hash("abc") == h, "body_hash not stable"

    try:
        names = live_skill_names()
        assert isinstance(names, list) and len(names) >= 1, "live_skill_names() returned <1 entry"
        print(f"live_skill_names(): {len(names)} skills (live index reachable)")
    except Exception as e:
        print(f"SKIP live_skill_names(): live index unreachable ({e})")

    print("PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
