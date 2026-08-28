# Plan — Catalog tier parity: one offer, one floor (v0.38.0)

Owner decision (2026-08-28, in chat): "no favor, none of the unfairness between the 2" —
built-in `~/.claude/skills` and external catalogs compete at parity in the per-turn offer.
This supersedes the ADR-0032 zero-displacement invariant and the ADR-0043 installed-only
default, by owner order. Revert path is one env var (below).

## The five asymmetries being removed (from the 2026-08-28 audit)

1. Annex silent on installed-getaway turns (enforcer.py:1611) → merged pool fixes natively.
2. External floor 2.2× installed (0.40 vs 0.18) → one floor, ITEM_FLOOR.
3. Zero-displacement invariant + slot asymmetry (8 vs ≤4) → one merged ranked pool, shared TOP_K.
4. Chain routing installed-only (sidecar skips catalog scopes) → sidecar admits `catalog:*`.
5. Flywheel manual default installed-only → default covers installed + every configured catalog; `--installed-only` restores old default; `--catalog <alias>` still narrows.

## Mechanism

- `_retrieve`: drop `must_not tier=external` when `EXTERNAL_OFFER` on. One grouped query,
  over-fetch RETRIEVE_LIMIT, ADR-0034 twin-test post-filter unchanged, trim to TOP_K.
  Rows carry alias derived from payload scope (`catalog:<alias>` → external).
- Render: externals INLINE in the ranked list, `[external:<alias>]` marker, same %-share
  pool, one footer with the get_skill consumption instruction. Annex block deleted.
- Gates (keepoff / deterministic / getaway / actionability / tau / dominance / multi-intent)
  run tier-blind on the merged pool — that IS the parity.
- Ledger: `ext` = external names inside the primary offer (field name kept; semantics
  annex→primary — EPOCH v0.38.0). `xh` unchanged.
- Kill-switch: `ENFORCER_EXTERNAL_OFFER=0` (legacy `ENFORCER_EXTERNAL_ANNEX=0` honored)
  restores ADR-0031 search-only exactly (filter back, no footer, no ext field).
- Chain hints: sidecar admits `catalog:<alias>` scopes (write side in server.py, read side
  in `_visible_sidecar_names`); hinted externals render `[external:alias]`. Overrides and
  mined layers unchanged; KEEPOFF still filters (tier-equal).
- Honest limit: mined chains (ADR-0040) read ledger take sequences; `get_skill` takes are
  not ledger rows today, so externals enter chains only via declared next-skills until a
  get_skill-take recorder exists. Recorded, not built.

## Files

- `hooks/scripts/enforcer.py` — retrieval merge, render, gates comments, ledger docstring,
  selftests 10/11 rewrite (+9d sidecar/hint case), 12 unpack.
- `vendor/skill-search/skill_search/server.py` — sidecar write admits catalog scopes.
- `scripts/flywheel.py` — default all-scope generation, `--installed-only`, per-scope limit.
- `docs/adr/0045-catalog-tier-parity.md` (new); status notes on 0031/0032/0036/0043.
- Docs sweep: CLAUDE.md flags, AGENTS.md guardrails, README, openwiki (quickstart,
  enforcement-gate, retrieval-engine), skills/catalogs/SKILL.md, skills/flywheel/SKILL.md,
  docs/skill-first-enforcement-mental-model.md, CHANGELOG.
- Version 0.38.0: `.claude-plugin/plugin.json`, `.claude-plugin/marketplace.json`,
  `.codex-plugin/plugin.json`, `package.json`.

## Non-goals

- Cross-harness annex (ADR-0034) unchanged — different axis (other harnesses, not tiers).
- doctor's installed-only corpus row unchanged (separate metric; externals have own row).
- get_skill take recorder (mined chains for externals) — recorded fast-follow.

## Acceptance

GATES.md in this dir; enforcer selftest green; live hook e2e; docs sweep; driftcheck +
openwiki parity green; independent blind validator PASS; shipped (commit + push).
