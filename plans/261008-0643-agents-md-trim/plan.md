# AGENTS.md trim (draft, awaiting approval)

Status: PROMOTED 2026-10-08 on Thinh's approval ("Promote + commit"). AGENTS.md and CLAUDE.md are governing files, so rule [4] applied: draft, approve, promote. Backups: `~/_ARCHIVE/agents-md-trim-20261008/`. After promotion `driftcheck.py` exited 0 and `doctor.py` reported `status: OK`.

## Goal

Cut skill-concierge's `AGENTS.md` so every Codex session that loads it pays far less, without losing any content. Codex 0.160.1 caps the instruction chain at 32 KiB by default; the cap was raised to 128 KiB in `~/.codex/config.toml`. The trim does not make that raise unnecessary: the chain inside this repo is about 76.6 KB after it (compiled global file 38,754 B + MY-WORKBENCH AGENTS.md 12,279 B + this AGENTS.md 25,608 B), still above 32 KiB, so the raised cap stays required. It cuts what every Codex session here loads by about 37 KB.

## Result (from `build_draft.py`, 2026-10-08)

| File | Before | After |
|---|---|---|
| `AGENTS.md` | 62,868 B | 25,608 B |
| `CLAUDE.md` | 18,710 B | 4,206 B |
| `docs/runtime-flags.md` | none | 42,943 B (new) |
| `docs/repository-layout.md` | none | 8,271 B (new) |

## What changes

1. **`AGENTS.md` → Runtime flags.** The full section moves verbatim to `docs/runtime-flags.md`; only relative links are re-based for `docs/`. AGENTS.md keeps a table of 38 flags (flag, default, effect in one line, ADR), the `ENGINE_ENV_KEYS` invariant, and the machine-local settings.
2. **`AGENTS.md` → Repository layout.** The full section moves verbatim to `docs/repository-layout.md`. AGENTS.md keeps one line per area, and the `skills/{...}/SKILL.md` list that `check_skill_list_parity.py` reads.
3. **`CLAUDE.md` → Governance flags bullet** (about 14 KB, a near-copy of the AGENTS.md flag section) becomes a 3-line pointer. Its two unique facts move into the AGENTS.md table: capsules are built by `flywheel.py --generate --capsules`, and `skill-concierge:reputation` manages the ranking.
4. **Unchanged:** Orientation, Setup & verification, Conventions, Guardrails (load-bearing gates, kept word for word), OpenWiki, and every other CLAUDE.md bullet.
5. **One addition:** a table row for `SKILL_COMMANDCODE_ROOTS` (default ON in `skills_discovery.py:52`, ADR-0038). It is in `ENGINE_ENV_KEYS` and README but had no entry in the old flag section.

## Proof nothing was lost (`build_draft.py` output)

- Verbatim move: 0 lines of either old section missing from its new doc.
- CLAUDE.md bullet: 199 tokens checked (backtick names, ADR numbers, decimals); 0 missing. Three tokens survive in another spelling, listed in `EQUIV` in the script.
- Every relative link in the four files resolves from its final location.
- `check_skill_list_parity.py` and `check_doc_parity.py` pass against the draft.

## Independent validation

`reports/validator-report.md` (agent-validator, blind): **PROMOTE WITH FIXES**. It found no lost content, 120/120 links resolving, and the untouched sections byte-identical. It found 10 wrong or loose claims in the new table (F1-F10) and 5 rules that had become less visible (L1-L5). All were applied (`fix_parts.py`, `patch_build.py`):

- F1/F4 `SKILL_LLM_TRIGGERS`: the curated phrases apply whatever the flag says; ON in the shipped `.mcp.json`.
- F2 `SKILL_FINDABILITY`: reindex-time, not query-time.
- F3 `SKILL_COMMANDCODE_ROOTS`: entry added to `docs/runtime-flags.md`.
- F5 `ENFORCER_ANNEX_COMPLEMENT` and the `ENFORCER_EXTERNAL_OFFER` alias are in the `ENFORCER_EXTERNAL_ANNEX` row.
- F6, F8, F9: annex default, "before any embed or Qdrant I/O", jevd only when it holds keys.
- F7: the preamble says "most flags"; the keep-off rule is a line of its own (also L1).
- F10: six reindex paths (`trigger_filter.py reindex` was missing), fixed in the table and in the moved text, the one correction made to that text.
- L2: the `SKILL_SYNCED_ROOTS` precondition is in its row. L4: the machine's Jev bench facts are back. The pointer now fires when a flag is set in any env or reasoned about, not only on a code edit.
- CLAUDE.md's last line now also points at `docs/repository-layout.md`.

Pre-existing, fixed in a follow-up commit on Thinh's "fix both": P1, the `ENFORCER_JEV_ROUTER` text named `TYPESAFE_API_KEY` as the router's key precondition; `enforcer.py:2304-2306` needs any bench tier with its own key (`_jev_key`), now stated in `docs/runtime-flags.md`. P2, `vendor/skill-search/skill_search/ports.py` pointed at "AGENTS.md's Runtime flags" for a port-caller list that was never there; it now points at `tests/test_port_agreement.py`, which names every caller.

## Step ledger — re-claude

- Step 1 (check length): DONE. `wc`: AGENTS.md 164 lines, 62,868 B; CLAUDE.md 28 lines, 18,710 B (one bullet is about 14 KB).
- Step 2 (integrate workflow orchestration): SKIPPED — authorized by AskUserQuestion; Thinh chose "Skip step 2 (Recommended)". `~/.claude/skills/workflow/SKILL.md` does not exist (`ls`: No such file).
- Step 3 (verification section): DONE. AGENTS.md *Setup & verification* already names `doctor.py` and `driftcheck.py`; CLAUDE.md's first bullet names doctor. No change needed.
- Step 4 (contradictions): DONE. The validator's point 4 found only contradictions the draft had introduced (F5, F7), and both are fixed. No pre-existing contradiction needs Thinh's choice.
- Step 5 (global skill candidates): DONE. None. Every moved block is specific to this repo's flags and files.
- Step 6 (essentials for the root file): DONE. The compact sections, invariants and gotchas stay in AGENTS.md; CLAUDE.md keeps its quick reference.
- Step 7 (group the rest): DONE, adapted. The content went to `docs/`, not `.claude/rules/`, because AGENTS.md serves every harness and Codex and the others never read `.claude/rules/`, and because `.gitignore` ignores `.claude/*` apart from `settings.json` (AGENTS.md *Guardrails*).
- Step 8 (flag for deletion): DONE. Nothing deleted: the moved text is project-specific evidence. P2 above is the one stale line found.

## Promotion steps (after approval)

1. Back up `AGENTS.md` and `CLAUDE.md` beside themselves (`*.bak-20261008`).
2. Re-run `build_draft.py` (it rebuilds from the live files, so edits made meanwhile are carried), confirm `RESULT: PASS`.
3. Copy the four `draft/` files into place.
4. Add `docs/runtime-flags.md` and `docs/repository-layout.md` to `driftcheck.json` → `paths_exist`.
5. Run `python3 scripts/driftcheck.py driftcheck.json` (exit 0) and `scripts/doctor.py` (status OK).
6. Commit only on Thinh's order. No version bump: docs-only.
7. Tell running sessions in this repo that AGENTS.md changed (rule [4]).

## Files

- `parts/flags-compact.md`, `parts/layout-compact.md`: the hand-written replacement sections.
- `build_draft.py`: assembles `draft/` from the live repo and runs every check above.
- `draft/`: the four files to promote.
- `reports/validator-report.md`: the independent validator's verdict.
