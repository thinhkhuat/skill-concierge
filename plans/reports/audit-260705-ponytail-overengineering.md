# ponytail-audit — skill-concierge over-engineering scan (2026-07-05)

Scope: over-engineering / complexity only (no correctness/security/perf). Read-only,
findings only, nothing applied. Every finding below cites a file:line actually read.

Ranked biggest-cut-first.

---

1. `yagni:` Three independently-wired, currently-unarmed retrieval knobs sit in the
   per-turn hot path, each fully built (env parsing, loader, apply function, selftest
   coverage) but *by the code's own comments* never armed and with no evidence arming
   would help:
   - per-skill tau — `hooks/scripts/enforcer.py:158-189` (`_load_per_skill_tau`,
     `_floor_for`). Comment at 162-166: "WHY OFF BY DEFAULT (data, 2026-06-30): all 5
     current `ok` skills calibrate to tau < 0.45 (one negative), so arming this LOWERS
     their bar and ADDS the false-offers ADR-0009 tuned against."
   - deterministic routes — `hooks/scripts/enforcer.py:192-233` (`_load_routes`,
     `_deterministic_hits`), backed by `config/deterministic-routes.json:1-4` which
     ships permanently empty (`"routes": []`) — dead config for a feature nobody has
     turned on.
   - P6 runner-up-gap collapse — `hooks/scripts/enforcer.py:236-245`
     (`_apply_dominance`). Comment: "Default OFF — no evidence collapsing improves
     conversion; gap>=1.25 fires only ~5%."
   Replacement: delete all three code paths + their `_selftest` sections (enforcer.py
   lines ~610-661), `scripts/calibrate_thresholds.py` (241 lines, produces the tau
   values that are explicitly "NOT wired into the enforcer"), `doctor.py`'s
   `check_corpus_health` (`scripts/doctor.py:439-465`), and
   `config/deterministic-routes.json` — until a superseding ADR actually arms one of
   these with data behind it. Today this is ~90 lines of always-false conditionals in
   the hottest hook in the repo, plus a 241-line script and a doctor check that exist
   only to feed a decision that has been repeatedly declined.

2. `shrink:` The exact same tiny urllib POST/GET/PUT/DELETE wrapper is hand-rolled
   6 separate times across `scripts/`:
   - `scripts/enrich_index.py:52-63` (`_post`, `_put`)
   - `scripts/build_prompt_intent.py:146-151` (`_post`)
   - `scripts/build_triggers.py:49-53` (`_post`)
   - `scripts/calibrate_thresholds.py:58-62` (`_post`)
   - `scripts/precision_eval.py:39-43` (`_post`)
   - `scripts/multivector_experiment.py:62-86` (`_req`, `_post`, `_put`, `_get`,
     `_delete`)
   Replacement: one shared `scripts/_qdrant_http.py` (10-15 lines: `post`/`put`/`get`/
   `delete` over `urllib.request`) imported by all six. Removes ~70-90 duplicate
   lines.

3. `shrink:` `cosine()` is reimplemented byte-for-byte twice:
   `scripts/enrich_index.py:66-69` and `scripts/calibrate_thresholds.py:93-97`.
   `rank_of()` is reimplemented byte-for-byte twice:
   `scripts/multivector_experiment.py:139-143` and `scripts/precision_eval.py:53-57`.
   Fold both into the same shared helper module as finding #2 (saves ~15-20 lines and
   removes the risk of the two copies silently drifting).

4. `yagni:` `scripts/driftcheck.py` (168 lines) is written and documented as a
   general-purpose, project-agnostic drift-detection engine — its own docstring
   (lines 1-22) says "Drop it into any repo — Python, JS, Rust, Go, docs-only." In
   this repo it has exactly one caller (`driftcheck.json`) checking exactly one fact
   family (the `version` string across 4 files) plus two `command_checks`. Those two
   command checks (`scripts/check_doc_parity.py`, 31 lines, and
   `scripts/check_skill_list_parity.py`, 27 lines) don't even use the framework they
   sit next to — each hand-rolls its own SSOT-vs-mirror set-diff instead. Net: a
   generalized platform built for a portability need nobody outside this repo has
   asked for, with its two hardest real cases opting out of it anyway.

5. `delete:` `config/deterministic-routes.json` — a permanently-empty stub
   (`"routes": []`, `config/deterministic-routes.json:1-4`) gated by an opt-in env var
   (`ENFORCER_DETERMINISTIC`) that is unset. Covered by finding #1; called out
   separately because it's the one piece of dead *config* (vs. dead code) in the set.

---

## Marked-vendored (flagged for completeness only — not this repo's code to cut)

`vendor/skill-search/skill_search/server.py` (583 LOC) is vendored upstream
(`vendor/skill-search/VENDORED.md`), with local customizations layered at the plugin
level rather than patched in-place (per VENDORED.md's own stated policy). Skimmed for
gross over-engineering; nothing rose to a confident, grounded finding worth listing
against code this project doesn't own. Two direct engine patches are documented
in VENDORED.md (multi-vector MAX-pool, plugin self-prefix guard) — both are described
as deliberate, ADR-backed changes, not speculative flexibility.

---

## Not flagged (deliberately excluded)

- `hooks/scripts/enforcer.py`'s `AUTHORIZED_SKIP` tier (lines 71-81, 309-335): default
  ON and actively read on every turn — not inert, so not a yagni candidate.
- The three "default-INERT" flags documented in `setup.sh:11-13`
  (`SKILL_BODY_TRIGGERS`, `ENFORCER_AUTHORIZED_SKIP`) are default-**ON** kill switches
  for shipped behavior (a revert lever), not speculative unshipped features — different
  category from finding #1.
- `scripts/multivector_experiment.py`, `scripts/precision_eval.py`,
  `scripts/calibrate_thresholds.py`, `scripts/build_*.py`: each is a standalone,
  clearly-labeled one-shot experiment/calibration script with its own `--selftest`;
  duplication *within* them is called out (#2/#3) but their existence as separate
  scripts is not itself over-engineering — they're run independently, at different
  cadences, by different people.

---

`net: -90 lines from finding #1 (dead-by-default enforcer complexity, excluding the
separate 241-line calibrate_thresholds.py and its doctor check which finding #1 also
recommends removing), -70 to -90 lines from #2, -15 to -20 lines from #3. 0 deps to
cut (repo is stdlib-only outside the vendored engine's pinned deps).`
