---
title: "A test that reads the live machine is testing the machine, not the code"
author: Thinh
date: 2026-11-07
branch: main
id: l-9707a150
scope: repo
status: active
src: agent
touches:
  - tests/test_agent_model_guard.py
  - hooks/scripts/agent_model_guard.py
---

## Decided
Make every test that depends on something being installed plant its own copy in a temp directory. In `tests/test_agent_model_guard.py` and the guard's own `--selftest` in `hooks/scripts/agent_model_guard.py`, the skill-form case named a real bundled skill and let `decide_type` read the live `~/.commandcode/skills` root. That skill ships inside a plugin, so it is never a standalone `<name>/SKILL.md` directory there; the guard correctly fell through to its generic message and both the test and the shipped selftest reported the guard as broken.

Both now create a temp root, write `<name>/SKILL.md`, and pass `skills_root=` explicitly. The selftest also asserts the negative: the same name in a temp root with no skill directory must deny generically.

## Tried and ruled out
- Changing the guard to match the name more loosely so the real skill was found. Rejected: the branch is correct; loosening the lookup would change shipped deny behaviour to satisfy a test.
- Installing the skill as a real directory to make the test pass. Rejected: that edits the machine to satisfy a test and breaks again on the next machine or the next plugin layout change.
- Assuming the failure was pre-existing and leaving it. Rejected as a default; it had to be proven pre-existing, and here it was a real brittle assumption worth fixing rather than reporting.

## Watch out
Same family as the vacuous-pass trap and just as quiet: one makes a test prove nothing, this one makes it fail for a reason unrelated to the code. Both come from a test reaching outside its own fixture.

The tell here was that the guard's `--selftest` failed along with the test. A selftest shipped in the product failing on a machine means the selftest, not the machine, made an assumption it had no right to.

In the code:
- `tests/test_agent_model_guard.py` — the skill-form test takes `tmp_path`, writes the skill, passes `skills_root=`
- `hooks/scripts/agent_model_guard.py` — `--selftest` builds its skill in a `tempfile.TemporaryDirectory()`
- both also assert the no-skill-directory case stays generic, so the pair pins both branches
