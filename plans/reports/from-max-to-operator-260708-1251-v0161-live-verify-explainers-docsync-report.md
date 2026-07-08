# v0.16.1 — Live verify, explainers, doc sync, OpenWiki refresh (for the operator)

**When:** 2026-07-08 ~12:51 · **Version:** 0.16.1 (live) · **Author:** MAX
**Scope:** the 5 asks handed off before lunch. Decisions made on your behalf are flagged **[DECISION]**.

---

## 1. Live code path — corrected and verified

You were right: the live, in-use plugin code is the **versioned cache dir**, not the `marketplaces/` copy I mistakenly probed last turn.

- **Live path:** `~/.claude/plugins/cache/skill-concierge/skill-concierge/0.16.1/` — verified present, version `0.16.1`.
- Its `bin/skill-search-mcp` (what `.mcp.json` launches) was rewritten today at 12:36 by the `/plugin update`.
- The stable engine venv stamp (`~/.claude/skill-concierge/venv/.engine-plugin-version`) = **`0.16.1`** → engine is fresh, matches the live cache.
- Both durability legs present in that live copy: `.mcp.json` → `SKILL_LLM_TRIGGERS=1, TRIGGERS_MAX=16`; `hooks/scripts/auto_reindex.py` → the whitelist fix is there.

I recorded this as a permanent gotcha in `docs/caveats.md §13` (three copies exist — repo working copy you edit, `marketplaces/` = registration checkout, `cache/<version>/` = what actually runs). The `marketplaces/` path is never the live code.

---

## 2. What "Corpus health 12/14 ok · 1 weak · 1 no-signal" means

Grounded in `scripts/doctor.py:449` (`check_corpus_health`) and `scripts/calibrate_thresholds.py`.

**Short version: it is not a problem. It's a small advisory diagnostic, and status stayed OK.**

- There's an optional per-skill calibration file (`eval/thresholds.json`) produced by `calibrate_thresholds.py`. For each skill it measures whether that skill's own *positive* example prompts out-score its *near-miss negative* prompts in cosine similarity (the "separation"). It buckets each skill:
  - **ok** — positives clearly beat negatives (separation ≥ 0.05): a trustworthy per-skill cutoff exists.
  - **weak** — positives lead, but by less than 0.05: a cutoff exists but is fragile.
  - **no-signal** — positives do *not* beat negatives (flat or inverted): **no threshold can ever fix it.**
- So "12/14 ok · 1 weak · 1 no-signal" = of the **14 skills** in this small legacy calibration set, 12 separate cleanly, 1 is borderline, 1 has no usable signal.
- **Why doctor still says OK:** the check only WARNs if *zero* skills are ok. weak/no-signal are surfaced as a visible **to-improve list**, not a failure. The doctor line literally says the lever is *index content (richer/multi-vector) or better contrastive negatives — not a threshold.* Our new utterance layer is exactly that kind of "richer index" lever.
- **Two things to keep in perspective:** (a) this 14-skill calibration corpus is separate from the 532-skill flywheel eval corpus — it's a tiny legacy set; (b) per-skill thresholds aren't even active in production (they're diagnostic only). So the 1 weak + 1 no-signal are informational, costing nothing today.

**Bottom line:** healthy. It's the system honestly naming 2 skills whose retrieval signal could be strengthened later; no action required.

---

## 3. How the index stays in sync when you add / remove skills (autonomous)

Grounded in `vendor/skill-search/skill_search/server.py` (reindex + staleness) and `hooks/scripts/auto_reindex.py`. Three cooperating mechanisms — you never run anything by hand:

1. **Incremental reindex (content-hash diff).** Every indexed point stores a hash of the exact text it embedded. A reindex computes the desired end-state (every skill's base + trigger points) and compares:
   - **Add a skill** → only its points get embedded and added.
   - **Remove a skill** → its points are *deleted* (`removed = points that exist but are no longer desired`).
   - **Edit a skill** → only that skill re-embeds; everything unchanged is skipped.
   Cheap, and it only ever touches what changed.
2. **Self-healing on session start.** `auto_reindex.py` fires that incremental reindex **automatically** on every new Claude Code session — detached (non-blocking), and throttled to at most once per 30 minutes so rapid restarts don't churn. So after you add/remove a skill, the next session reconciles the index for you.
3. **Drift detector (in-band warning).** The index stores a *content signature* of what's on disk (ADR-0024). Every `search_skills` compares the live disk signature to that manifest; if they differ it returns a "disk changed since last index" warning *inside the results*, so a stale index is never silent while the auto-reindex catches up. It's content-based, so a `/plugin update` or re-clone that doesn't change skill text won't false-alarm.

The utterance layer rides along for free: utterance trigger points carry their own content hashes and per-(skill, slot) IDs, so incremental reindex adds/removes them exactly like any other point.

**Two honest caveats (worth knowing):**
- A **brand-new** skill has no generated utterances yet (the flywheel that writes `eval/triggers.json` runs offline, occasionally). Until then the new skill is still fully indexed and retrievable via its description + body phrases — it just doesn't get the extra utterance boost until the flywheel regenerates. No breakage, just a smaller lift for the newest skills.
- A **removed** skill leaves a stale entry in `eval/triggers.json`; it's harmless (the loader keys by name and ignores unused entries) and gets cleaned on the next flywheel run.

---

## 4. Documentation sync (done)

Refreshed to the 0.16.1 state. Files changed (committed — see end):

- `README.md` — version-history head now leads with **0.16.1** (the auto_reindex env-forwarding fix), 0.16.0 folded below.
- `CLAUDE.md` (repo) — the governance-flags quick-ref now lists all three engine flags incl. `SKILL_LLM_TRIGGERS` (default OFF) and notes v0.16.1's flag-forwarding.
- `AGENTS.md` — the `SKILL_LLM_TRIGGERS` runtime-flag entry notes the v0.16.1 auto_reindex forwarding.
- `docs/caveats.md` — added **§13** (live code = versioned cache path, not `marketplaces/`) and **§14** (a background reindex must receive the engine flags or it reverts them — the v0.16.1 lesson).
- Already current from the 0.16.0 sweep (unchanged this round): CHANGELOG (`[0.16.1]` + `[0.16.0]`), ADR index, `docs/adr/0026-llm-utterance-trigger-layer.md`, README + AGENTS + operations flag tables.

**[DECISION] No version bump for this docs refresh.** A pure documentation sync changes no plugin behavior, so bumping to 0.16.2 (and forcing you into another `/plugin update`) would be ceremony for nothing. Docs are committed/pushed at 0.16.1; a future `/plugin marketplace update` will pull them whenever you next run one. (Consistent with the rule's intent, which targets behavioral changes.)

---

## 5. OpenWiki refresh — done (delegated agent ran `openwiki:wiki` update)

The agent ran the `openwiki:wiki` skill in **update** mode, following its procedure (read prior metadata → git evidence → snapshot → surgical docs-impact edits → write metadata).

**Key finding:** the wiki *content* was already 0.16.0-current from the earlier sweep (commit `ee20e2e`) — ADR-0026, `SKILL_LLM_TRIGGERS`, `TRIGGERS_MAX` were already documented — but its `.last-update.json` pointer was stale (still at `984ff78`). The real gaps were the **0.16.1 delta** and the two requested caveats.

**Files updated (all under `openwiki/`):**
- `quickstart.md` — version header `0.16.0` → **`0.16.1`**.
- `operations.md` — stale-engine "current" bumped to `v0.16.1`; added an **utterance-layer deploy caveat** (`.mcp.json` ships the flags, but the ~733 KB gitignored `eval/triggers.json` corpus isn't in the repo and its `SKILL_TRIGGERS` path is machine-local in settings.json env; plus the v0.16.1 `auto_reindex._mcp_env()` forwarding fix).
- `architecture/retrieval-engine.md` — v0.16.1 link at the auto_reindex mention; added the **`enrich_index.py` is STALE for the multi-vector index — do not use** warning.
- `.last-update.json` — rewritten to `gitHead a2c3b22`, `updatedAt 2026-07-08T05:56Z`, `model claude-opus-4-8`.

Verified against source (ADR-0026 numbers, the `_mcp_env` whitelist at `auto_reindex.py:53-54`, `.mcp.json`, the gitignored 750,995-byte corpus, ADR index through 0026, `plugin.json` 0.16.1). All intra-wiki links resolve; header reads 0.16.1.

**[DECISION] Accepted one procedural deviation, flagged transparently:** the agent did not create the skill's ephemeral `openwiki/_plan.md` scratch file (which the skill deletes before finishing anyway) — it ran the impact plan inline for a small surgical update. Net on-disk result is identical; the deliverable (updated pages + metadata, all source-verified) is complete. I judged this immaterial and did not re-run.

---

## Decisions made on your behalf
- **[DECISION]** Docs-only refresh shipped without a version bump (rationale in §4).
- **[DECISION]** Did not touch `openwiki/` directly — delegated it to the subagent per your "fanout a team" instruction, to avoid two writers colliding.

## Open questions / for your call
- None blocking. Optional: run the flywheel (`scripts/llm_triggers.py`) periodically so newly-added skills pick up utterances (§3 caveat) — a nicety, not a fix.
