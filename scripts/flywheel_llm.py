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
API_KEY = os.environ.get("FLYWHEEL_LLM_API_KEY", "")
# json_schema = strict grammar-constrained JSON (LM-Studio); json_object = loose JSON mode
# (Ollama /v1 + some gateways); off = no response_format, rely on the prompt (generators
# already validate + retry, so a looser mode degrades safely rather than crashing).
SCHEMA_MODE = os.environ.get("FLYWHEEL_LLM_SCHEMA_MODE", "json_schema")


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
    if schema is not None and SCHEMA_MODE == "json_schema":
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "reply", "strict": True, "schema": schema},
        }
    elif schema is not None and SCHEMA_MODE == "json_object":
        payload["response_format"] = {"type": "json_object"}
    # SCHEMA_MODE == "off" (or no schema given): omit response_format, rely on the prompt.
    body = json.dumps(payload).encode()
    headers = {"Content-Type": "application/json"}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(ENDPOINT, data=body, headers=headers)
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


def ping(timeout=5):
    """Cheap reachability preflight: GET <base>/models (base = ENDPOINT with the trailing
    /chat/completions path dropped). Returns (ok: bool, detail: str) — never raises. Consumed
    by `doctor.py` check_flywheel() and the flywheel skill; makes no network call unless invoked."""
    base = ENDPOINT.rsplit("/chat/completions", 1)[0]
    url = base.rstrip("/") + "/models"
    headers = {}
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
        ids = [m.get("id", "?") for m in data.get("data", [])] if isinstance(data, dict) else []
        detail = f"{url} reachable" + (f" — models: {', '.join(ids[:5])}" if ids else "")
        return True, detail
    except Exception as e:
        return False, f"{url} unreachable: {e}"


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

    # Auth header: built when FLYWHEEL_LLM_API_KEY is set, absent otherwise. Network-free —
    # inspect the Request object build_chat_request() would produce without sending it.
    def _headers(key):
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = f"Bearer {key}"
        return h
    assert "Authorization" not in _headers(""), "no key -> no Authorization header"
    assert _headers("sk-test")["Authorization"] == "Bearer sk-test", "key -> Bearer header"

    # Schema-mode -> response_format shape (mirrors the branch in chat()).
    def _response_format(mode, schema):
        if schema is not None and mode == "json_schema":
            return {"type": "json_schema", "json_schema": {"name": "reply", "strict": True, "schema": schema}}
        if schema is not None and mode == "json_object":
            return {"type": "json_object"}
        return None
    dummy_schema = {"type": "object"}
    assert _response_format("json_schema", dummy_schema)["type"] == "json_schema", "json_schema mode"
    assert _response_format("json_object", dummy_schema) == {"type": "json_object"}, "json_object mode"
    assert _response_format("off", dummy_schema) is None, "off mode omits response_format"
    assert _response_format("json_schema", None) is None, "no schema -> no response_format regardless of mode"

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
