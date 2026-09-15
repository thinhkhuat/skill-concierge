# ADR-0054 — Harness-message lane, config-driven routes, and the v0.46.0 usage-audit fixes

Status: Accepted (2026-09-15)
Relates to: ADR-0011 (keep-off), ADR-0019 (authorized-skip tier), ADR-0034 (cross-harness offer isolation), ADR-0036 (annex margin), ADR-0041 (route projection), ADR-0050/0051 (DSH/Cline parity).
Evidence: `plans/reports/audit-260914-2325-concierge-usage-strengthen.md` (epoch v0.46.0, 2026-09-06 03:06 → 09-14; two independent reviews recorded in the report).

## Context

The first epoch-scoped audit of daily use found the enforcer's attention pointed at the wrong turns:

- **59 % of enforcer decisions (344/581) were on text no user typed** — `<task-notification>`, monitor events, OMP `omp-msum` summarizer calls, cross-session/teammate messages, idle `<system-reminder>` nags — and 168 of them received a full ranked preview. Seven incidental takes followed. Those turns owned the never-taken top-3 slots (`horizon-notify` 201 offers / 0 takes, all on notifications) and 14 of the 19 ROUTE projections. There was no shape check anywhere in `enforcer.py`.
- **On human prompts the doctrine works**: USING 56 %, SEARCH 12 %, false-SKIPPING 8 %. The ledger's "14 % uptake" undercounts ~4× because 64 of 110 USING turns read the SKILL.md inline.
- **Eleven prompts named the skill and the preview missed it** (`/unlazy`, `/progress-map`, `cook --auto`, `ego lite browser`, `vn-gov-docx`); the deterministic-route scaffold existed but was default-OFF with an empty config, and ran after the embed step so four of the eleven were lost to a timeout.
- **All 53 `qdrant_down` rows sat at 101-106 ms against a 100 ms cap; all 21 embed timeouts at 359-381 ms against 350 ms** — censoring, not outages.
- **ADR-0011 keep-off had been empty since 2026-06-29** (generator never wired into doctor).
- **`dsh-personal` re-roots of the plugin's own skills leaked into Claude offers as bare twins** (`doctor` beside `skill-concierge:doctor`; 27 of 581 offers) because Claude's foreign-scope tuple omitted `dsh-*`/`cline-*`.
- `analyze.py` counted the `fallback` field truthy, so the "fallback rate" read 39 % when the outage share was 13 %.

## Decision

1. **Harness-message lane** (`ENFORCER_HARNESS_SKIP`, default ON). A prompt whose head matches a harness-generated shape is authorized to skip before the refusal guard, consult route, embed and every Qdrant round-trip: ledger band `harness_skip`, `fallback = "harness_message"`, a fourth `SKILL-CHECK:` leg whose locked signature is **"harness-message lane"** (audit `_AUTHORIZED_SIGNATURES`), and **no chain hint** (a notification is not the user's continuation). Anchored at the prompt head so a pasted block mid-prompt still routes normally. OMP worker briefs ("Complete assignment thoroughly…") are orchestrator-authored tasks and are not gated.
2. **Deterministic routes become config-driven and default ON** (`ENFORCER_DETERMINISTIC=0` disables). `_route_hits` is pure and runs **before** the embed step; a hit leads the menu at 1.0, drops the retrieved twin from the tail, bypasses getaway and the intent gate, and survives an embed/Qdrant timeout (the fallback mandate carries it). `config/deterministic-routes.json` is seeded with the eleven replayed misses. Curation rule unchanged: literal names, slash forms, replayed aliases only.
3. **Timeout defaults 0.35 → 0.5 s (embed) and 0.10 → 0.25 s (Qdrant).** Worst path ≈ 1.75 s inside the 5 s hook budget. Revert: `ENFORCER_EMBED_TIMEOUT=0.35 ENFORCER_QDRANT_TIMEOUT=0.1`.
4. **Keep-off activated.** The generated map moves to the durable home `~/.claude/skill-concierge/keep-off.json` (the keep-on/blocklist pattern; a plugin update cannot wipe it); the shipped `config/keep-off.json` is the empty seed. The generator excludes harness-shaped offers, exempts keep-on members (the operator's explicit always-on choice; the ledger cannot see inline USING takes — the v0.46.0 backtest with the harness filter alone would have dropped exactly one skill, `vn-doc-complete`, taken 3× inline), defaults its window to the v0.47.0 epoch (`KEEPOFF_SINCE`), and is wired into `doctor` (`Keep-off` check, `--fix` regenerates). ADR-0011's data-sufficiency guard keeps it inert until ≥40 clean offered turns exist.
5. **`dsh-personal` and `cline-personal` are foreign to every other harness** (every tuple in `_foreign_scopes`, compound labels), so the existing foreign-drop + `_invocable_twin` path handles them. The foreign annex additionally skips a row whose bare name is already in the installed offer — listing it as "NOT invocable" would state the opposite of the truth.
6. **`analyze.py` counts only outage values** (`embed_timeout`, `embed_down`, `qdrant_down`) on the fallback line; the conversational, refusal and harness legs report through the band histogram.
7. **Operator config, not code:** seven daily-used name-only skills join the always-on list; `ENFORCER_ANNEX_MARGIN=0.0` is set as a Claude-side trial (271 annexed offers, 2 pulls, median foreign row 0.03 below the installed top; revert = delete the env line).

Deferred by design (R9): ROUTE projection and multi-intent stay ON until ≥30 human-prompt projections exist under this epoch.

## Consequences

- Offer composition changes again: previews fall by roughly the harness share (~29 % of all offers), chronic-zero lists collapse, ROUTE/multi-intent become measurable on clean turns. **New epoch — see `docs/epoch-watch.md` v0.47.0.**
- The audit script's false-SKIPPING accounting gains a fourth authorized signature; older audits are unaffected.
- A named skill that is also blocklisted or keep-off'd still never surfaces (suppression outranks a route — pinned by selftests 6b and 6c), and under a harness where `personal` is foreign (Command Code, DSH, Cline, divergent ZCode) a bare route target must pass the invocable-twin test or the route stays inert (ADR-0034 invariant, selftest 6c).
- The harness regex ships with four ledger-evidenced shapes (`<task-notification>` 1,700 rows, OMP `omp-msum` 1,546, `<system-reminder>` 36, `<cross-session-message` 20 over the whole ledger) plus transcript-evidenced shapes the hook has not yet seen at the prompt head; `<command-name>` was dropped as dead surface (slash commands reach the hook raw and are pre-gated). `tests/test_harness_regex_parity.py` pins the generator's mirror byte-identical.
- `doctor --fix` re-runs the keep-off generator on every pass (`REFRESH_FIXERS`), and `setup.sh` builds the map at install, so the durable map refreshes as the window grows without a manual generator run.
- `keep-off.json` in the repo stays empty forever; a `doctor --fix` in a checkout writes to the durable home, never to the tree.
- Kill-switches, each a one-var revert: `ENFORCER_HARNESS_SKIP=0`, `ENFORCER_DETERMINISTIC=0`, the two timeout vars, `SKILL_CONCIERGE_KEEPOFF=<repo config path>` (or an empty durable map), and deleting the annex-margin line.
