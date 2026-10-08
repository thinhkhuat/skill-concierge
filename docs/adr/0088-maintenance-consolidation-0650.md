# 0088 — Maintenance consolidation: two dormant levers removed, self-tests out of the shipped scripts, shared installer and harness helpers

- Status: accepted
- Date: 2026-10-09
- Deciders: Thinh ("do 1, 2, 3, 4", 2026-10-09 ~03:03)
- Supersedes: the runner-up-gap collapse (`ENFORCER_DOMINANCE_RATIO`) described in ADR-0011, and the per-skill
  floor (`ENFORCER_PER_SKILL_TAU`) left inert by ADR-0012. The rest of both ADRs stands.
- Relates to: ADR-0027 (SessionStart self-heal), ADR-0042 (one-directional installers)

## Context

The whole-repo audit of 2026-10-09 (`plans/reports/chisle-audit-261009-0102-whole-concierge.md`, shipped as v0.64.1)
left four structural changes to the owner, because each removes a feature or moves a large body of code:

1. `hooks/scripts/enforcer.py` carried a 1,266-line `_selftest()` and `scripts/doctor.py` a 516-line one. The hook
   runs as `__main__` on every prompt, so Python compiles the whole file each time and never caches it. Nothing in
   `tests/` ran either self-test until v0.64.1.
2. Two enforcer levers had been default-off since they shipped and were set nowhere: the runner-up-gap menu collapse
   and the per-skill floor. The collapse's own measurement found single-lead collapse worse; arming the per-skill
   floor would lower the bar for every calibrated skill. The Sept 26 over-engineering audit had proposed the same cut.
3. Five installers carried byte-identical copies of the same shell helpers; one copy had already drifted.
4. Harness detection was written three times (enforcer, doctrine, ledger), and the copies had drifted: doctrine did
   not know OpenCode until v0.64.1.

## Decision

1. **The self-test bodies live in `tests/`** (`tests/enforcer_selftest.py`, `tests/doctor_selftest.py`; no `test_`
   prefix, so pytest does not collect them directly). `enforcer.py --selftest` and `doctor.py --selftest` keep
   working — immutable ADRs and docs cite them — by loading the body and executing it inside the script's own
   module namespace, so every global reference and patch in the body is unchanged. A copy without `tests/` prints
   one line and exits 2. `tests/test_enforcer_selftest.py` and `tests/test_doctor_selftest.py` run the bodies
   under pytest.
2. **Both dormant levers are deleted.** The getaway floor is `GETAWAY_FLOOR` at every call site and the menu is
   never collapsed to one row. `scripts/calibrate_thresholds.py` and the `thresholds.json` it writes stay: doctor
   reads that file on its own.
3. **`adapters/lib/sync.sh` holds the helpers that were byte-identical** (`_ver_ge`, `_is_own_checkout`, the staged
   `_export_to` of claude-code/codex/zcode, `_refuse_unexportable_checkout`). The claude-code, codex, omp, zcode and
   opencode installers source it from their own location and exit 1 with a message naming the path if it is
   missing. Helpers that differ in behaviour stay per installer (OMP's export skips the legacy staging cleanup
   because its cache folder is shared).
4. **`hooks/scripts/harness.py` is the one harness detector** for enforcer, doctrine and ledger. Each module keeps its
   call-site semantics; Claude ledger rows still carry no harness field. Where the three copies disagreed, the
   enforcer's answer wins, with one exception: the `.commandcode` path marker doctrine already had is kept, so the
   enforcer now also reads it (`docs/caveats.md` requires it; the Command Code mod always sets
   `SKILL_CONCIERGE_HARNESS`, so this changes an offer row's `harness` only when that variable is unset). If
   `harness.py` cannot be imported, each hook exits 0 with no output.

## Consequences

- `enforcer.py` shrinks from 4,592 to 3,221 lines; `compile()` of it drops from 17.0–18.3 ms to 11.5–12.1 ms per
  prompt (median of 30, five runs, Python 3.12, this machine). `doctor.py` shrinks from 3,038 to 2,529 lines.
- Hook output is unchanged: lane checks ran main against the new code on 15 prompts (Jev off) and in 16 harness
  setups (doctrine output, enforcer output and ledger rows identical), and 139 installer runs matched main's exit
  codes, output (bar timestamps and bash line numbers) and written files. `tests/test_harness_detector.py` pins the
  detector against main's answers over 77 cases; `tests/test_installer_shared_lib.py` pins the shared lib.
- Ledger rows change only in conflicting-signal cases no live harness produces (several env markers set at once,
  no payload, no explicit `SKILL_CONCIERGE_HARNESS`), now answered the enforcer's way. Evidence and the case list:
  `plans/261009-0305-maintenance-four/`.
- Revert: each part is its own commit on `maint/integrate`; reverting the lever removal restores both flags at
  their default-off behaviour.
