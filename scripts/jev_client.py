#!/usr/bin/env python3
"""One way for offline scripts to ask Jev (ADR-0076). Stdlib only.

Every request goes through the enforcer's own `_jev_call`, so host pinning, key routing and model checks
are the hook's. `ask` splits questions under Jev's two token limits, sends the batches in parallel under a
process-wide rate cap, and walks the bench tiers per batch: any failure, a timeout included, moves to the
next tier while the deadline allows (the hook's rule, ADR-0079), a 429 waits for Retry-After once. Offline calls never
use the owner's relay, which drops Retry-After and serves the live hook; when jevd answers they go through jevd
(ADR-0080), pinned to one provider, which passes a provider's 429 and its Retry-After through as they are.

  python3 scripts/jev_client.py --selftest   # batch limits, no network
  python3 scripts/jev_client.py --probe      # one live noul; prints meta, never a key
"""
import http.client
import atexit
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENFORCER = Path(__file__).resolve().parent.parent / "hooks" / "scripts" / "enforcer.py"
MAX_REQUEST_TOKENS = 60000        # Jev: 64k per request (state + every question)
MAX_STATE_PLUS_QUESTION = 30000   # Jev: 32k for state + the single longest question

_ENF = None
_LOAD_LOCK = threading.Lock()


class JevError(RuntimeError):
    """Every tier failed for at least one batch. The message is an exception class name only."""


class JevTooLarge(ValueError):
    """State plus one question exceeds Jev's per-question limit; nothing was sent."""


def load_enforcer():
    """The enforcer, loaded once from this file's own repo with a throwaway ledger dir that is set only
    while the module executes (a reindex child must never inherit it). Its relay is switched off."""
    global _ENF
    with _LOAD_LOCK:
        if _ENF is None:
            prev = os.environ.get("SKILL_CONCIERGE_LOG")
            logdir = tempfile.mkdtemp(prefix="jevclient-")
            atexit.register(shutil.rmtree, logdir, True)
            os.environ["SKILL_CONCIERGE_LOG"] = logdir
            try:
                spec = importlib.util.spec_from_file_location("enforcer_jev_client", ENFORCER)
                assert spec and spec.loader
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
            finally:
                if prev is None:
                    os.environ.pop("SKILL_CONCIERGE_LOG", None)
                else:
                    os.environ["SKILL_CONCIERGE_LOG"] = prev
            mod.JEV_RELAY_URL = None
            mod.JEV_CC_RELAY_URL = None
            _ENF = mod
    return _ENF


def batches(state: dict, questions: dict) -> list:
    """Greedy split in insertion order: each batch stays under MAX_REQUEST_TOKENS in total."""
    enf = load_enforcer()
    base = enf._jev_tokens(json.dumps(state))
    out, cur, used = [], {}, base
    for k, q in questions.items():
        t = enf._jev_tokens(json.dumps({k: q})) + 1
        if base + t > MAX_STATE_PLUS_QUESTION:
            raise JevTooLarge(k)
        if cur and used + t > MAX_REQUEST_TOKENS:
            out.append(cur)
            cur, used = {}, base
        cur[k] = q
        used += t
    if cur:
        out.append(cur)
    return out


class _Rate:
    """Token bucket on request starts: estimated tokens/s and requests/s, shared by every thread."""

    def __init__(self):
        self.tps = float(os.environ.get("JEV_CLIENT_MAX_TPS", "30000"))
        self.rps = float(os.environ.get("JEV_CLIENT_MAX_RPS", "20"))
        self.lock = threading.Lock()
        self.next_t = 0.0

    def wait(self, tokens: int, deadline: float) -> bool:
        with self.lock:
            now = time.time()
            start = max(now, self.next_t)
            if start > deadline:
                return False
            self.next_t = start + max(tokens / self.tps, 1 / self.rps)
        if start > now:
            time.sleep(start - now)
        return True


_RATE = _Rate()


def _retry_after(e) -> float:
    try:
        return min(float(e.headers.get("Retry-After") or 1.5), 10.0)
    except (TypeError, ValueError, AttributeError):
        return 1.5


def _ask_batch(enf, state, qs, tiers, timeout, deadline, retries, stop=None):
    """(answers, via, model) for one batch; raises JevError with the last error's class name. `stop` is set
    when another batch of the same ask has failed: no further request is started for a doomed answer."""
    tokens = enf._jev_tokens(json.dumps({"state": state, "questions": qs}))
    err = "NoTier"
    for tier in tiers:
        key = enf._jev_key(tier)
        if not key:
            err = "NoKey"
            continue
        for attempt in range(retries + 1):
            if stop is not None and stop.is_set():
                raise JevError("Aborted")
            left = deadline - time.time()
            if left < 0.25 or not _RATE.wait(tokens, deadline - 0.25):
                raise JevError("Deadline")
            try:
                # a span tier (Command Code) is never cut before its span (ADR-0079): cutting it early bills
                # it and the next tier for one answer
                return enf._jev_call(state, qs, tier, key,
                                     min(max(timeout, tier.get("span", 0.0)), deadline - time.time()))
            except urllib.error.HTTPError as e:
                err = type(e).__name__
                if e.code == 429 and attempt < retries:
                    pause = _retry_after(e)
                    if time.time() + pause > deadline - 0.25:
                        raise JevError("Deadline") from None
                    time.sleep(pause)
                    continue
                break
            except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException) as e:
                err = type(e).__name__
                break
    raise JevError(err)


def ask(state: dict, questions: dict, timeout: float, deadline: float = None, tiers: list = None,
        workers: int = 4, retries: int = 1):
    """(answers, meta) for every question, or JevError. No partial answers."""
    enf = load_enforcer()
    t0 = time.time()
    deadline = deadline if deadline is not None else t0 + 60
    tiers = tiers if tiers is not None else enf._jev_bench()
    parts = batches(state, questions)
    stop = threading.Event()

    def one(qs):
        try:
            return _ask_batch(enf, state, qs, tiers, timeout, deadline, retries, stop)
        except JevError:
            stop.set()
            raise
    # The deadline bounds every request start and each socket operation; a request already in flight may
    # finish its last read up to `timeout` past it (urllib applies the timeout per operation).
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(parts)))) as pool:
        results = list(pool.map(one, parts))
    answers, per_key = {}, {}
    for qs, (ans, _, model) in zip(parts, results):
        answers.update(ans)
        per_key.update({k: model for k in qs})
    return answers, {"ms": int((time.time() - t0) * 1000), "requests": len(parts),
                     "via": sorted({r[1] for r in results}),
                     "model": sorted({str(r[2]) for r in results}), "per_key_model": per_key}


def _selftest() -> int:
    qs = {f"q{i}": {"type": "noul", "instructions": "word " * 300} for i in range(300)}
    parts = batches({"x": "y" * 100}, qs)
    enf = load_enforcer()
    ok = all(enf._jev_tokens(json.dumps({"state": {"x": "y" * 100}, "questions": p})) <= MAX_REQUEST_TOKENS
             for p in parts) and [k for p in parts for k in p] == list(qs)
    try:
        batches({"s": "a " * 40000}, {"q": {"type": "noul", "instructions": "x"}})
        ok = False
    except JevTooLarge:
        pass
    print("PASS" if ok else "FAIL", f"({len(parts)} batches)")
    return 0 if ok else 1


def _probe() -> int:
    try:
        ans, meta = ask({}, {"sky": {"type": "noul", "instructions": "Is the sky blue on a clear day?"}}, timeout=5.0)
    except JevError as e:
        print("probe failed:", e)
        return 1
    print("requests:", meta["requests"], "via:", meta["via"], "model:", meta["model"], "ms:", meta["ms"])
    print("p(yes):", ans["sky"])
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    if "--probe" in sys.argv:
        sys.exit(_probe())
    print(__doc__)
