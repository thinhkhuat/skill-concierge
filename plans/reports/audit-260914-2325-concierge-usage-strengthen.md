# Concierge usage audit — where to strengthen daily usefulness

Date: 2026-09-14 23:25 (+0700) · Author: session audit · Status: REVIEWED — two independent verdicts applied (see *Review verdict*)

## Epoch

- Window: **2026-09-06 03:06 → 2026-09-14 23:26** (+0700). Start = last commit touching `hooks/scripts/enforcer.py` (`225ea25`, the v0.46.0 banner; behaviour change `1081a3b` at 02:58 the same night).
- Ledger rows in window: 1,437 of 9,886. Organic after exclusions: 1,382 rows, 79 sessions, 581 enforcer decisions.
- Excluded: 51 subagent rows (`sub: true`), 4 rows from this session, every transcript under the skill-concierge project.
- Harness mix of enforcer decisions: claude 465 · omp 100 · codex 14 · zcode 2.
- Nothing pooled across epochs. Numbers below are this window only. Pre-window rates are not cited.

## Method

| Source | Used for | Script |
|---|---|---|
| `~/.claude/skill-concierge/logs/skill-invocation-ledger.log` | gate mechanics: bands, fallback causes, offer composition, hit@k, timeouts, annex deltas | `scripts/analyze.py --since …`, `/tmp/sc_audit/ledger_deep.py`, `/tmp/sc_audit/ledger_deep2.py` |
| `~/.claude/projects/**/*.jsonl` (Claude Code only; 42 organic files) | the SKILL-FIRST declaration trail on human prompts, false-SKIPPING, silent turns | `/tmp/sc_audit/trail2.py` |
| `scripts/build_keep_off.py --out /tmp/…` | keep-off backtest (never wrote live config) | dry-run |
| `scripts/doctor.py` | deployment state | read-only |

Deviations from the skill's stated procedure, stated plainly:

- The shipped `skills/skill-usage-audit/scripts/audit_skill_usage.py` was not run. It has no harness-message filter and no ledger-band join, both of which this analysis needed. Its false-SKIPPING rule (SKIPPING with no same-turn `search_skills`, minus hook-authorized skips) was reproduced; authorization was taken from the ledger band (`intent_skip`/`getaway`/`negation`) instead of the `SKILL-CHECK:` marker, because the marker lives in `hook_additional_context` attachments, not in the user message.
- OMP, Codex and ZCode transcripts were not parsed. Their behaviour is visible only through the ledger.
- "Human prompt" = a user record that does not open with `<task-notification>`, `<system-reminder>`, `<cross-session-message`, `<teammate-message`, `Another Claude session sent`, `[Request interrupted`, `This session is being continued`, `<local-command`, `<command-name>`, or an OMP `<file name="…omp-msum-…">` summary wrapper.

## Findings

Ranked by how much they cost you on an ordinary day.

### F1 — 59% of what the enforcer scores is harness-generated text, and 168 full previews were injected into it

- 344 of 581 enforcer decisions were on non-human prompts. 168 of those got a **full preview** (`band=offer`): 89 `<task-notification>`, 65 OMP `omp-msum` summary calls, 9 cross-session messages, 5 idle `<system-reminder>` nags. Split: claude 98, omp 70.
- Only 7 skill takes followed any of those 168 previews, and each was a take the agent would have made anyway (journal/handoff after a monitor event).
- The enforcer has **no shape check** for these prompts: `grep -n 'task-notification\|system-reminder\|teammate' hooks/scripts/enforcer.py` returns nothing. Every one of them pays the embed + Qdrant + intent + annex round trip (`hooks/scripts/enforcer.py:1843-1912`).
- Cost per injected preview ≈ 2,021 chars (~500 tokens), measured by the author from 82 preview-bearing `UserPromptSubmit` attachments in a 15-transcript sample (not independently re-derived by review; treat as an order of magnitude).
- Knock-on damage: these turns are what fill the top-3 slots with never-taken skills (F3), fire 14 of the 19 ROUTE projections (F6), and inflate every ledger rate you read.

### F2 — On human prompts the doctrine is working; the ledger's "14% uptake" is a measurement artefact

Claude Code transcripts, 195 human prompts, line-1 token:

| Token | Count | Share |
|---|---|---|
| USING | 110 | 56% |
| SEARCH | 23 | 12% |
| SKIPPING | 21 | 11% |
| SILENT (no token) | 39 | 20% |
| SILENT but Skill tool fired | 2 | 1% |

- The ledger sees only Skill-tool invocations. Of the 110 USING turns, **64 (58%)** are inline reads of a SKILL.md that never touch the Skill tool, so `analyze.py`'s "uptake 14%" undercounts real usage by ~4×. This is the known blind spot the audit skill warns about; it is now quantified for this epoch.
- false-SKIPPING (no search, no authorized band): **16 of 195 human prompts (8%)**. Examples are short follow-ups ("continue pls", "in plain words", "revert pls").
- SILENT on an offered human turn: 17 of 112. Several were the user naming a skill in prose ("consider the ui-ux-pro-max skill", "one option should be the /liquid-glass-design") and the agent acting without declaring.
- Offered-turn conversion on human prompts, by harness (gate compliance, not usage): omp 9/22 (41%), claude **15/148 (10%)**, codex 0/9, zcode 0/2. (Claude figure corrected by review: the first pass used a fixed 5-event lookahead that could credit a take to an earlier offer; the join now stops at the next offer.)

### F3 — The top-3 slots are owned by skills nobody takes, and the layer built to fix that has been inert since June

- Chronic-zero in this window (offered ≥15, taken 0): 42 skills. Worst: `horizon-notify` 201 offers / 155 top-3 / 0 takes; `ak-plans-kanban` 101/73/0; `ak-debugging` 93/43/0; `check-work` 89/48/0; `vibe-code-auditor` 81/31/0; `ak-worktree` 75/31/0.
- Slot attribution: `horizon-notify` 0 human-prompt slots vs 46 harness-message slots; `check-work` 0 vs 30; `ak-debugging` 0 vs 23; `ak-plans-kanban` 0 vs 13. These are harness-message artefacts (F1), not retrieval errors.
- ADR-0011 keep-off: `config/keep-off.json` was generated **2026-06-29** and is **empty** (`"keep_off": []`). `hooks/scripts/enforcer.py:795` loads it, so the P5 drop at `:1872` is a no-op. The generator `scripts/build_keep_off.py` is not wired into `doctor --fix` or `setup.sh` (ADR-0011 deferred that trigger "until one real post-enrichment run is eyeballed"; it never was).
- Backtest (dry-run to `/tmp/sc_audit/keep-off-dryrun.json`, 314 organic offered turns, data-sufficient): the generator would drop **32** skills today. Four of them are questionable: under ADR-0011's rule they qualify (offered ≥15, not taken *when offered*), but their offers were dominated by harness-message turns (`ak-project-management` 27 harness vs 1 human top-3 slot; `ak-journal`, `ak-docs` likewise), so the measured take-rate says nothing about human prompts; and `vn-doc-complete` was taken 3× inline via USING, which the ledger cannot see. Regenerating keep-off **before** fixing F1 would drop skills on polluted evidence.

### F4 — When you name the skill, the preview still misses it (11 cases)

Prompt (abridged) → band → what you took:

- "please give a /progress-map of the build…" → `intent_skip` → progress-map
- "run it - end-to-end - /unlazy" → offered create-cli, ak-codex-goal, skill-search → unlazy
- "/cook them --auto with /unlazy pls" → `fallback` (embed timeout) → ak-cook, unlazy
- "cook --auto all phases please, with unlazy" → `fallback` → ak-cook, unlazy
- "run vn-gov-docx to produce a docx copy" → `fallback` → vn-gov-docx
- "please use ego lite browser skills to access this google sheet" → offered google-workspace, 9router-web-fetch, firecrawl-interact → ego-browser
- "…writing the journal & session handoff report" → `fallback` → session-handoff

The deterministic-route scaffold exists (`hooks/scripts/enforcer.py:1135 _deterministic_hits`, prepends at score 1.0, bypasses getaway and the intent gate) but is **default-OFF** (`ENFORCER_DETERMINISTIC` unset) and `config/deterministic-routes.json` has `"routes": []`. Note it runs *after* the embed step, so it cannot rescue a `fallback` turn as written.

### F5 — "Qdrant down" and "embed timeout" are timeout-censoring at the cap, not outages

- 53 `qdrant_down` rows: **every one** has `qdrant_ms` in 101-106 ms against `QDRANT_TIMEOUT_S = 0.1` (`hooks/scripts/enforcer.py:67`). Successful queries (capped rows excluded): p50 38 ms, p90 87 ms. The cap sits 13 ms above the p90 of a normal query.
- 21 `embed_timeout` rows: `embed_ms` 359-381 against `EMBED_TIMEOUT_S = 0.35` (`:66`). Successful embeds (capped rows excluded): p50 151 ms, p90 257 ms, p99 338 ms.
- (Percentiles corrected by review: the first pass left the capped rows inside the "successful" population, which made the cap look closer to the p90 than it is. The load-bearing fact is unchanged: every failure lands exactly at its cap.)
- Together: 74 of 581 decisions (13%) fell to mandate-only. Days 09-10 and 09-14 carried 14 and 23 of them; the 09-14 13h cluster (6 + 5) coincides with the flywheel run. Spread across hours otherwise: intermittent tail latency, not downtime. Doctor reports Qdrant and the embedder healthy.
- The file's own calibration note (`:59-65`) documents a 5 s hook budget and ~850 ms worst path; there is headroom.

### F6 — Continuation layers: chain hints pay, ROUTE projection and multi-intent do not (yet)

- Chain hint (ADR-0029) followed **8/16 (50%)**.
- ROUTE projection (ADR-0041) followed **0/19**; 14 of the 19 fired on `<task-notification>` / `<system-reminder>` / cross-session text (F1). Human-prompt sample is 5. Insufficient to judge the design; sufficient to say it is currently firing on the wrong turns.
- Multi-intent (ADR-0041) ≥2 takes: **0/142** vs single-intent control 3/439 (142 = 581 − 439; the first pass read 143 from a live ledger that had grown by one row between queries). Same contamination caveat.
- Consult-route (ADR-0049 phase 2): **0 rows** in the window. Epoch-watch v0.43.0 W1-W4 have no data.

### F7 — The always-on list and what actually gets used have drifted apart

- 25 of the 42 keep-on skills had **0 takes** in 8 days (`ak-code-review`, `ak-context-engineering`, `ak-design`, `ak-docs-seeker`, `ak-folder-context`, `ak-help`, `ak-orchestrate`, `ak-problem-solving`, `ak-research`, `ak-research-prompt`, `ak-scenario`, `ak-sequential-thinking`, `ak-team`, `ak-test`, `ak-use-mcp`, `architecture-decision-records`, `code-change-verification`, `directional-prompting`, `mnemosyne-ops`, `palate:palate`, `rg_history`, `skill-concierge:skill-search`, `tool-design`, `vibe-code-auditor`, `writing-for-agents`). 8 days is too thin to call any of them dead; noted, not actioned.
- Name-only skills with ≥2 takes: `progress-map` 10, `vn-gov-docx` 6, `ppwr-dossier-intake` 6, `vn-editor` 5, `officecli-xlsx` 4, `consult` 4, `tk-research` 3, `session-handoff` 3, `ego-browser` 2, `vn-canu-reporting` 2. These are your daily skills and the agent only finds them by name.

### F8 — Twin rows from the DSH personal scope waste preview slots

- 27 of 581 offers carried a duplicate bare name; `doctor` 12×, `consult` 3×, `keep-on` 3×, `flywheel` 2×, `catalogs` 2×, `skill-usage-audit` 1×.
- Source (Qdrant scroll): the bare rows are `scope: dsh-personal`, path `~/.ohdsh/skills/<name>/SKILL.md`: the skill-concierge skills re-rooted for DSH, indexed as if they were separate personal skills. The plugin twin (`skill-concierge:doctor`) is the invocable one under Claude.
- Mechanism: under Claude, `_foreign_scopes()` returns only `("codex-plugin", "codex-personal", "commandcode-personal")` (`hooks/scripts/enforcer.py:388`), so `dsh-personal` (and `dsh-project:*`, `cline-*`) rows are never routed through the existing foreign-drop + `_invocable_twin` path (`:1338`, `:617-648`) and land in the main offer as if they were Claude-native. The selftest at `:2573` pins the Claude tuple to `codex-`/`commandcode-` prefixes, so it must move with the fix.

### F9 — The cross-harness annex fires on almost every offer and is pulled almost never

- 271 offers carried an `[other-harness]` annex (513 rows). Delta of the top foreign row vs the installed top: p10 −0.07, p50 −0.03, p90 +0.01; only **5** beat the installed top by ≥0.04. 2 pulls across 52 annexed sessions.
- This session's own preview is an example: `vercel:routing-middleware` and `cloudflare:sandbox-sdk` offered for "analyze concierge usage".
- Attribution (verified after review): these figures come from the ledger's `xh` field and the rows render under the `[codex]` / "Other-harness matches" block (`enforcer.py:1671-1675`), i.e. the **cross-harness** annex governed by `ANNEX_MARGIN` (ADR-0036). The **external-catalog** annex (`ext` field, `[external:…]` render, ADR-0048 beat gate) is a separate line: 36 offers, 0 of 17 annexed sessions took one.

### F10 — `analyze.py` reports a 39% "fallback rate" that is mostly the conversational gate

- `fallback rate : 227/582 39% (mandate-only: embed/qdrant down or slow)` is a truthy test on the `fallback` field (`scripts/analyze.py:596`). It therefore counts the 147 `intent_skip` rows (`fallback = "conversational"`, `hooks/scripts/enforcer.py:1906`) and the 6 `negation` rows (`fallback = "skill_refusal"`, `:1821`) together with the 74 real timeouts: 147 + 74 + 6 = 227. True mandate-only share is 13%. Anyone reading the epoch watch from this line over-diagnoses the shim.

### F11 — Deployment drift (RULES [26])

- Repo HEAD `225ea25` (v0.46.0) is **2 commits ahead of origin/main, unpushed**; one modified report file uncommitted.
- Claude Code runs the **0.45.0** cache (`installed_plugins.json`, lastUpdated 2026-09-05). `diff` of the deployed enforcer vs HEAD is non-empty (ADR-0053 gate text). Doctor: WARN — OMP marketplace catalog v0.45.0, Codex cache v0.45.0, SSOT v0.46.0.
- The handoff of 2026-09-06 records "4 live sessions still run the 0.44.1 engine"; doctor now shows 7 live MCP servers on the current engine build, so that item is resolved.

## Recommendations

Ordered by daily impact per unit of change. Each names its evidence, the mechanism, and the revert.

### R1 — Add a harness-shape gate before the embed step (highest value, small change)

- **Evidence:** F1 (168 previews on non-human text, 7 incidental takes), F3 slot attribution, F6 (14/19 projections on harness text).
- **Mechanism:** in `hooks/scripts/enforcer.py`, after the refusal guard and before `_embed` (~`:1841`), a compiled regex on the prompt head for the shapes listed under *Method*. On match: `_append_offer(sid, "harness_skip", [], "harness_message", prompt)` + `_authorized_skip_inject(...)`, `return 0`. No embed, no Qdrant, no annex, no projection. Stamp the ledger row so `analyze.py` can segment. Pin with a selftest positive control (one prompt per shape, plus one human prompt that must still be offered).
- **Do not gate** OMP worker briefs ("Complete assignment thoroughly: # Target …"): those are orchestrator-authored tasks and converted 41% under omp.
- **Expected effect:** ~−29% enforcer previews, chronic-zero list collapses, ROUTE/multi-intent measured on clean turns, fewer embed/Qdrant calls under load (helps F5).
- **Revert:** `ENFORCER_HARNESS_SKIP=0`.

### R2 — Turn on the existing deterministic routes for the named-skill misses, and run them before embed

- **Evidence:** F4 (11 named-and-missed, 4 of them lost to `fallback` where the current scaffold cannot run).
- **Mechanism (simplified after review):** no new layer. Populate `config/deterministic-routes.json` with the F4 shapes (`/unlazy`, `unlazy` → `unlazy`; `/cook`, `cook --auto`, `/ak-cook` → `ak-cook`; `/progress-map` → `progress-map`; `vn-gov-docx` → `vn-gov-docx`; `ego lite browser`, `ego-browser` → `ego-browser`; `session handoff` → `session-handoff`), set `ENFORCER_DETERMINISTIC=1` in the hook env, and move the `_deterministic_hits` call (`:1882`) ahead of `_embed` (`:1843`) so a timeout cannot lose a hit. The scaffold already leads at 1.0 and bypasses getaway and the intent gate; its header's "curate sparingly" doctrine (`:1107-1112`) is honoured because every entry is a literal skill name or slash form. Grow the file only from replayed ledger misses.
- **Revert:** `ENFORCER_DETERMINISTIC` unset (file becomes inert); or empty `"routes": []`.

### R3 — Widen the two timeouts (env-only, today)

- **Evidence:** F5 (all 53 "down" rows at 101-106 ms; all 21 embed timeouts at 359-381 ms).
- **Mechanism:** in the hook env (`~/.claude/settings.json` `env`, mirrored to the OMP/DSH/Cline shims): `ENFORCER_QDRANT_TIMEOUT=0.25`, `ENFORCER_EMBED_TIMEOUT=0.5`. Worst path grows by ≤300 ms inside the 5 s hook budget. Record as a tuning order (value, date, why, revert) per RULES [71].
- **Expected effect:** 74 mandate-only turns → ~10 over a similar window. Re-measure with `analyze.py --latency --since <deploy>`.
- **Revert:** unset both (defaults 0.1 / 0.35 at `enforcer.py:66-67`).

### R4 — Turn the keep-off layer on, but only after R1, on human-prompt offers

- **Evidence:** F3 (empty since 2026-06-29; dry-run drops 32 incl. 4 wrong).
- **Mechanism:** (1) land R1; (2) make `build_keep_off.py` skip `harness_skip` rows (or rows whose `q` matches the same shapes) so it counts human offers only; (3) run it `--since <R1 deploy time>` once ≥40 human offered turns exist; (4) wire it into `doctor --fix` as ADR-0011 intended. Keep the ADR's guards (min 15 offers, ≤5% take, data-sufficiency).
- **Revert:** write `"keep_off": []` (fail-open by design).

### R5 — Refresh the always-on list from the data

- **Evidence:** F7.
- **Mechanism:** via the `skill-concierge:keep-on` skill, add the name-only daily skills with ≥3 takes: `progress-map`, `vn-gov-docx`, `ppwr-dossier-intake`, `vn-editor`, `officecli-xlsx`, `consult`, `tk-research`, `session-handoff` (8 additions, each ~1-2 description lines per turn). Do **not** demote the 25 zero-take entries yet; revisit after 30 days of clean data.
- **Revert:** `keep-on.py remove <name>`; backups already kept beside the file.

### R6 — Fix the `analyze.py` fallback line and add a harness segment

- **Evidence:** F10.
- **Mechanism:** one-line change at `scripts/analyze.py:596`: count `fallback` only where the value is one of `embed_timeout`, `embed_down`, `qdrant_down` — an allow-list, so `"conversational"` (intent_skip) and `"skill_refusal"` (negation) both fall out. Both bands already appear in the band histogram on the next line. Add `harness_msg` as a band once R1 lands. Update `docs/epoch-watch.md` "How to measure" to say the fallback line is outage-only.
- **Revert:** n/a (reporting only).

### R7 — Collapse DSH-scope twins in the Claude offer

- **Evidence:** F8.
- **Mechanism (simplified after review):** one tuple edit. Add `"dsh-personal"` (plus the `dsh-project:*` and `cline-*` labels the engine emits, confirmed by a live Qdrant scroll) to the Claude branch of `_foreign_scopes()` at `hooks/scripts/enforcer.py:388`, and relax the selftest at `:2573` that pins the tuple to `codex-`/`commandcode-` prefixes. The existing foreign-drop path (`:1338`) and `_invocable_twin` (`:617-648`) then remove the twin from the main offer and re-surface it in the annex if Claude cannot invoke it. No new de-dup logic.
- **Revert:** remove the added scope strings.

### R8 — Cross-harness annex: require a beat, not a near-miss

- **Evidence:** F9 (median −0.03; 5 beats; 2 pulls in 52 sessions).
- **Mechanism:** set `ENFORCER_ANNEX_MARGIN=0.0` (ADR-0036 knob, `enforcer.py:115`; parsed as a float, so `0.0` is honoured, not treated as unset — `:155-157`) so a foreign row must match or beat the installed top. If that proves too blunt, extend the ADR-0048 beat gate (+0.04) to `_retrieve` foreign rows the same way it already applies to externals. Env first; ADR if it sticks. The over-engineering reviewer asked that the annex be re-attributed before touching a knob; done — F9 is the `xh` annex, `ANNEX_MARGIN` is its governing knob.
- **Revert:** unset (0.08).

### R9 — Decide ROUTE projection and multi-intent after R1, not now

- **Evidence:** F6. 5 human-prompt projections is not a verdict.
- **Mechanism:** re-run `analyze.py --continuation --since <R1 deploy>` once ≥30 human-prompt projections exist. If route-follow is still 0, set `ENFORCER_CHAIN_PROJECTION=0`; same test for `ENFORCER_MULTI_INTENT`. Chain hints stay on (50% follow).

### R10 — Ship hygiene (your call, not done here)

- **Evidence:** F11.
- Push the 2 commits; commit or discard the modified report; update Claude Code, Codex and the OMP catalog to 0.46.0 (`/plugin marketplace update` is yours); re-run `doctor` for OK. R1-R2 and R6-R7 are a release; R3, R5, R8 are env/config only and can land tonight.

### Suggested order

1. R3 (env, 5 min) and R5 (keep-on tool, 5 min) — no release.
2. R1 + R2 + R6 in one release, with selftests; then R10.
3. R4 after ≥40 clean human offered turns.
4. R7, R8 with the same release or the next.
5. R9 once clean projection data exists.

## Review verdict

Two fresh-context reviewers, both read-only, both re-derived from the repo and the raw ledger.

**Over-engineering audit** (`plans/reports/review-260914-overengineering-concierge-usage-audit.md`): 8 of 10 recommendations right-sized (R1, R3, R4, R5, R6, R9, R10 KEEP; R6's one-line fix confirmed at `scripts/analyze.py:595`). R2 SIMPLIFY and R7 DROP-the-new-layer: both proposed machinery next to an existing mechanism that already does the job (`_deterministic_hits`/`_ROUTES`; `_foreign_scopes` + `_invocable_twin`). R8: re-verify which annex produced the evidence before touching a knob. **Disposition:** R2 and R7 rewritten as the reviewer's smaller versions (above). R8 attribution verified against the ledger's `xh` field and the `[codex]` render path; the knob stands, the note is recorded in F9.

**Adversarial review** (`plans/reports/review-260914-adversarial-concierge-usage-audit.md`): **PASS-WITH-CORRECTIONS.** All 14 checklist items re-derived from the raw ledger, the 42 transcripts, git, doctor and a live Qdrant scroll; every headline count, every config state and every cited `enforcer.py` line bar one reproduced exactly. Five defects, none overturning a finding: F5 latency percentiles had included the capped rows (corrected above to successful-only); F2 Claude conversion 18/148 was a join-boundary bug (corrected to 15/148); F6 multi-intent denominator 143 → 142 (live-ledger growth between queries); F10/R6 omitted the `negation` band's `skill_refusal` value (corrected in both); one line citation 1871 → 1872. Two figures marked UNVERIFIABLE by the reviewer: the "61 turns" parenthetical (removed — not load-bearing; the 4× undercount is confirmed by a separate path) and the ~2,021-char preview cost (kept, now labelled as an author-only measurement). **Disposition:** all five corrections applied in-text; the reviewer's note that the chain-hint join must look past the next offer (hints are re-injected on non-offer legs, `enforcer.py:1953`) is accepted as the correct method for that one signal.

## Judgement calls made during the audit

- Treated `1081a3b`/`225ea25` (same night) as one epoch boundary.
- Classified OMP `omp-msum` summary calls as harness-generated; classified OMP "Complete assignment thoroughly" worker briefs as human-equivalent tasks.
- Counted a `USING` declaration as usage even when no Skill tool fired (inline SKILL.md reads), per the audit skill's definition.
- Did not run `audit_skill_usage.py`; reproduced its verdict logic (see *Method*).

## Open questions

- Is any consumer relying on offers for `<task-notification>` turns (e.g. a monitor-driven chain that expects `ak-journal` to be surfaced)? The 7 incidental takes suggest not, but only you can confirm.
- Should the OMP `omp-msum` summarizer prompts reach the enforcer at all, or be excluded at the OMP shim (cheaper than gating in Python)?
- Keep-on demotions: what window do you want before a zero-take always-on skill is demoted (30 days suggested)?
- `ak-debugging` (93 offers, 0 takes) vs `ak-debug` (keep-on, 1 take): is `ak-debugging` a stale twin that should be blocklisted outright?
