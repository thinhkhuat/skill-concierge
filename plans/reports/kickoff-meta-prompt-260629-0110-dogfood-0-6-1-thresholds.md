# Session kickoff — skill-concierge · dogfood-0.6.1-gate-thresholds

You are resuming work on the `skill-concierge` project after a clean session-handoff. Context is fully recoverable from disk — read these files IN THIS ORDER before responding:

1. `docs/adr/0009-operator-set-gate-thresholds.md` — what just changed (word floor 2→5, score floor 0.40→0.45), why, the evidence that argued against it, and the one-line revert.
2. `hooks/scripts/enforcer.py` — the gate under test: pre-gate (`MAX_SHORT_WORDS`), `GETAWAY_FLOOR`, imperative-veto, intent gate; the bands getaway/offer/intent_skip/fallback/negation.
3. `scripts/analyze.py` — the ledger analyzer; `offered-turn conversion` is the decisive metric (supports `--since`/`--until`).
4. `CHANGELOG.md` (the `[0.6.1]` entry) — release framing.
5. `.handoff/handoff-2026-06-29-0020-actionability-gate-shipped-v060.md` — the broader arc + the three architectural escalations (substrate measures topic, not usefulness).
6. `docs/journals/journal-2026-06-29-0020-actionability-gate-shipped-v060.md` — technical narrative + the post-ship dogfood findings.
7. `scripts/build_prompt_intent.py` — the corpus miner (use `mine()` for word-count-by-class checks; read-only, no embed).
8. `plans/reports/verify-260629-0107-skill-concierge-0-6-1-gate-thresholds-live-raw-evidence.md` — the live-verification raw evidence at ship (if present).

After reading, do NOT change any threshold and do NOT write a plan file yet. Your first response is a **diff-and-propose checkpoint** only.

## The task

Independently dogfood the just-shipped 0.6.1 gate-threshold change on the LIVE plugin. Reach your OWN data-backed verdict — **replicate or falsify** the pre-ship prediction (ADR-0009) that both knobs hurt — and recommend keep / revert / adjust. Do not trust the prior conclusion; prove it from the live ledger and from driving the real gate.

## What the user already knows (don't re-explain)

- 0.6.1 shipped (commit `6995fd8`), pushed, `/plugin update` + `/reload-plugins` done → the gate is live.
- The two knobs and their old→new values; both are OPERATOR-SET against a data-backed recommendation (ADR-0009 records the override).
- The enforcer is an additive, FAIL-OPEN UserPromptSubmit hook; a suppressed offer withholds a nudge, it never blocks work.
- The core finding: cosine score is anti-correlated with adoption here (taken offers score LOWER than dodged); the substrate measures topic, not usefulness.
- Live ledger: `~/.claude/skill-telemetry/logs/skill-invocation-ledger.log`; the gate executes from the plugin CACHE copy, not the dev tree.

## Known pain points / status (from prior session + analysis)

- The word floor runs BEFORE the imperative-veto → short imperatives ("update the handoff", "fix the parser bug") now get pre-gated (predicted false-suppression).
- ~93% of conversational noise is >5 words → the word floor can't reach most noise.
- Score floor 0.45 was predicted to cut the better-converting offers first (taken median top 0.414 < dodged 0.457).
- The `intent_skip` band may stay near-empty (the floor gets there first) — a near-empty band is NOT gate failure.
- Small sample (~10 taken offers historically) — trust direction over magnitude.

## Your first response must do these things, in this order

### 1. Context-loaded proof
A one-line-per-file table of what each file told you.

### 2. Establish the live operating point + baseline (raw bytes, not verdicts)
- Confirm the ACTIVE enforcer is 0.6.1 carrying `MAX_SHORT_WORDS = 5` / `GETAWAY_FLOOR 0.45` (grep the cache copy; prove which version is active).
- Measure the current ledger: band distribution + offered-turn conversion via `analyze.py`. Split on the ship time (commit `6995fd8`) with `--since`/`--until` to compare the pre (0.40/2) window vs the post (0.45/5) window. Paste numbers.

### 3. Propose 4–6 scoping questions (trade-off + your recommendation)
- **measurement mode** — natural-usage accrual vs actively driving the gate with a prompt battery? (recommend BOTH — drive now for signal, accrue for truth)
- **A/B baseline** — re-run the threshold probe at live 0.45/5 vs the data-backed 0.40/2 side by side? (recommend yes)
- **window** — how much usage to accrue before a keep/revert call? (recommend a minimum offered-turn count)
- **verdict criterion** — what number flips keep→revert? (recommend: a drop in surviving-offer take-rate)
- **ledger hygiene** — drive the gate via a temp `SKILL_CONCIERGE_LOG` so the real ledger stays clean? (recommend always)

### 4. Explicitly close with "I am NOT changing any threshold or reverting ADR-0009 until you answer the above."

## Constraints on any future work in this thread

- Don't touch `~/.claude/plugins/**` (the cache is upstream-managed).
- Writes into `skill-concierge` are hook-blocked → use bash/python (heredoc / `Path.write_text`), never the Write tool.
- Never pollute the live ledger when driving the gate → redirect `SKILL_CONCIERGE_LOG` to a temp dir; do NOT set `ENFORCER_GETAWAY_FLOOR` (test the file's 0.45 default).
- `git` and `/plugin` ops are user-run only; no version bump / no revert without explicit approval. To revert, supersede with ADR-0010 — never edit the immutable ADR-0009.
- Verified over asserted: every "helps/hurts" claim cites ledger bytes.

Begin.
