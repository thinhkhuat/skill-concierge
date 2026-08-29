#!/usr/bin/env python3
"""
llm_capsules.py — generate per-skill capsule dossiers via the shared flywheel_llm
client into the canonical corpus (~/.claude/skill-concierge/capsules.json).

ADR-0049 consult layer. A capsule is a ~150-300 token structured summary of a
skill's FULL BODY (purpose / capabilities / inputs / outputs / avoid_when) written
with vocabulary deliberately different from the description — the same recall lever
the ADR-0026 v2 trigger prompt proved (vocabulary distance, not sentence-likeness).
The consult sieve serves capsules so the analyst can scan breadth cheaply and deep
read only the finalists.

Incremental like llm_triggers.py: the cache key hashes body+description, so only
new/changed skills hit the LLM. Staleness is therefore fingerprint-driven
(content-not-mtime, the ADR-0024 doctrine).

Usage:
  python3 scripts/llm_capsules.py --selftest
  python3 scripts/llm_capsules.py --limit 10
  python3 scripts/llm_capsules.py --only ck:ai-artist
  python3 scripts/llm_capsules.py --workers 4
"""
import argparse
import json
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import flywheel_llm
import build_triggers

# Canonical capsule corpus lives in the OPERATOR home (same doctrine as triggers.json,
# ADR-0025/0044: the versioned plugin cache dir is wiped on every /plugin update).
_CAPSULES_DURABLE = Path.home() / ".claude" / "skill-concierge" / "capsules.json"
CAPSULES_FILE = Path(__import__("os").environ.get(
    "SKILL_CAPSULES", str(_CAPSULES_DURABLE)))
CACHE_FILE = flywheel_llm.CACHE_FILE  # shared durable cache (ADR-0025)

# Bump when SYSTEM_PROMPT changes — the cache key hashes only the skill CONTENT,
# so without a version in the prefix a prompt rewrite regenerates nothing.
PROMPT_VERSION = 1
CACHE_PREFIX = f"capsules:v{PROMPT_VERSION}:"

# Body input cap for the LLM prompt. Hashing uses the FULL body (any change
# invalidates); only the prompt input is truncated so a 40KB SKILL.md cannot
# blow the generation context.
BODY_PROMPT_CAP = 6000

SYSTEM_PROMPT = (
    "You write capsule dossiers for developer-tool skills. A consultant agent reads "
    "them to decide which skills fit a task, so precision beats polish. Output STRICT "
    'JSON: {"purpose": str, "capabilities": [str], "inputs": str, "outputs": str, '
    '"avoid_when": str}.\n\n'
    "RULES:\n"
    "1. purpose: 1-2 sentences naming the PROBLEM the skill solves and the OUTCOME it "
    "produces. Use everyday synonyms, NOT the description's own vocabulary — the "
    "description already exists; your value is different words for the same thing.\n"
    "2. capabilities: 3-6 short phrases, each a DISTINCT thing the skill actually does "
    "(steps, scripts, references — grounded in the body text you are given).\n"
    "3. inputs: what it needs to run (arguments, files, env, context).\n"
    "4. outputs: what it produces (artifact, verdict, report, side effect).\n"
    "5. avoid_when: one sentence on when NOT to use it or what it does not cover.\n"
    "6. Ground every claim in the body text provided. No marketing, no guessing. "
    "No markdown. Valid JSON, double-quoted keys."
)

SCHEMA = {
    "type": "object",
    "properties": {
        "purpose": {"type": "string"},
        "capabilities": {"type": "array", "items": {"type": "string"},
                         "minItems": 3, "maxItems": 6},
        "inputs": {"type": "string"},
        "outputs": {"type": "string"},
        "avoid_when": {"type": "string"},
    },
    "required": ["purpose", "capabilities", "inputs", "outputs", "avoid_when"],
}

MIN_PURPOSE_CHARS = 20
MAX_CAPABILITIES = 6


def live_skills_with_paths(catalog=None):
    """{name: (description, body_path)} from the LIVE index, deduped by name (keep
    the first non-empty path). `catalog="<alias>"` scopes to one external catalog's
    `<alias>:*` skills, same as the trigger generator."""
    out = {}
    for name, desc, path in build_triggers.scroll_all_points(catalog=catalog, paths=True):
        if not name or name in out:
            continue
        out[name] = (desc or "", path or "")
    return out


def content_hash(description, body):
    """Fingerprint over body + description (either may be empty). Full body —
    truncation is a prompt concern, never a staleness concern."""
    return flywheel_llm.body_hash(f"{body}\x00{description}")


def read_body(path):
    """Best-effort body read; '' when unreadable (the hash then covers the
    description only, still catching description edits)."""
    if not path:
        return ""
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def user_prompt(name, description, body):
    shown = body[:BODY_PROMPT_CAP] + ("\n…[truncated]" if len(body) > BODY_PROMPT_CAP else "")
    return f"Skill: {name}\nDescription: {description}\n\nSKILL.md body:\n{shown}"


def clean_capabilities(strings):
    """Normalize and drop degenerate capability phrases (degraded-model guard,
    same class as llm_triggers.clean_triggers)."""
    seen, out = set(), []
    for s in strings:
        if not isinstance(s, str):
            continue
        p = " ".join(s.split()).strip().strip('",')
        if len(p) < 4:
            continue
        key = p.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out[:MAX_CAPABILITIES]


def validate_reply(reply):
    """Return an error string if `reply` doesn't meet the capsule shape, else None."""
    if not isinstance(reply, dict):
        return f"reply is not an object: {reply!r}"
    for k in ("purpose", "inputs", "outputs", "avoid_when"):
        v = reply.get(k)
        if not isinstance(v, str) or not v.strip():
            return f"field {k!r} missing or empty"
    if len(reply["purpose"].strip()) < MIN_PURPOSE_CHARS:
        return f"purpose too short (<{MIN_PURPOSE_CHARS} chars): {reply['purpose']!r}"
    caps = clean_capabilities(reply.get("capabilities", []))
    if len(caps) < 3:
        return (f"only {len(caps)} usable capabilities after cleaning (need >=3) — "
                f"model may be degraded: {reply.get('capabilities')!r}")
    return None


def store_capsule(capsules, name, reply):
    """Write one validated capsule into the corpus dict (overwrite, never stack —
    a capsule is a snapshot, not a layered merge like triggers)."""
    capsules[name] = {
        "source": "llm-capsule",
        "purpose": reply["purpose"].strip(),
        "capabilities": clean_capabilities(reply["capabilities"]),
        "inputs": reply["inputs"].strip(),
        "outputs": reply["outputs"].strip(),
        "avoid_when": reply["avoid_when"].strip(),
    }
    return capsules


def load_capsules():
    if CAPSULES_FILE.exists():
        return json.loads(CAPSULES_FILE.read_text(encoding="utf-8"))
    return {}


def save_capsules(capsules):
    CAPSULES_FILE.parent.mkdir(parents=True, exist_ok=True)
    CAPSULES_FILE.write_text(
        json.dumps(capsules, indent=2, ensure_ascii=False), encoding="utf-8")


def load_cache():
    if CACHE_FILE.exists():
        return json.loads(CACHE_FILE.read_text())
    return {}


def save_cache(cache):
    CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2))


def run(limit=None, only=None, rate=6.0, catalog=None, workers=1):
    """Returns [{"name", "status": "generated"|"error", "detail"}] — one per skill
    actually attempted (unchanged skills are skipped silently). Same threading
    contract as llm_triggers.run: network phase fans out over workers, all corpus/
    cache writes stay in the calling thread."""
    skills = live_skills_with_paths(catalog=catalog)
    names = sorted(skills) if only is None else [only]

    capsules = load_capsules()
    cache = load_cache()
    bodies = {n: read_body(skills[n][1]) for n in names}

    def _needs_work(name):
        h = content_hash(skills[name][0], bodies[name])
        return not (cache.get(CACHE_PREFIX + name) == h
                    and isinstance(capsules.get(name), dict)
                    and capsules[name].get("purpose"))

    # Cap AFTER filtering (the llm_triggers lesson: capping the raw list starves
    # the uncovered tail).
    if only is None:
        names = [n for n in names if _needs_work(n)]
    if limit:
        names = names[:limit]

    results = []

    def _net(name):
        desc, _path = skills[name]
        try:
            reply = flywheel_llm.chat(
                SYSTEM_PROMPT, user_prompt(name, desc, bodies[name]),
                rate_s=rate, schema=SCHEMA)
        except (
            AttributeError, IndexError, KeyError, OSError, TypeError,
            json.JSONDecodeError, flywheel_llm.TruncatedCompletion,
            urllib.error.URLError,
        ) as e:
            return name, e
        return name, reply

    def _merge(name, reply):
        h = content_hash(skills[name][0], bodies[name])
        err = validate_reply(reply)
        if err:
            print(f"WARN: skipping {name}: {err}")
            return {"name": name, "status": "error", "detail": err}
        store_capsule(capsules, name, reply)
        cache[CACHE_PREFIX + name] = h
        save_capsules(capsules)
        save_cache(cache)
        return {"name": name, "status": "generated", "detail": None}

    def _collect(name, out):
        if isinstance(out, BaseException):
            print(f"WARN: skipping {name}: chat failed ({out})")
            return {"name": name, "status": "error", "detail": f"chat failed: {out}"}
        return _merge(name, out)

    if workers <= 1 or len(names) <= 1:
        for name in names:
            if not _needs_work(name):
                continue
            name2, out = _net(name)
            results.append(_collect(name2, out))
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed
        batch = [n for n in names if _needs_work(n)]
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_net, n) for n in batch]
            for fut in as_completed(futs):
                name, out = fut.result()
                results.append(_collect(name, out))
    return results


def _selftest():
    assert set(SCHEMA["required"]) == {
        "purpose", "capabilities", "inputs", "outputs", "avoid_when"}, "SCHEMA required wrong"

    before = CAPSULES_FILE.read_bytes() if CAPSULES_FILE.exists() else None

    good = {
        "purpose": "Turns a rough idea into a sharpened, buildable concept worth committing to",
        "capabilities": ["restates the idea as a problem statement",
                         "stress-tests directions against criteria",
                         "surfaces hidden assumptions"],
        "inputs": "the raw idea text plus any codebase context",
        "outputs": "a markdown one-pager with recommended direction",
        "avoid_when": "the decision is already made and only execution remains",
    }
    assert validate_reply(good) is None, "good capsule must validate"

    assert validate_reply({"purpose": "short"}) is not None, "short purpose must fail"
    bad_caps = dict(good, capabilities=["a", "b"])
    assert validate_reply(bad_caps) is not None, "fewer than 3 capabilities must fail"
    missing = {k: v for k, v in good.items() if k != "avoid_when"}
    assert validate_reply(missing) is not None, "missing field must fail"

    # clean_capabilities: dedupe, degenerate-drop, cap
    cleaned = clean_capabilities(
        ["Draft the  spec", "draft the spec", "x", "", 5, "Review the result",
         "Flag gaps", "Compose the card", "Extra one", "Extra two"])
    assert cleaned == ["Draft the spec", "Review the result", "Flag gaps",
                       "Compose the card", "Extra one", "Extra two"], \
        f"clean_capabilities wrong: {cleaned!r}"

    # store overwrites, never stacks; shape pinned
    capsules = {}
    store_capsule(capsules, "idea-refine", good)
    store_capsule(capsules, "idea-refine", dict(good, purpose="A second, sharper pass"))
    assert len(capsules) == 1, "store must overwrite, not append"
    assert capsules["idea-refine"]["purpose"] == "A second, sharper pass"
    assert capsules["idea-refine"]["source"] == "llm-capsule"

    # content_hash: body change invalidates even with identical description
    h1 = content_hash("desc", "body-one")
    h2 = content_hash("desc", "body-two")
    assert h1 != h2, "body change must change the hash"
    assert content_hash("desc", "body-one") == h1, "hash must be stable"

    # user_prompt truncation marker
    up = user_prompt("s", "d", "x" * (BODY_PROMPT_CAP + 10))
    assert "…[truncated]" in up, "truncated body must carry the marker"
    assert "…[truncated]" not in user_prompt("s", "d", "short"), \
        "short body must not carry the marker"

    after = CAPSULES_FILE.read_bytes() if CAPSULES_FILE.exists() else None
    assert before == after, "selftest mutated the real capsules corpus on disk!"

    print("PASS")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--only", default=None)
    p.add_argument("--rate", type=float, default=6.0)
    p.add_argument("--catalog", default=None,
                   help="generate for ONE external catalog's skills (<alias>:* "
                        "names) instead of installed skills")
    p.add_argument("--workers", type=int, default=1,
                   help="concurrent LLM calls (network phase only; file writes "
                        "stay single-threaded). Default 1 = sequential.")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        _selftest()
    else:
        run(limit=args.limit, only=args.only, rate=args.rate, catalog=args.catalog,
            workers=args.workers)
