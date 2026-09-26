# ADR-0061 — The Jev skill router: Jev ranks the whole catalogue, calibrated on real outcomes

Status: Accepted (2026-09-26)
Supersedes: ADR-0060 (the Jev needs-a-skill yes/no leg). Relates to: ADR-0001 (index scope), ADR-0015
(authorized-skip tier), ADR-0034/0059 (invocability filters), ADR-0054 (lanes, deterministic routes).
Evidence: `plans/260926-0225-jev-gate-zero-prompt-calibration/plan.md`; reviews in `plans/reports/`
(`validator-260926-0232-*`, `overeng-audit-260926-0232-*`, `validator-260926-0310-*`); vendor research
`researcher-260926-0252-jev-docs-exhaustive.md`, `researcher-260926-0252-jev-integration-patterns.md`.

## Context

ADR-0060 asked Jev one yes/no question on the prompt alone ("should the agent load a specialized
playbook?") and pre-authorized a skip below p = 0.25. Wording and threshold came from 22 hand-labelled
prompts that were never saved. The owner ordered that figure taken to zero: no hand-written prompt set as
the rationale for any decision.

Replaying real traffic settled it. A corpus of real turns (`scripts/extract_turn_labels.py`) labels a
turn "needed a skill" when the agent loaded and used a skill in that same turn. On 431 such English and
Vietnamese turns the ADR-0060 gate scored 206 (47.8 %) below 0.25 — "commit now pls", "write the
session-handoff pls" — and a live-format re-check matched (21/40). The v0.50.0 gate skipped about half
of the turns it existed to protect.

The same corpus showed where Jev's value actually is. TypeSafe's own skill-suggestion recipe
(`docs.typesafe.ai/cookbooks/skill_suggestion.md`) uses Jev to *rank* a roster and re-check a
shortlist, and hands the agent a soft hint. Measured on 313 English positives whose used skill is still
installed (237) plus 300 traffic turns — interactive sessions outside skill-concierge's own dev sessions, turns
that reach the gate — replayed on the
live catalogue (the enforcer's own `_jev_catalog`, 475-494 skills depending on the session's cwd) with the
live question builders and the live `_jev_decide`:

| | today's embedding menu (8 rows) | Jev router (5 rows) |
|---|---|---|
| offer contains the skill the agent used | 86/237 (36 %) | 177/237 (75 %) |
| real skill turns wrongly skipped | — | 1/313 (1/105 on the Sept holdout) |
| traffic skipped | — | 6/297 (2.0 %) |

## Decision

1. **Lane.** After every no-I/O lane (short, harness, refusal, consult, self-recap, named route) and only
   for **English** prompts (fewer than two non-ASCII letters — the calibration population's rule) with
   `TYPESAFE_API_KEY` set. Owner order 2026-09-26: English end to end first; Jev's primary training
   language is English (`docs.typesafe.ai/concepts/state.md`). Everything else takes the embedding path,
   unchanged.
2. **State.** `request`, `recent_context` (tail of the last assistant message) and
   `skills_already_loaded_this_session` (last 3), read from the hook payload's `transcript_path` by a
   bounded tail read. This is exactly the state the replay measured.
3. **Call 1 — wide.** The invocable catalogue (every installed skill's `kind=base` point, through the
   same per-row test `_retrieve` applies — `_row_invocable` — plus keep-off and the blocklist) as
   ≤ 250-option Choice chunks in one request; the top 5 of each chunk form the shortlist.
4. **Call 2 — rerank.** One request over the shortlist: a Choice plus one `fits` Noul per candidate
   (cookbook wording, verbatim).
5. **Decide** (`_jev_decide`, pure). Best `fits` < `ENFORCER_JEV_FITS_FLOOR` (0.30, the vendor default; the
   time-holdout fit on our data picked 0.34) → authorized skip, band `jev_skip`; the locked signature "Jev needs-a-skill
   gate" is unchanged, so the audit contract is too. Otherwise the offer is the rerank Choice's top
   `JEV_OFFER_ROWS` (5) in its order, rendered by the existing `_ranked_mandate`. A single "confident"
   lead was measured and rejected: at confidence cut-offs 0.70/0.90/0.95 it lowered recall to 62-65 %.
   **This re-opens ADR-0009's operator-set getaway floor and ADR-0015's intent skip for English turns
   only.** Measured on the same 313 English skill turns: the embedding gates wrongly skip 24 (7.7 %; 23 by
   the intent skip, 1 by the getaway floor) against Jev's 1 (0.3 %); on traffic they skip 14.3 % against
   Jev's 2.0 %. Non-English turns and any Jev failure keep both gates exactly as before. **Owner
   approved 2026-09-26 09:45 +07** (Thinh: "approved and now pls implement").
6. **Concurrency and fallback.** The router runs in a worker thread started before the embed step and is
   joined after retrieval (hard cap `ENFORCER_JEV_BUDGET`, 3.0 s from start). Any failure, a malformed
   answer or a blown budget → the embedding path decides, with `jev.err` logged. If embed or Qdrant is
   down, a Jev verdict still serves the turn. Named routes never ask Jev.
7. **Warm connection.** Both calls go through the embed shim's `POST /jev` relay, which keeps a pool of
   warm HTTPS connections to `api.typesafe.ai` (fixed host and path; the caller's key is forwarded, never
   stored; loopback shim hosts only, since the key rides that hop in clear text; a stale pooled connection
   is retried once on a fresh one, a timeout never). A fresh connection costs ~500-700 ms per call from the reference Mac; measured end to end the
   hook takes ~0.8-1.0 s warm vs ~1.6-2.0 s cold. A shim without the route (404) or not listening → one
   direct call. `setup.sh` rebuilds a shim whose `/health` does not list `jev`.
8. **Telemetry.** Every ledger row after an attempted route carries `jev`: `{ms, wide_ms, conf, fit,
   via, n, ctx, lead}` or `{err, ms}`.
9. **Calibration tooling, kept.** `scripts/calibrate_jev_gate.py` (replay / curve / fit with a time
   holdout / rank / wide / policy) uses the enforcer's own question builders and `_jev_decide`, so a
   replayed decision is the live decision. Its corpus holds verbatim prompts and lives under
   `~/.claude/skill-concierge/jev-calibration/` (mode 700/600), never in this public repo.

Rejected: automatic live recalibration (the gate would learn from the labels it suppresses and drift
toward skipping more); hierarchical beam search (two chunked Choice questions already reach the whole
catalogue in one call); per-prompt yes/no gating of any wording (four wordings replayed; none separated
real skill turns from traffic at a safe error rate).

## Consequences

- The menu changes character: Jev-ordered, at most 5 rows, and about twice as likely to contain the skill
  the agent ends up using. Offer-level ledger rates (take, hit@k) start a new epoch.
- The skip leg fires rarely (2.0 % of English traffic in the replay). Conversation still gets a menu most of the time —
  Jev's value is choosing, not suppressing.
- Every English prompt that reaches the gate sends its text (≤ 4 000 chars), the last assistant message
  tail (≤ 1 500 chars) and the catalogue names/descriptions to `api.typesafe.ai`. Cost ≈ 25-30k input
  tokens per turn (~$0.001).
- Latency: ~0.8-1.0 s warm, overlapped with the embed/Qdrant legs; worst case bounded by the 3.0 s join.
- Vietnamese and other languages keep the embedding path until English is proven end to end.
- The router also runs on English turns the calibration did not sample: SDK / `claude -p` sessions and
  skill-concierge's own dev sessions. Their offer quality is unmeasured (epoch-watch W22 should slice
  them apart), and each such turn costs two metered calls. Owner decision 2026-09-26: keep all English
  turns in scope and measure them after ship.
- Built-in Claude Code skills (ADR-0001: not indexed) cannot be offered by Jev either.

## Revert

`ENFORCER_JEV_ROUTER=0` (or the ADR-0060 `ENFORCER_JEV_GATE=0`) restores the pre-v0.50.0 embedding-only
path byte-identically: no Jev call, no `jev` field.
