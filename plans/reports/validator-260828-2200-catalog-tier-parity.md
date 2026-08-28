# Blind validation — catalog tier parity (ADR-0045, v0.38.0)

Validator: independent adversarial agent (parity-validator), 2026-08-28.
Scope: read-only verification of the CURRENT working tree (uncommitted release state, `git status` shows the release files modified, HEAD `fdaf90c`). Executions limited to the two authorized probes. All line numbers refer to the working tree as validated.

## Verdict: PASS

None of the five audited asymmetries survives in a live code path under default env. Kill-switch verified both directions. Docs match code, with one wrong ADR cross-reference (concern C1, non-blocking).

## Item 1 — Merged retrieval: PASS

- `hooks/scripts/enforcer.py:86-88` — `EXTERNAL_OFFER` flag, legacy `ENFORCER_EXTERNAL_ANNEX` honored as fallback default "1".
- `hooks/scripts/enforcer.py:1116-1123` — `_retrieve` builds ONE grouped query (`group_by: name`, `group_size: 1`); the body carries **no `filter` key** unless the kill-switch is off: `if not EXTERNAL_OFFER: body["filter"] = {"must_not": [{"key": "tier", "match": {"value": "external"}}]}`. Exactly the claimed restore shape.
- Same `TOP_K`: external rows are appended to the same `out` list as installed rows and the list is trimmed at `TOP_K` for both tiers (`enforcer.py:1144-1146`).
- Alias tagging derives from the row's own payload scope: `scope.startswith("catalog:")` → `ext[name] = scope.split(":", 1)[1]` (`enforcer.py:1133-1137`); `"scope"` is requested in `with_payload` whenever parity is on (`enforcer.py:1117-1118`).
- Selftest case (10) pins both directions against an honest mocked server (`enforcer.py:2040-2108`): parity ON → asserts no `filter`, `scope` in payload, merged ranking `[("inst",…,0.5), ("cat:hi",…,0.49)]`, alias map `{"cat:hi": "cat"}`, inline `cat:hi [external:cat]` with a shared %-share (`"(49%)"`), get_skill footer, and NO "External catalog matches" annex block; kill-switch → asserts `must_not tier=external` restored, zero external rows, no `[external:` marker. The mock models the server honoring the filter (`enforcer.py:2061-2070`) — the outcome contract, not a vacuous echo.

## Item 2 — No residual asymmetry: PASS

- `EXTERNAL_FLOOR` / `EXTERNAL_SLOTS`: **zero hits** repo-wide (`grep -rn` across `hooks/`, `scripts/`, `vendor/`, docs probes only).
- The only other live `must_not tier=external` is `scripts/doctor.py:1005` inside `_indexed_skill_names()` — a diagnostic scroll for flywheel-coverage/trigger-hygiene counting, whose docstring records the deliberate exclusion (catalog utterance coverage is measured separately via `scroll_all_points(catalog=alias)`). Not a per-turn offer path; no favoritism effect.
- Separate external annex query: gone. The only remaining separate query is `_retrieve_foreign` (`enforcer.py:1150-1193`) — the ADR-0034 CROSS-HARNESS annex, scoped by `FOREIGN_SCOPES`, which never contains `catalog:*` (`_foreign_scopes()`, `enforcer.py:255-281`, returns only plugin/codex/commandcode/omp/zcode scopes). A different axis, documented as preserved by ADR-0045.
- Annex-block render: gone. `_ranked_mandate` renders externals INLINE in the single ranked list with the same %-share pool (`enforcer.py:1356-1397`) and one get_skill footer when any external row shows (`enforcer.py:1418-1422`); the selftest asserts the block's absence.
- Floors tier-blind: getaway floor is computed from the MERGED-pool top (`enforcer.py:1584, 1589-1590`); per-candidate cutoff is the shared `ITEM_FLOOR` 0.18 applied to merged cands (`enforcer.py:70, 1627`); per-skill tau is name-keyed and default-inert (`enforcer.py:888-891`). Keepoff drop, deterministic hits, dominance, multi-intent all operate on merged cands (`enforcer.py:1575-1582, 1627-1636`).
- Externals bypass the invocable-twin test (`enforcer.py:1134-1137`) — by design (ADR-0045: `get_skill` is their first-class lane), not built-in favoritism.

## Item 3 — Chain routing: PASS

- `vendor/skill-search/skill_search/server.py:272-277` — `_write_next_skills_sidecar` joins catalog scopes (ADR-0045 comment; per-scope merge, unconditional best-effort).
- `hooks/scripts/enforcer.py:731-734` — `_visible_sidecar_names` appends every `catalog:*` scope in the sidecar when `EXTERNAL_OFFER`; `enforcer.py:744-753` populates `_EXT_HINT_ALIASES` from those scopes; `_chain_hint_data` calls `_visible_sidecar_names()` before rendering, so the tag map is always fresh.
- `_ext_tag` renders `` [external:<alias>] `` (`enforcer.py:701-704`); applied to the CHAIN-HINT seed and successors (`enforcer.py:847-848`) and to the ROUTE projection line (`enforcer.py:1414-1416`). Selftest case (9d) pins the sidecar admission (`enforcer.py:1950`).

## Item 4 — Flywheel: PASS

- `scripts/flywheel.py:358-364` — bare `--generate` default: `scopes = [None] + _configured_aliases()` — installed FIRST, then every configured catalog from `catalog-roots.json`. Broken catalog degrades to a WARN + skip, never aborts the run (`flywheel.py:379-386`).
- Per-scope `--limit`: the scope loop (`flywheel.py:401-421`) passes `catalog=sc, limit=limit` to both `llm_eval_gen.run` (`scripts/llm_eval_gen.py:112`) and `llm_triggers.run` (`scripts/llm_triggers.py:196`) — the cap applies per scope, matching `auto_flywheel`'s comment "each scope capped at MAX_PER_RUN".
- `--installed-only` exists (`flywheel.py:484-486` → `scopes=[None]`, `flywheel.py:361-362`); `--catalog <alias>` narrows.
- `hooks/scripts/auto_flywheel.py:210-216` — ONE default run: `flywheel.py --generate --limit MAX_PER_RUN --workers N`; no `--installed-only`, no `--catalog` (the old installed-pass + per-alias loop removed).
- `scripts/flywheel_manifest.py:39-56, 75-76` — `write_run(..., scope=...)` records `scope` ("installed" | "all" | "catalog:<alias>"), backward-compatible; `flywheel.py:456-463` writes it; status card prefers the explicit field (`flywheel.py:254-259`).

## Item 5 — Probes (run from repo root)

- `python3 hooks/scripts/enforcer.py --selftest` (tail):
  ```
  enforcer --selftest OK: refusal guard (5 fire / 6 silent) + ranked-mandate %-share + actionability imperative-veto (17 fire / 12 off) + keepoff-drop + gap-collapse + per-skill-tau/deterministic-routes (default-inert) + authorized-skip tier (3 injects on / silent-off) + selfref over-fire lane (6 fire / 6 off) + cross-harness annex + tier-parity merged retrieval + external chain-hint tags (ADR-0045) + CJK word-count (pre-gate no longer swallows no-space scripts)
  ```
- `python3 plans/260828-2115-catalog-tier-parity/e2e_probe.py` (tail) — LIVE leg: real embed + live Qdrant (leg 1) and a real enforcer subprocess hook contract (leg 2), throwaway ledger dir:
  ```
  leg1 merged top-8: antigravity:skill-developer[external:antigravity](0.80), antigravity:skill-improver[external:antigravity](0.80), antigravity:project-skill-audit[external:antigravity](0.77), antigravity:yao-meta-skill[external:antigravity](0.75), antigravity:skill-writer[external:antigravity](0.75), open-knowledge-write-skill(0.75), skill-creator:skill-creator(0.73), antigravity:skill-creator-ms[external:antigravity](0.73)
  leg2 offer (1792 chars): carries external rows
  E2E PARITY OK
  ```
  Externals interleave with installed rows by score in the live merged pool — including displacing installed rows — which is the parity claim made real.

## Item 6 — Adversarial pass

Hunted for: a gate that demotes external rows differently, a render path hiding their scores, a second tier=external filter with the flag on, docs contradicting code.

- Gates: all downstream gates run on merged cands (Item 2). Scores: rendered uniformly (`enforcer.py:1395-1396`), raw scores logged to the ledger for both tiers; external rows logged inside the PRIMARY offer event's `ext` field (`enforcer.py:1637-1641`) — matching the claimed ledger semantics. Second filter: the only tier=external query filter outside the kill-switch leg is the doctor diagnostic (Item 2). Index substrate: `server.py:668` stamps `tier=external` on catalog points; `skills_discovery.py:146-149` documents the tier now drives only the kill-switch + telemetry.
- Installed-side "protection" that remains: FOREIGN annex slots (2) — different tier, not built-in-vs-catalog; dominance/multi-intent apply to merged cands, not per tier.
- Docs vs code: CLAUDE.md:14, AGENTS.md:72, README.md:200/262-276/358, CHANGELOG.md:10-32, openwiki (quickstart.md:127-136, operations.md:201-204, architecture/enforcement-gate.md:80-84, retrieval-engine.md:65-67) all describe the merged pool, kill-switch, flywheel default, chain tags exactly as coded. ADR-0045 exists and matches. Versions 0.38.0 in all four manifests (`package.json:4`, `.claude-plugin/plugin.json:3`, `.claude-plugin/marketplace.json:8,23`, `.codex-plugin/plugin.json:3`).

### Concerns (non-blocking)

- **C1 — wrong ADR cross-reference in CLAUDE.md.** The `ENFORCER_ANNEX_DYNAMIC` flag entry says "the ADR-0034 FOREIGN annex only **since ADR-0044**"; the correct reference is ADR-0045 (code: `enforcer.py:90` "foreign annex only since ADR-0045"; ADR-0044 is the utterance-corpus home ADR). Cosmetic; fix with the next doc touch.
- **C2 — disclosed honest limit, not a defect:** externals enter chain hints only via declared `next-skills`; mined chains (ADR-0040) cannot see `get_skill` takes yet ("recorded, not built", ADR-0045 §4). Already disclosed in the ADR and AGENTS.md — listed here for completeness.
- **C3 — not run:** `python3 scripts/driftcheck.py driftcheck.json` was NOT executed (it writes `driftcheck.json`, outside this validator's read-only mandate). The repo's commit-gate step remains the committer's to run.
- **C4 — session-start CLAUDE.md snapshot stale vs live file:** the session-injected CLAUDE.md copy lists the old flag set (no `ENFORCER_EXTERNAL_OFFER`) while the live file has it — expected for an uncommitted working tree; noted only so no one reads the stale snapshot as a docs gap.

## State of evidence

Checked by reading: enforcer.py (flags, `_retrieve`, `_retrieve_foreign`, `_ranked_mandate`, `_ext_tag`/`_visible_sidecar_names`/`_chain_hint`, gates at 1560-1647, selftest cases 9d/10), server.py (sidecar writer, index payload), skills_discovery.py, flywheel.py, auto_flywheel.py, flywheel_manifest.py, llm_triggers.py/llm_eval_gen.py (catalog param), build_triggers.py/flywheel_llm.py (external skip + per-catalog lift), doctor.py (diagnostic filter), all docs surfaces, four version manifests. Ran: the two authorized probes (tails quoted above). Grep sweeps: EXTERNAL_FLOOR/EXTERNAL_SLOTS (zero), `tier` filters (kill-switch + doctor diagnostic only), `catalog:` touchpoints in enforcer (tagging/visibility only).

VERDICT: PASS
