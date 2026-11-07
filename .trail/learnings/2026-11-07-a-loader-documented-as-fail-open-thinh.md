---
title: "A loader documented as fail-open still aborted startup, because only the happy path was ever tested"
author: Thinh
date: 2026-11-07
branch: main
id: l-c4f331c0
scope: repo
status: active
src: agent
---

## Decided
A config loader documented as "fail-open" was not fail-open, and the check that
should have caught it was the one thing never tested: a malformed input.

`bin/skill-search-mcp` loads `~/.claude/skill-concierge/engine-env.json` before
exec-ing the engine. It filtered keys with Python `str.isidentifier()`, which
accepts Unicode. A key `ÉCOLE` passed the filter, the block emitted
`export ÉCOLE=x`, and bash answered "not a valid identifier" — which under the
script's `set -euo pipefail` aborted the entire launcher. So a bad config file
stopped the MCP server from starting, the exact opposite of the guarantee the
code comment and the ADR both made.

Fix: match a POSIX shell name exactly — `re.fullmatch(r"[A-Z_][A-Z0-9_]*", k)`,
ASCII only — and wrap the `eval` in `|| true` as a second line of defence.

## Tried and ruled out
- **Testing the loader with the real config file.** It passed, every time. A
  fail-open claim is only about the FAILURE path, so a healthy-input test proves
  nothing about it.
- **Trusting `str.isidentifier()` because Python and bash "both take identifiers".**
  They do not agree: Python's rule is Unicode-wide, bash's is ASCII. Where two
  systems must agree on a name, encode the STRICTER system's rule, not the
  convenient one's.
- **Reading the code comment as evidence the behaviour existed.** The comment said
  "fail-open on every error"; the code did that for a missing or unparseable FILE
  and not for a well-formed file with an odd KEY.

## Watch out
- **Enumerate the input classes a guarantee covers, then test one of each.** For a
  fail-open claim that is at least: absent file, unreadable file, malformed JSON,
  valid JSON but wrong type, valid JSON with hostile keys, valid JSON with an empty
  value. Ordering and precedence need their own cases on top.
- **A `set -euo pipefail` script turns every unexpected non-zero into a startup
  abort.** Any block claiming not to block must guard its own last command.
- **An independent auditor found this; the author did not.** The author had already
  reasoned about the block and concluded it was safe — the reasoning was about the
  paths already in mind.

In the code:
- `bin/skill-search-mcp` — the engine-env block; the key filter and the guarded `eval`
- reproduction: config `{"ÉCOLE":"x"}` -> Python emits `export ÉCOLE=x` -> bash
  "not a valid identifier" -> launcher exits before `exec "$BIN"`
- verification: the real launcher completes an MCP `initialize` handshake with a
  config holding `ÉCOLE`, `bad key`, `1NUM` and an empty value; a malformed file
  leaves the environment untouched and exits 0
- shipped in v0.76.3, commit 68db3bf
