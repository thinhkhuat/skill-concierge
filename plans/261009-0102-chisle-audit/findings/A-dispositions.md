# A — dispositions for `hooks/scripts/enforcer.py` (2026-10-09 01:28 Asia/Saigon)

Worktree `/Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts`. Files changed: `hooks/scripts/enforcer.py`
(4,761 → 4,592 lines), `tests/test_opencode_adapter.py` (one assertion on the deleted `UNDER_OPENCODE`).
Line numbers below are the findings file's (HEAD 692cab1).

## Defect fix (coordinator-approved)

- hooks/scripts/enforcer.py:825 — FIXED (defect): the module crashed at import on Python 3.9 (`/usr/bin/python3`)
  with `TypeError: unsupported operand type(s) for |` at `def _plugin_gate_ok(name: str, scope: str | None = None)`.
  Added `from __future__ import annotations` as the first import. Before: hook exit 1. After:
  `echo '{"prompt":"refactor this python module","session_id":"x"}' | env -i HOME=$HOME PATH=/usr/bin:/bin /usr/bin/python3 hooks/scripts/enforcer.py`
  → exit 0 with a full `additionalContext` menu; `env -i HOME=$HOME PATH=/usr/bin:/bin /usr/bin/python3 hooks/scripts/enforcer.py --selftest`
  → `enforcer --selftest OK: …`, exit 0. A scan for other 3.10+ runtime constructs (`match`, `zip(strict=)`,
  `X | Y` outside annotations, `isinstance(x, A | B)`, `get_type_hints`/dataclass) found none.
  Side effect: that ordered smoke run wrote one real ledger row with sid `x`.

## Per finding

- hooks/scripts/enforcer.py:3483 — SKIPPED: policy, `_selftest()` relocation not approved (structural move; `--selftest` cited by immutable ADRs). The two redundant `import tempfile as _tf` inside it go with that move.
- hooks/scripts/enforcer.py:105 — FIXED: ADR-0032/0036/0048 annex blocks cut to ADR ref + why + revert path; verified the measurements live in docs/adr/0036 (1.9k pool, 0.05/0.10 margins), 0047 (0.40→0.32, alias), 0048 (410 of 2,656, 6 pulls).
- hooks/scripts/enforcer.py:1361 — SKIPPED: policy, per-skill tau feature cut is the owner's call.
- hooks/scripts/enforcer.py:420 — FIXED: `_foreign_scopes` docstring (stale: omitted `opencode-personal`) cut to the contract, the claude-synced rule, the per-harness `personal` rule with ADR refs, and a pointer to tests/test_foreign_scope_completeness.py; inline branch comments kept.
- hooks/scripts/enforcer.py:236 — FIXED: `_running_harness` docstring (stale: omitted cline/opencode) cut to the precedence order and why native signals outrank path markers.
- hooks/scripts/enforcer.py:1491 — SKIPPED: policy, dominance-collapse feature cut is the owner's call.
- hooks/scripts/enforcer.py:747 — FIXED: one `_has_skill_md(name, roots)` helper (same OSError/ValueError → True rule) and one `_AGENTS_SKILLS` constant; zcode/dsh/cline/opencode branches are one return line each. The DSH branch's `_DSH_HOME.exists()` guard was dropped: stat of `<DSH_HOME>/skills/<name>/SKILL.md` gives the same answer when DSH_HOME is absent (False) or unreadable (caught → True). `~/.agents/skills` is now resolved at import instead of per call (HOME is fixed for a hook process; no test patches HOME for these paths).
- hooks/scripts/enforcer.py:2770 — SKIPPED: medium-confidence refactor (`_query_groups`), not in the policy's medium allow-list.
- hooks/scripts/enforcer.py:826 — FIXED: `_plugin_gate_ok` docstring cut to ADR-0052/0053 one-liner, the None=unknown rule and the revert flag; the per-harness WHY moved to two short inline comments on the branches that had none.
- hooks/scripts/enforcer.py:192 — FIXED (partial): `_retrieve` docstring now points to the module cross-harness block instead of restating it. `_row_invocable` docstring kept: it carries a different WHY (the INVOCABLE_PLUGIN_IDS None rule and the DSH/Cline/OpenCode exception), not the post-filter rationale.
- hooks/scripts/enforcer.py:3341 — FIXED: the three outage legs call one local `_fallback(reason, **ms)`; same `_jev_serve` → inject → `_append_offer` sequence, same kwargs in the same order, same return.
- hooks/scripts/enforcer.py:3426 — SKIPPED: low confidence.
- hooks/scripts/enforcer.py:87 — FIXED: embed/Qdrant cap history cut to the live values' reason, ADR-0008/ADR-0054 refs, and the revert path (verified in docs/adr/0054 line 23 and docs/plan.md:3).
- hooks/scripts/enforcer.py:1866 — FIXED (partial): `_tail_lines(path, nbytes)` serves `_jev_context` and `_jev_history` (verbatim duplicates). `_last_used_skill` kept as is: it does not drop the partial first line, so routing it through the helper would change which ledger line is read when the window starts exactly at a line boundary.
- hooks/scripts/enforcer.py:3084 — FIXED: `_intent_plan(cands) -> (ordered, n_intents)` computes the clustering once; `_ranked_mandate` and main()'s `n_intents` ledger field both read it.
- hooks/scripts/enforcer.py:324 — FIXED: deleted all 7 `UNDER_*` booleans; :686 reads `RUNNING_HARNESS == "omp"`; the selftest's UNDER_CODEX save/set/restore removed (RUNNING_HARNESS was already pinned there). `rg -w UNDER_*` across the repo (excluding plans/, vendor/) showed only these readers plus tests/test_opencode_adapter.py:105, whose redundant assertion was removed (the line above it still asserts `RUNNING_HARNESS == "opencode"`).
- hooks/scripts/enforcer.py:18 — FIXED: module docstring no longer claims a ~100 ms happy path or MANDATE-ONLY on every outage; it names JEV_BUDGET_S and the `_jev_serve` / named-route outage behaviour.
- hooks/scripts/enforcer.py:2853 — FIXED: `_retrieve_foreign` docstring now names FOREIGN_FLOOR (0.40) instead of "the external floor's height (0.40)" (EXTERNAL_FLOOR is 0.32), and the two "opposite of the truth" paragraphs are merged.
- hooks/scripts/enforcer.py:3441 — FIXED: `_atop` replaced by `top` (`cands` is not reassigned between them), `det` alias replaced by `_hits`, the restating comment cut to one line.
- hooks/scripts/enforcer.py:404 — FIXED: `_zcode_shares_personal_shelf` wrapper deleted; :480 calls `_agents_shares_personal_shelf`; the selftest zcode block patches that function (5 references) and the `global` line drops the old name.
- hooks/scripts/enforcer.py:2176 — FIXED (partial): one module `_prob(x)` used by `_jev_wide_rows` and `_jev_decide`. The per-chunk top-JEV_PER_CHUNK recomputation in `_jev_shortlist` was left: it sorts raw, unvalidated probabilities, so sharing the validated path would change its behaviour on a malformed answer.
- hooks/scripts/enforcer.py:1507 — FIXED: deleted the v0.4.0 EFFORT note and the SKILL_CONSULT_ROUTE "no longer rides" note; neither describes current code.
- hooks/scripts/enforcer.py:3538 — FIXED: the imperative-veto comment now says 4+ words (MAX_SHORT_WORDS is 3); the UNDER_CODEX comment now says RUNNING_HARNESS (rewritten with the :324 cut).
- hooks/scripts/enforcer.py:1125 — FIXED: dropped `_owner_tier(rep=)`, `_route_of(max_nodes=)` (loop reads `_ROUTE_MAX`), and `_jev_direct_url`'s defaults plus `url = url or JEV_URL`. Every caller passes both arguments (enforcer :2373/:2393, scripts/calibrate_jev_gate.py:175, tests/test_jev_bench.py:230-234). Only divergence: an explicitly empty `ENFORCER_JEV_CC_URL` with a loopback `ENFORCER_JEV_URL` used to fall back to the TypeSafe URL; it now raises like every other off-host URL.
- hooks/scripts/enforcer.py:1698 — SKIPPED: medium-confidence dedupe (`_LOOPBACK`, `_relay`), not in the policy's medium allow-list.
- hooks/scripts/enforcer.py:3484 — FIXED: `_selftest` docstring is one line; the duplicate section label "(12)" on the ADR-0049 consult block is now "(15)".
- hooks/scripts/enforcer.py:3567 — SKIPPED: low confidence.
- hooks/scripts/enforcer.py:2595 — SKIPPED: marked `(check)`, not approved in my prompt.
- hooks/scripts/enforcer.py:1632 — FIXED: stale `:93` / `:289` line references dropped; symbol name kept (verified at audit_skill_usage.py:335).
- hooks/scripts/enforcer.py:1510 — SKIPPED: medium-confidence dedupe of the header literal, not in the policy's medium allow-list.
- hooks/scripts/enforcer.py:2607 — FIXED: `_authorized_skip_inject` docstring lists `"jev"`.
- hooks/scripts/enforcer.py:18 (phase labels) — SKIPPED: low confidence. (The "defect D1" audit label inside the rewritten UNDER_CODEX selftest comment was dropped with that rewrite.)

## Verification (run from the worktree)

- Baseline before edits: `python3 hooks/scripts/enforcer.py --selftest` → `enforcer --selftest OK: …`, exit 0;
  filtered pytest → `417 passed, 686 deselected in 159.13s (0:02:39)`.
- After: `python3 hooks/scripts/enforcer.py --selftest` → `enforcer --selftest OK: refusal guard (5 fire / 6 silent) + …`, exit 0.
- After: `python3 -m pytest -q -p no:cacheprovider tests/ -k "enforcer or jev or ruling or harness or foreign or annex or offer or consult or chain or mandate"`
  → `419 passed, 695 deselected in 183.30s (0:03:03)` (the count rose because other agents added tests in the shared worktree).
- After: every test file that mentions `enforcer` (41 files) → `1 failed, 824 passed in 263.34s (0:04:23)`. The one failure,
  `tests/test_sibling_installers.py::test_readme_054_1_line_mentions_the_zcode_missing_registry_entry_refusal`, read README.md
  while another agent was rewriting it; that test no longer exists, and a re-run of the file gave `35 passed in 7.51s`.
- Python 3.9: see the defect-fix entry above (hook exit 0, selftest OK under `/usr/bin/python3` 3.9.6).

Not done: no independent blind reviewer was spawned for behaviour preservation; the evidence is the selftest and the pytest runs above.
