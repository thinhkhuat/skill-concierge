# Ship J20: docs and version bump (0.58.0), 2026-10-04

## Authority surfaces

Created
- `docs/adr/0078-consult-sieve-jev-widening.md` (Accepted). Decision, gate verdict lines copied from `reports/iter2-gate-raw.txt`, the five judgement calls from `plans/reports/decisions-261004-0942-sieve-iter2.md`, consequences, revert path. Narrow margin (Holm p 0.0469, 6 sessions) and the proxy-case limit are stated.

Changed
- `docs/adr/README.md`: row 0078 after 0077. (The existing rows 0072 to 0069 sit after 0077 out of order; left alone.)
- `CHANGELOG.md`: `[Unreleased]` became `## [0.58.0] - 2026-10-04`. Added: the widening, the two default-off flags (now with the second failed gate), `scripts/sieve_recall.py`.
- `AGENTS.md`: `SKILL_CONSULT_JEV_WIDEN` in the default-ON list and a Runtime flags bullet; SLOTS and RRF bullets cite both gates.
- `CLAUDE.md`: same facts in the governance flags line; SLOTS/RRF text cites both gates.
- `README.md`: version badge, new 0.58.0 status line, `SKILL_CONSULT_JEV_WIDEN` env table row, SLOTS/RRF rows cite both gates.
- `docs/epoch-watch.md`: new v0.58.0 section, W37 (highest existing was W36).
- Version 0.58.0 in `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json` (2 occurrences), `.codex-plugin/plugin.json`, `package.json`, `openwiki/quickstart.md`.

Not touched: `scripts/`, `skills/`, `tests/`, `vendor/`, `hooks/`, `driftcheck.json`, old ADRs. No git, no installers.

## Figures used (all copied from `iter2-gate-raw.txt`)
- D_J20 PASS n=29, recall@20 24.1 -> 48.3, gained 7 / lost 0, sessions +6/-0, p=0.0156, Holm p 0.0469, G6 p90 73 -> 969 ms.
- D_J40 PASS, same counts (27.6 -> 51.7 at 40).
- D_SR40 FAIL n=57, recall@40 28.1 -> 33.3, gained 5 / lost 2, Holm p 0.2266.
- Jev: 57 calls, 0 failed, p50 839 ms, p90 969 ms.
- Prereg sha256 `60c3389d...` and commit `7b339dd` from `iter2-gate-meta.txt` and the decisions log.

## Verification (run this session)
- `python3 scripts/driftcheck.py driftcheck.json`: `IN SYNC: every fact matches its source of truth.`, exit 0 (version SSOT 0.58.0; all `[ok]`).
- `grep -rn "0.57.1" .claude-plugin .codex-plugin package.json openwiki/quickstart.md`: no output (grep exit 1).
- `python3 scripts/openwiki_parity_guard.py </dev/null; echo $?`: no output, exit 0.
- The four JSON manifests parse. ADR relative links resolve on disk.

## Concerns and what I did not check
- The README 0.58.0 status line says "published" because `driftcheck.json` matches the regex `` `x.y.z`...**published `` on that line; the guard cannot pass without the word. It is true only once 0.58.0 is pushed. The release step should push, or correct the line.
- W37 reads the widen outcome from consult cards or transcripts, not the ledger: `consult_verdict` rows (`scripts/consult_log.py`) carry no widen field. Adding one would be a code change, outside this task.
- The ADR says "Not checked: widen under a non-Claude harness, and Jev with recent context", taken from `ship-j20-implementation-report.md`.
- I did not run the test suite, doctor, or `verify_shipped.py` (outside this task's scope). `openwiki/` prose was not reviewed beyond the version line; `/openwiki:wiki update` was not run, so the wiki may not mention the new flag.
- Changelog heading uses a hyphen as ordered; older headings use an em dash. Driftcheck accepts both.

Status: DONE_WITH_CONCERNS
Summary: ADR-0078, changelog, flag docs, W37 and the 0.58.0 bump are written, and driftcheck is IN SYNC with the parity guard exit 0. The README "published" word is true only after the push, and the wiki prose was not refreshed.
