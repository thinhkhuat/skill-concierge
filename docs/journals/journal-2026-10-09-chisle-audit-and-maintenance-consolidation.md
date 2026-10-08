# Journal — 2026-10-09: whole-repo chisle audit (v0.64.1) and the maintenance consolidation (v0.65.0)

Both releases ran while Thinh was away ("AFK"), on his orders.

## v0.64.1 — the audit (01:02 → 02:25)

Six read-only agents audited six areas against one brief that demanded a grep count for every "no caller" claim
and a `file:line` for every stale-prose claim. About 179 findings. Six fix agents then worked one worktree with
disjoint files under a written policy: apply high-confidence and proven-dead/proven-stale items that keep
behaviour the same, fix real defects failing-test-first, leave feature cuts and structural moves to Thinh.

The most valuable find was not bloat. `hooks/hooks.json` runs plain `python3`; on a Mac whose PATH lacks Homebrew
that is `/usr/bin/python3` 3.9, and `enforcer.py` and `ledger.py` died at import on a `str | None` annotation. The
turn got no menu and no ledger row, and nothing reported it. Found by accident: a bare `env -i` run of the
enforcer self-test. Now pinned by `tests/test_python39_hooks.py`.

Lesson: a pytest run of 1,100 tests said nothing about either built-in `--selftest`, because nothing ran them;
`tests/test_builtin_selftests.py` closes that.

## v0.65.0 — the four owner decisions (03:03 → 04:25)

Thinh: "do 1, 2, 3, 4". Three lanes, three branches, disjoint files: X (remove the two dormant levers, move the
enforcer self-test, one harness detector), Y (shared installer lib), Z (doctor self-test). Integrated on
`maint/integrate`, ADR-0088, then reviewed.

The pre-release review caught a crash the full suite (1,453 passing) did not: removing the per-skill floor left
`floor=floor` on the getaway leg, so every low-fit turn the Jev router does not take (every low-fit Vietnamese
prompt) raised NameError and exited 1. Lane X's old-vs-new comparison ran English prompts with Jev off and never
reached that leg either. Fix plus two guards: `tests/test_getaway_leg.py` drives `main()` through the leg, and
`tests/test_no_undefined_names.py` runs pyflakes over all shipped Python (vendored engine included) and fails,
never skips, without pyflakes. Proven to fire on the reverted line.

Lesson: "behaviour unchanged" claims proven by old-vs-new runs are only as good as the branches the inputs reach.
A static undefined-name check covers what sampled inputs miss.

Numbers: `enforcer.py` 4,592 → 3,221 lines, compile per prompt 17.0–18.3 → 11.5–12.1 ms (measured by the main
session); `doctor.py` 3,038 → 2,529 lines; installers −142 lines.

Evidence: `plans/261009-0102-chisle-audit/GATES.md` (6/6), `plans/261009-0305-maintenance-four/GATES.md` (9/9),
review reports under `plans/reports/` dated 261009.
