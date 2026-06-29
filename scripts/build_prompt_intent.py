#!/usr/bin/env python3
"""
skill-concierge — build the actionability-gate corpus (the `prompt_intent` collection).

The per-turn enforcer's actionability gate (hooks/scripts/enforcer.py
`_intent_conversational`) suppresses an offer when a prompt leans CONVERSATIONAL over
ACTIONABLE in embedding space. That decision is grounded in this collection: labelled
historical user prompts, embedded with the SAME warm shim the enforcer queries. This
script makes that corpus REPRODUCIBLE (it was prototyped ad-hoc). It:

  1. mines Claude Code's transcript store (~/.claude/projects/**/*.jsonl) for GENUINE user
     prompts (skipping skill bodies, hook output, system notices) paired with what the
     agent then did;
  2. labels each by the AGENT'S ACTION — an outcome signal independent of prompt surface:
       actionable     = the turn did an Edit/Write or a >=3-tool multi-step sequence
       conversational = the turn did NO tool call (pure prose reply)
     (1-2 read-only tools = ambiguous, dropped — only clear anchors go in);
  3. BALANCES the two classes — the gate's class-margin rule is prior-sensitive, so an
     imbalanced corpus biases the mean-similarity and the gate goes inert (see the enforcer
     comment / the M=0.03 calibration);
  4. embeds via the warm shim and (re)builds the Qdrant `prompt_intent` collection.

CAVEAT — threshold tuning is IN-SAMPLE against this corpus: the gate's `_intent_conversational`
kNN self-matches these same points, so replaying them to measure gate accuracy overstates it
(~73% noise-catch in-sample vs ~53% held-out). Sweep thresholds on a held-out train/test split
(temp collection via SKILL_PROMPT_INTENT_COLLECTION on a train slice; evaluate on the held-out
slice). See skills/skill-usage-audit.

Fail-soft: too few labelled prompts (or the shim down) -> warns and leaves the gate to
FAIL-OPEN (no collection => the enforcer offers normally). Pure stdlib. Idempotent
(delete + rebuild).

Env (mirrors the enforcer / .mcp.json): SKILL_QDRANT_URL, EMBED_SHIM_HOST, EMBED_SHIM_PORT,
SKILL_PROMPT_INTENT_COLLECTION, CLAUDE_PROJECTS_DIR.
Usage: python3 scripts/build_prompt_intent.py [--dump PATH] [--min N] [--selftest]
"""
import argparse
import glob
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

QDRANT_URL = os.environ.get("SKILL_QDRANT_URL", "http://localhost:6333").rstrip("/")
COLLECTION = os.environ.get("SKILL_PROMPT_INTENT_COLLECTION", "prompt_intent")
EMBED_HOST = os.environ.get("EMBED_SHIM_HOST", "127.0.0.1")
EMBED_PORT = os.environ.get("EMBED_SHIM_PORT", "6363")
EMBED_URL = f"http://{EMBED_HOST}:{EMBED_PORT}/embed"
PROJECTS = Path(os.environ.get("CLAUDE_PROJECTS_DIR", Path.home() / ".claude" / "projects"))

EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MIN_TOOLS_ACTIONABLE = 3

# Injection markers — text that arrives as a `user` event but is NOT a typed user prompt
# (skill bodies, hook output, system notices). Excluded so labels reflect real intent.
_BAD_PREFIX = ("Base directory for this skill:", "Stop hook feedback", "Caveat:", "## Session",
               "PROMPT EVALUATION", "This session is being continued", "Your turn ended",
               "## Context Usage")
_BAD_SUB = ("[Request interrupted", "<system-reminder", "<command-name", "<command-message",
            "<local-command", "<user-prompt-submit-hook", "<persisted-output", "<task-notification",
            "SessionStart hook", "UserPromptSubmit hook")


def _genuine(s):
    if not s or s.startswith("/") or s.startswith("<"):
        return False
    if len(s.split()) < 3:
        return False
    if any(s.startswith(p) for p in _BAD_PREFIX):
        return False
    if any(b in s[:60] for b in _BAD_SUB):
        return False
    return True


def _prompt_text(ev):
    if ev.get("type") != "user":
        return None
    c = ev.get("message", {}).get("content")
    if isinstance(c, str):
        s = c.strip()
    elif isinstance(c, list):
        if any(isinstance(b, dict) and b.get("type") == "tool_result" for b in c):
            return None
        s = " ".join(b.get("text", "") for b in c
                     if isinstance(b, dict) and b.get("type") == "text").strip()
    else:
        return None
    return s if _genuine(s) else None


def mine():
    """(prompt, label) for clear-label turns across the transcript store. A turn opens on a
    genuine user prompt and closes at the next one; the label is the agent's action between."""
    rows = []
    for fp in glob.glob(str(PROJECTS / "**" / "*.jsonl"), recursive=True):
        try:
            lines = Path(fp).read_text(encoding="utf-8").splitlines()
        except Exception:
            continue
        cur = {"p": None, "n": 0, "e": False}

        def flush(c):
            if not c["p"]:
                return
            if c["e"] or c["n"] >= MIN_TOOLS_ACTIONABLE:
                rows.append((c["p"], "actionable"))
            elif c["n"] == 0:
                rows.append((c["p"], "conversational"))
            # 1-2 read-only tools => ambiguous, skipped

        for ln in lines:
            ln = ln.strip()
            if not ln:
                continue
            try:
                ev = json.loads(ln)
            except Exception:
                continue
            p = _prompt_text(ev)
            if p is not None:
                flush(cur)
                cur = {"p": p[:400], "n": 0, "e": False}
            elif ev.get("type") == "assistant" and cur["p"] is not None:
                cont = ev.get("message", {}).get("content")
                if isinstance(cont, list):
                    for b in cont:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            cur["n"] += 1
                            if b.get("name") in EDIT_TOOLS:
                                cur["e"] = True
        flush(cur)
    return rows


def balance(rows):
    """Equal actionable/conversational via deterministic head-downsample (no RNG -> reproducible)."""
    act = [p for p, l in rows if l == "actionable"]
    conv = [p for p, l in rows if l == "conversational"]
    k = min(len(act), len(conv))
    return [(p, "actionable") for p in act[:k]] + [(p, "conversational") for p in conv[:k]]


def _post(url, payload, method="POST", timeout=20):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def embed(text):
    return _post(EMBED_URL, {"text": text})["vector"]


def build(items, dump=None):
    vecs, labs, prompts = [], [], []
    for p, l in items:
        try:
            v = embed(p)
        except Exception:
            continue
        if isinstance(v, list) and v:
            vecs.append(v)
            labs.append(l)
            prompts.append(p)
    if not vecs:
        return 0, 0
    dim = len(vecs[0])
    try:
        _post(f"{QDRANT_URL}/collections/{COLLECTION}", None, method="DELETE")
    except Exception:
        pass
    _post(f"{QDRANT_URL}/collections/{COLLECTION}",
          {"vectors": {"size": dim, "distance": "Cosine"}}, method="PUT")
    pts = [{"id": i, "vector": vecs[i], "payload": {"label": labs[i]}} for i in range(len(vecs))]
    for b in range(0, len(pts), 300):
        _post(f"{QDRANT_URL}/collections/{COLLECTION}/points", {"points": pts[b:b + 300]}, method="PUT")
    if dump:
        Path(dump).write_text(
            "\n".join(json.dumps({"prompt": prompts[i], "label": labs[i]}, ensure_ascii=False)
                      for i in range(len(prompts))), encoding="utf-8")
    return len(vecs), dim


def _selftest():
    assert _genuine("fix the parser bug in the hook")
    assert not _genuine("Base directory for this skill: x")
    assert not _genuine("/clear")
    assert not _genuine("ok")  # < 3 words
    assert not _genuine("Stop hook feedback: blah blah")
    b = balance([("a", "actionable"), ("b", "actionable"),
                 ("c", "actionable"), ("d", "conversational")])
    assert Counter(l for _, l in b) == {"actionable": 1, "conversational": 1}, b
    print("build_prompt_intent --selftest ok")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Build the prompt_intent actionability-gate corpus.")
    ap.add_argument("--dump", metavar="PATH", help="also write the labelled dataset as JSONL")
    ap.add_argument("--min", type=int, default=200,
                    help="min balanced prompts required to build (else leave the gate fail-open)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    rows = mine()
    print(f"mined {len(rows)} clear-label prompts: {dict(Counter(l for _, l in rows))}")
    items = balance(rows)
    if len(items) < args.min:
        print(f"! only {len(items)} balanced prompts (< --min {args.min}) — leaving the gate FAIL-OPEN "
              f"(no collection -> enforcer offers normally). Re-run once more history accrues.")
        return 0
    n, dim = build(items, dump=args.dump)
    if n == 0:
        print("! embed produced 0 vectors (warm shim down?) — gate FAIL-OPEN (no collection).")
        return 0
    print(f"built '{COLLECTION}': {n} points (balanced {dict(Counter(l for _, l in items))}), "
          f"dim {dim}, cosine @ {QDRANT_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
