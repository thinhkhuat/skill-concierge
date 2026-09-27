# ADR-0074 — Findability is a ratcheted invariant; the retrieval fixes ship off until the keyword channel joins them

Status: Accepted (2026-09-27)
Evidence: `plans/reports/diagnose-260927-1430-new-skill-loses-to-external-catalog.md` (the incident),
`plans/260927-1450-findability-at-the-root/design.md` (v4.1, the design and its reviews),
`plans/260927-1450-findability-at-the-root/build/integration.md` (four evidence rounds),
`plans/reports/judgment-260927-1655-findability-conditional-external-rule.md` (the release-shape call).

## Context

**The incident.** A new installed skill, `tk-gdelt-doctor`, ranked below unrelated external-catalog
skills for queries that named it. A per-skill curated phrase list fixed that one skill. Thinh
rejected it as a symptom cure: the class had to be fixed at the system level.

**The class is system-wide.** A live sweep probed each of 149 Claude-invocable installed skills with
the most distinctive word in its own name. 113 of them are not in the top 3 of `search_skills` for
that word. Nothing reported this. The flywheel's "coverage" counts whether a skill has phrases, not
whether the skill can be found.

**The causes, measured:**
- Retrieval is dense-only. A rare name word embeds close to many unrelated things, and nothing
  matches it as a keyword. This is the dominant cause.
- External catalogs are ~72 % of indexed names and compete for the same slots in `search_skills`.
- "Not for …" sentences in a description are indexed as positive trigger phrases.
- A list-form `when_to_use` is embedded as one diluted phrase. Only 4 installed skills declare one.
- No check measures findability, so a regression or an unfindable new skill stays silent.

**Thinh's decisions (2026-09-27, AskUserQuestion):**
1. detect with a name-word probe;
2. judge precision with a bounded, audited bar: violations ≤ 1 % of the negatives AND ≤ one-third of
   the recall gains, every violation listed;
3. ship the keyword channel on the name-word gate, re-judged on fresh turns at n ≥ 150;
4. rank externals below the installed top in `search_skills`.

## Decision

1. **Findability is measured, and it only ratchets up.**
   - `vendor/skill-search/skill_search/findability.py` runs two read-only probes against the local
     index owner:
     - the name-word rank, in the `search_skills` shape;
     - the own-phrase leave-one-out score, in the enforcer's installed-only shape.
   - Results go to `~/.claude/skill-concierge/findability.json` (`SKILL_FINDABILITY_PATH`).
   - The first sweep seeds the baseline and warns about nothing. After that the sweep warns in two
     cases:
     - a new skill is not in the top 3 for its own name word;
     - a known skill regresses: it leaves the top 3, or its own-phrase score falls by ≥ 0.25 to below
       0.5.
   - `--accept <skill>` resets one skill's baseline.
2. **The sweep runs by itself after an index-changing reindex.**
   - At the end of `build_index`, when points were embedded or deleted, the engine launches
     `python -m skill_search.findability --sweep`: detached, from `~`, pinned to the Claude view.
   - It is throttled to one sweep per 10 minutes. It exits quietly when the owner is unreachable.
   - `SKILL_FINDABILITY=0` disables the hook. The flag is not index-shaping, so it stays out of
     `ENGINE_ENV_KEYS`.
3. **doctor shows the result.** A read-only "Findability" row reads the JSON: WARN on any warning,
   OK with the backlog count otherwise. It never sweeps and never calls the owner.
4. **The pre-registered harness is part of the repo.** `scripts/precision_eval.py --mode findability`
   runs five sets, base vs candidate, and prints every lost case:
   - W, name words;
   - C, real turns;
   - D, real search queries;
   - N, the precision negatives from `eval/scenarios-shadow/` (`SKILL_SCENARIOS_SHADOW_DIR`);
   - G, the GDELT name queries.
5. **Three retrieval fixes are built, tested, and ship OFF.**
   - `SKILL_DECLARED_TRIGGERS` (default 0) covers two fixes:
     - drop exclusion sentences from the trigger phrases;
     - split a guarded list-form `when_to_use` into declared phrases.
   - `SKILL_SEARCH_COMPLEMENT` (default 0): installed rows rank ahead of an external row within
     0.08 of it.
   - Why they ship off: they failed the precision bar in the release evidence.
     - The external rule caused 129 of 131 violations.
     - Without it, the other two fixes lifted the name-word top 3 from only 35 to 36. That left
       2 violations against a bound of 1.
   - v0.56.0 judges all three together with the keyword channel. The v4 review measured that
     channel alone at 59 → 118 name-word top-3 hits, which gives the gain-relative clause a real base.
   - `=1` plus a reindex turns each fix on for local evaluation.
6. **Tests stay hermetic.** The vendored conftest sets `SKILL_FINDABILITY=0`. The end-to-end indexing
   test no longer reads the live `~/.claude` skill tree, which made it flaky while other sessions
   edited skills.

## Consequences

- **The index is byte-identical to v0.54.1 at the shipped defaults.**
  - Both staging owners embedded 0 points.
  - A sorted SHA-256 over all 44,602 points matched, and so did the raw file MD5.
  - The live owner was never written.
- **Search results do not change in this release.** What changes is that the system now reports
  the class it used to hide.
- **The epoch window restarts at the go-live commit.** `server.py` changed, and the epoch rule keys
  on that file. Ranking is identical, so any shift across the boundary is environmental, not a
  design effect.
- **Sweep cost.** The first live sweep took ~86 s of detached CPU, not the design's ~22 s estimate.
  The 10-minute throttle bounds how often that happens.
- **The curated `tk-gdelt-doctor` phrases stay live** as a labelled temporary guard. They retire
  only when v0.56.0's G bar passes without them.
- **Known approximation.** The own-phrase probe filters competing rows by `tier != external`, not by
  a full per-row invocability re-check. The module docstring discloses this.

## Reverts

- `SKILL_FINDABILITY=0`: no sweep after a reindex. The doctor row then reports the last file, or
  "not yet swept".
- The two retrieval flags are already off. Unsetting them is the revert.
- No ADR is superseded. The design's ADR-0075 (externals ranked below the installed top in
  `search_skills`) is not written: that rule failed its bar. It returns, if at all, with v0.56.0's
  evidence.
