#!/usr/bin/env python3
"""Measure the per-turn token cost of the native skill listing vs `name-only`.

Uses a real BPE tokenizer (tiktoken, cl100k_base) — an approximation of Claude's
tokenizer, but far more faithful than a chars/N proxy. Models the native listing
as one entry per skill in the form Claude sees it ("- name: description"), and
compares it to what remains once descriptions are dropped ("- name").

Run from the repo root:  python scripts/measure_tokens.py
"""

from skill_search.skills_discovery import discover_skills

WINDOW = 200_000  # reference context window for the percentage columns


def _counter():
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda s: len(enc.encode(s))), "tiktoken/cl100k_base (real BPE)"
    except Exception:
        return (lambda s: round(len(s) / 4)), "chars/4 fallback (pip install tiktoken for real counts)"


def main() -> None:
    count, method = _counter()
    skills = discover_skills()

    full = sum(count(f"- {s['name']}: {s['description']}\n") for s in skills)
    name_only = sum(count(f"- {s['name']}\n") for s in skills)
    saved = full - name_only
    desc_tok = [(count(s["description"]), s["name"]) for s in skills]

    pct = lambda t: f"{t / WINDOW * 100:.2f}%"
    print(f"tokenizer : {method}")
    print(f"skills    : {len(skills)}")
    print(f"native full listing (name + description) : {full:>7,} tok  ({pct(full)} of {WINDOW//1000}K)")
    print(f"name-only  (names remain, invocable)     : {name_only:>7,} tok  ({pct(name_only)} of {WINDOW//1000}K)")
    print(f"saved per turn                           : {saved:>7,} tok  ({pct(saved)} of {WINDOW//1000}K)")
    print(f"avg description                          : {sum(t for t, _ in desc_tok) // len(skills):>7} tok/skill")
    print("heaviest descriptions:")
    for t, name in sorted(desc_tok, reverse=True)[:5]:
        print(f"  {t:>5} tok  {name}")


if __name__ == "__main__":
    main()
