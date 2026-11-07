---
title: "Testing code embedded in a shell string: extract by delimiters, never by the code's first line"
author: Thinh
date: 2026-11-07
branch: main
id: l-ad76d0dd
scope: repo
status: active
src: agent
touches:
  - vendor/skill-search/tests/test_launcher_engine_env.py
---

## Decided
To test an inline program that lives inside a shell string, extract it by its QUOTING
BOUNDARIES, never by its content.

`bin/skill-search-mcp` runs its engine-env loader as `"$VENV/bin/python" -I -c '…'`.
The program cannot be imported, so the only honest way to test it is to lift it out and run
it as its own process — which is exactly what the launcher does. The first extraction
anchored on content:

    re.search(r"-I -c '(import json.*?)\n' 2>/dev/null", src, re.S)

That worked until a comment line was added above `import json`. Then it matched nothing,
every test in the file errored, and the message read "could not locate the inline loader" —
true, but pointing at the extraction, not at the code under test. The fix anchors on the
delimiters instead:

    re.search(r"-I -c '(.*?)\n' 2>/dev/null", src, re.S)

Correct because the delimiters are the shell contract; the first line of the program is not.

## Tried and ruled out
- **Anchoring on the first line of the inline program.** Any edit above that line breaks
  every test in the file at once, including tests unrelated to the edit.
- **Asserting only that the extraction found SOMETHING.** The assert is what made the
  breakage loud. Weakening it to a skip would have turned a broken harness into a silently
  green suite — worse than the original defect.
- **Testing the loader's logic by re-implementing it in the test.** That tests the copy, not
  the shipped bytes, and the copy is free to drift from the launcher.

## Watch out
- **An extraction test has two failure modes and they look alike.** "The program is broken"
  and "the extractor stopped finding the program" both surface as red tests. Assert the
  extraction SEPARATELY from the behaviour so the message says which one broke.
- **Single-quoted shell strings forbid apostrophes in the embedded program.** A comment
  reading "Python's" closes the string and turns the shell script into a syntax error. The
  block now carries a standing NOTE saying so.
- **Three real defects lived in that loader because nothing exercised it.** The extraction
  indirection is the price of reaching code the language cannot import.

In the code:
- `bin/skill-search-mcp` — the `-I -c '…'` inline loader
- `vendor/skill-search/tests/test_launcher_engine_env.py` — `_loader_source()`, the
  delimiter-anchored extraction, and 9 tests that run the real program as a subprocess
- `bash -n bin/skill-search-mcp` catches the apostrophe class before pytest ever runs
