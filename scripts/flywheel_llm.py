#!/usr/bin/env python3
"""flywheel_llm.py — shared LLM client for the retrieval-flywheel generator
scripts (llm_eval_gen.py, llm_triggers.py). Stdlib only. Any OpenAI-compatible
endpoint; production today is the private cloud gateway api.thinhkhuat.com/v1
(model cmc/MiniMaxAI/MiniMax-M3, FLYWHEEL_LLM_SCHEMA_MODE=off), configured
in ~/.config/harness-env.sh — the canonical cross-harness env home (caveats §20).

Config resolution order (see _cfg below): real environment wins, then
harness-env.sh, then the hard-coded default. The file fallback exists because
processes launched outside a login shell — GUI-launched harness extensions,
detached auto_* hook spawns, agent bash tools — do NOT inherit the sourced env;
without it they silently target the dead local LM-Studio default (observed live
2026-08-26, an OMP bash tool launching flywheel.py --generate with no env).

Usage:
  python3 scripts/flywheel_llm.py --selftest   # network-free checks
"""
import hashlib
import http.client
import json
import os
import re
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

# Regen cache lives in the canonical durable home (ADR-0025), NOT ROOT/eval/ — ROOT is the
# versioned plugin cache dir (…/<version>/), wiped on every /plugin update. A cache under the
# ephemeral dir goes cold after each update, forcing a full-catalogue regeneration. Both
# generators (llm_triggers.py, llm_eval_gen.py) share this single path.
HOME = Path(os.environ.get("SKILL_CONCIERGE_HOME", Path.home() / ".claude" / "skill-concierge"))
CACHE_FILE = HOME / ".flywheel-cache.json"

_HARNESS_ENV_SH = Path.home() / ".config" / "harness-env.sh"


def _harness_env() -> dict:
    """Parse `export KEY="VALUE"` lines for FLYWHEEL_LLM_* keys from the canonical
    env home. Missing file or odd lines: no-op (fail-open to today's resolution)."""
    out = {}
    try:
        for line in _HARNESS_ENV_SH.read_text(encoding="utf-8").splitlines():
            m = re.match(
                r'^\s*(?:export\s+)?(FLYWHEEL_LLM_[A-Z_]+)=(["\']?)(.*)\2\s*$', line)
            if m:
                out[m.group(1)] = m.group(3)
    except OSError:
        pass
    return out


_HENV = _harness_env()


def _cfg(key: str, default: str) -> str:
    """env > harness-env.sh > default. Same seam rule as auto_*._mcp_env: a real
    exported var always wins over the file."""
    return os.environ.get(key) or _HENV.get(key) or default


ENDPOINT = _cfg("FLYWHEEL_LLM_ENDPOINT", "http://localhost:4310/v1/chat/completions")
MODEL = _cfg("FLYWHEEL_LLM_MODEL", "gemma-4-e4b-it-qat-optiq")
API_KEY = _cfg("FLYWHEEL_LLM_API_KEY", "")
SCHEMA_MODE = _cfg("FLYWHEEL_LLM_SCHEMA_MODE", "json_schema")
# Ping budget. 5 s was too tight for the production gateway (api.thinhkhuat.com
# legitimately serves /v1/models in 6-7 s+ under load; a real preflight miss was
# observed 2026-08-27 19:58 ICT, silently skipping a whole flywheel pass). All
# ping() consumers are fail-open, so the extra budget only delays the skip.
PING_TIMEOUT = float(_cfg("FLYWHEEL_LLM_PING_TIMEOUT", "10"))


def _is_timeout(exc: BaseException) -> bool:
    """True when `exc` is a connect/read timeout in any of the shapes urllib raises.

    - bare TimeoutError (socket.timeout aliases it on 3.10+) — read timeouts during
      r.read() surface unwrapped;
    - URLError whose .reason is a timeout — connect-phase timeouts get wrapped.
    Other OSErrors (refused, DNS, TLS) stay non-retryable: they fail fast instead
    of burning backoff on a gateway that is down, not slow.
    """
    if isinstance(exc, TimeoutError) or isinstance(exc, socket.timeout):
        return True
    if isinstance(exc, urllib.error.URLError):
        reason = exc.reason
        return isinstance(reason, TimeoutError) or isinstance(reason, socket.timeout)
    return False


class TruncatedCompletion(RuntimeError):
    """The endpoint returned a reply that did not finish cleanly (finish_reason != "stop").

    Most often `finish_reason == "length"`: the schema carried a constraint the model was
    unlikely to satisfy (e.g. a `pattern` requiring a character the prompt steers it away
    from), so the grammar masked the string-closing quote until that obligation was met and
    generation ran to `max_tokens`. Raised rather than swallowed because a truncated reply
    can still PARSE — see chat().
    """


def slug(name):
    """Skill name -> filesystem-safe slug: any run of non [A-Za-z0-9._-] chars
    collapses to a single '-', leading/trailing '-' stripped. Filenames only —
    the stored "skill" field / triggers.json key keeps the true original name."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-")


def parse_json_reply(s):
    """Strip a leading/trailing ```json fence (if any) and parse the JSON object."""
    s = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.MULTILINE).strip()
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
    gemma-4-e4b-it-qat-optiq (no thinking mode) is the production model; set it via
    FLYWHEEL_LLM_MODEL. It replaced gemma-4-12b-it-qat-optiq: on a 20-probe held-out
    retrieval eval it roughly doubled MRR (0.231 -> 0.462) and cut mean rank 56.6 -> 13.1.

    Raises TruncatedCompletion when the endpoint reports finish_reason != "stop", and
    HTTPError on a non-retryable transport failure. Retried with backoff (3 attempts):
    HTTP 502/503/504 (the transient gateway/upstream class — a live outage window on
    2026-08-27/28 left 93 per-skill 502 errors in one run; a sustained outage still
    exhausts the ladder in ~15s/skill and fails the skill, which the next run
    retries) AND timeouts (connect or read — the production gateway is bimodal under
    load, 2-10 s or 60-95 s on the same call, so a timeout is contention, not a
    verdict). Other transport errors (refused, DNS) fail fast on purpose."""
    payload = {
        "model": MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0.4,
        # 8192 (was 4096): deepseek-v4-flash spends budget on reasoning before content —
        # observed live 2026-08-26 as deterministic finish_reason='length' with 0-318 chars
        # of content returned on 7/89 skills; the raise is the documented fix (line ~149).
        "max_tokens": 8192,
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
    for attempt in range(3):        # transient 5xx/timeout -> backoff, don't hammer
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                choice = json.loads(r.read())["choices"][0]
            finish = choice.get("finish_reason")
            out = (choice.get("message") or {}).get("content", "")
            # Guard on the FIELD, never on whether the body parses. A `length` cut can
            # leave syntactically valid but semantically short JSON (4 triggers where 10
            # were asked), which json.loads accepts happily. Absent field -> tolerate:
            # some OpenAI-compatible gateways omit it, and absence is not evidence of a
            # truncation. Explicit non-"stop" -> fail loud, so the caller reports a real
            # cause instead of dropping the skill on an opaque JSONDecodeError.
            if finish is not None and finish != "stop":
                raise TruncatedCompletion(
                    f"completion did not finish cleanly (finish_reason={finish!r}, "
                    f"{len(out)} chars). Not retried: given the same prompt+schema this "
                    f"is deterministic. Raise max_tokens, or relax the schema constraint "
                    f"the model cannot satisfy.")
            # The gateway can wrap an upstream 503 INSIDE a 200 envelope:
            # content is literally `[CommandCode error: {...,"statusCode":503,
            # "isRetryable":true}]` with finish_reason "stop" (observed live
            # 2026-08-28 on cmc/minimax/minimax-m3-free). finish is "stop" and the
            # text is non-JSON, so neither the HTTPError ladder above nor the
            # caller's JSON handling ever retries it — the skill just fails.
            # Same transient class as HTTP 503: route it through the same ladder.
            err_m = re.search(r"\[CommandCode error: (\{.*\})\]\s*$", out, re.DOTALL)
            if err_m:
                try:
                    err = json.loads(err_m.group(1))
                except ValueError:
                    err = {}
                if err.get("isRetryable") and attempt < 2:
                    print(f"retry {attempt + 2}/3 after 200-wrapped HTTP "
                          f"{err.get('statusCode', '?')} (+{5 * (attempt + 1)}s)")
                    time.sleep(5 * (attempt + 1))
                    continue
                # URLError (an OSError) on purpose: every per-skill handler in the
                # generators catches OSError — the contract is "sustained outage
                # fails the SKILL, which the next run retries", never the pass.
                raise urllib.error.URLError(
                    f"gateway 200-wrapped HTTP {err.get('statusCode', '?')} "
                    f"after retries: {out[:160]}")
            time.sleep(rate_s)
            return parse_json_reply(out)
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < 2:
                print(f"retry {attempt + 2}/3 after HTTP {e.code} (+{5 * (attempt + 1)}s)")
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except OSError as e:  # URLError + TimeoutError are both OSError subclasses
            if _is_timeout(e) and attempt < 2:
                print(f"retry {attempt + 2}/3 after timeout ({e}; +{5 * (attempt + 1)}s)")
                time.sleep(5 * (attempt + 1))
                continue
            raise


def ping(timeout=None):
    """Cheap reachability preflight: GET <base>/models (base = ENDPOINT with the trailing
    /chat/completions path dropped). Returns (ok: bool, detail: str) — never raises. Consumed
    by `doctor.py` check_flywheel(), the auto-flywheel hook's `_ping_ok()`, and the flywheel
    skill; makes no network call unless invoked. Default budget is PING_TIMEOUT (10 s,
    FLYWHEEL_LLM_PING_TIMEOUT) — see its comment for why 5 s was too tight."""
    base = ENDPOINT.rsplit("/chat/completions", 1)[0]
    url = base.rstrip("/") + "/models"
    if timeout is None:
        timeout = PING_TIMEOUT
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
    # Enumerated on purpose (contract: never raises): URLError/HTTPError are OSError
    # subclasses (DNS/refused/timeout/TLS/HTTP status), HTTPException leaks from
    # http.client on malformed replies, JSONDecodeError (ValueError) = non-JSON 200.
    except (OSError, http.client.HTTPException, ValueError) as e:
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

    # timeout classification — what chat() may retry vs what must fail fast
    assert _is_timeout(TimeoutError("read timed out")), "bare TimeoutError must classify as timeout"
    assert _is_timeout(urllib.error.URLError(TimeoutError("timed out"))), "wrapped connect timeout must classify"
    assert not _is_timeout(urllib.error.URLError(ConnectionRefusedError())), "refused is NOT a timeout"
    assert not _is_timeout(urllib.error.URLError(OSError("dns failure"))), "DNS is NOT a timeout"
    assert not _is_timeout(ValueError("unrelated")), "non-OSError is never a timeout"
    # PING_TIMEOUT: env-tunable float, default widened past the gateway's real 6-7s budget
    assert PING_TIMEOUT >= 10, f"PING_TIMEOUT default must be >= 10s, got {PING_TIMEOUT}"

    try:
        names = live_skill_names()
        assert isinstance(names, list) and len(names) >= 1, "live_skill_names() returned <1 entry"
        print(f"live_skill_names(): {len(names)} skills (live index reachable)")
    # Same enumerated set as ping() plus KeyError: scroll_all_points() indexes
    # ["result"], which a malformed Qdrant reply can omit.
    except (OSError, http.client.HTTPException, ValueError, KeyError) as e:
        print(f"SKIP live_skill_names(): live index unreachable ({e})")

    print("PASS")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        print(__doc__)
