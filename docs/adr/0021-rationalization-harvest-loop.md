# ADR-0021 — H1 rationalization-harvest loop

Status: Accepted (2026-07-06)
Relates to: ADR-0020 (H3 subagent/dispatch session-scoping — this REUSES its audit-side exclusion as
the harvest denominator), ADR-0015 (AUTHORIZED-SKIP tier / `SKILL-CHECK:` marker — the harvest never
harvests an authorized skip), ADR-0019 (H5 self-referential over-fire lane — its `SELFREF_SKIP_MSG`
signature is one of the re-verify guards). Design doc: `docs/anti-dodge-integration-v0.14.md`.
Plan: `plans/260706-1315-superpowers-anti-dodge-integration/` (phase-03). Adapted (not copied) from
superpowers v6.1.1 RED-step — Jesse Vincent / Prime Radiant — MIT.

## Context
skill-concierge's own docs call in-generation compliance *"the only lever … unmeasured, not solved"*.
The audit already **detects** false skips (a `SKIPPING` declared with no same-turn `search_skills` and
no authorized marker — `_skip_verdicts`), but it only **counts** them; it never captured the verbatim
excuse the agent actually wrote. Without the real rationalizations there is nothing concrete to author
the H2 refutation table against. Turning the shipped *detector* into a *harvester* closes that gap using
machinery concierge already owns — no new dependency, still stdlib-only.

Four grounded traps had to be respected (all from the plan's red-team):
- **Stale `txt` (F5).** `txt` is loop-local to the inner content-block loop; at the turn-flush points it
  is stale/unbound. Capture must happen at the MATCH site.
- **No join key (F4).** Turn dicts carried no `sid`; `false_skip` is computed before `meta_sessions`
  exists, so meta/self/subagent turns could not be excluded at turn granularity.
- **Data exposure (F7).** A verbatim harvest emits assistant text that can quote paths/secrets/task text.
- **Authorized-skip contamination (F4/F8).** A lawfully-authorized skip (incl. H5's new lane) must NEVER
  be harvested as a rationalization, else H2 would author a refutation of the excuse the enforcer just
  authorized — a self-contradicting doctrine.

## Decision
All changes are in `skills/skill-usage-audit/scripts/audit_skill_usage.py` (stdlib-only, read-only except
the harvest sink).

- **Capture at the match site.** Where `_SKIPPING.search(txt)` fires, store `cur["skip_text"]` = the
  single `SKIPPING:` clause LINE (sliced on the surrounding newlines), NOT the whole `txt`. This caps the
  captured text to the clause and drops surrounding task text (F5 + F7 in one move).
- **Thread `sid` + `sub` onto every (skip) turn dict** at both flush points. `sid` = the file's session
  id; `sub` = the per-FILE subagent flag from ADR-0020 (subagent transcripts share the parent's `sid`, so
  `sid` alone cannot separate them — the `sub` flag does).
- **Pure harvest filter.** `_harvest_corpus(turns, meta_sessions, subagent_stop)` returns a deduped
  `clause -> count` corpus over false-skip turns, EXCLUDING self/meta/dispatch sessions (by `sid`) and
  subagent turns (by `sub`) when the flag is on, and dropping any clause that re-verifies as authorized.
  `_skip_verdicts` stays PURE and untouched (its selftest still pins it); the harvest filter is a separate
  pure function so `--selftest` pins it without touching the filesystem.
- **Re-verify against the live enforcer messages (item 2e).** `_looks_authorized(clause)` drops any clause
  echoing a live AUTHORIZED-skip signature — `full-catalogue retrieval ran` / `intent-margin classifier` /
  `self-referential recap lane` (`_AUTHORIZED_SIGNATURES`, kept in sync with GETAWAY/INTENT/SELFREF_SKIP_MSG
  in `enforcer.py`). This runs regardless of the flag.
- **Scrubbed, gitignored, local-only sink.** `--harvest [PATH]` writes the corpus to
  `./logs/skill-rationalizations.txt` (default). `_scrub()` redacts absolute home paths, emails, and common
  token shapes before write. The glob is pinned in `.gitignore` (in addition to the existing `logs/` rule).
  Never committed, never linked from an ADR.
- **Toggle:** the whole H3/H1 exclusion rides `SKILL_SUBAGENT_STOP` (default ON, one-var revert). `=0`
  yields byte-identical pre-change audit output and no harvest exclusion; authorized skips are still never
  harvested.

## Scope boundary (respected)
This ADR is the **harvest** side only. The H5 **audit-anchor** (wiring `self-referential recap lane` into
the authorized-skip COUNT at `:176-178` + its parity selftest) is a SEPARATE, held task and is NOT done
here — the count anchor was left exactly as shipped. Until it lands, SELFREF turns are kept out of the
harvest by the clause-level `_looks_authorized` re-verify above (the count-side exclusion arrives with the
held task).

## Evidence
- Selftests GREEN: `audit --selftest` → *OK: false-SKIPPING verdict + H1 harvest filter* (adds a
  false-skip-with-rationalization case that IS harvested, a meta-sid case + a subagent case that are
  EXCLUDED, an authorized-signature case that is dropped, and a `subagent_stop=0` revert-parity case).
  `analyze --selftest` → OK (untouched).
- Grounding for the exclusion signals (live transcript store): 980 files; 572 under `subagents/`, 558 with
  `isSidechain:true`, **0 files mix parent+subagent records** → the file-level subagent flag is exact. The
  3 dispatch phrases hit ~7-9 top-level sessions each, **0 under `subagents/`** → high-precision.
- Live smoke over all transcripts: H3 ON dropped the organic denominator `202→174` Skill-tool /
  `121→113` USING (subagent + 9 dispatched sessions removed); `SKILL_SUBAGENT_STOP=0` restored the
  original numbers and the original NOISE-SCOPED wording byte-for-byte.
- `--harvest` over all transcripts: **35 rationalizations (34 distinct)**, each output line is only the
  `SKIPPING:` clause (no surrounding task text), sink `git check-ignore`d ✓, and **0** authorized-signature
  substrings present in the corpus.

## Consequences
- H2 authoring now has a concrete, deduped corpus of the real excuses to refute — the missing input to the
  H3→H1→H2 loop.
- The harvest is additive and reversible; global totals and the false-skip COUNT are unchanged (only the
  organic denominator and the new corpus are affected).

## Open / to measure (accepted knowingly)
- **The RE-MEASURE leg may be "insufficient data" this epoch [Red-Team F6].** The HARVEST leg (capture →
  feed H2) is epoch-independent and keeps its value. The RE-MEASURE leg (false-skip rate before vs after)
  is windowed on the deploy commit via `scripts/analyze.py --since/--until` and is contingent on a
  config-freeze window; per `AGENTS.md` Guardrails this repo changes ledger inputs ~daily, so a fresh
  post-deploy window may be too small. Do NOT author H2-v2 from an unclean or tiny window — say
  *"insufficient data"* rather than pool across epochs. Define a minimum-n + freeze duration, or split the
  re-measure out of v0.14.0.
- **This is a dodge/compliance metric, not outcome quality.** The corpus says how often agents skipped
  without searching, not whether a skill would have helped. No usefulness-lift claim attaches to it.
- **Turn segmentation is a line-heuristic** (substring-sniffs raw JSONL at user-prompt boundaries) — a
  rationalization spanning multiple text blocks may split. Accepted for v1; the capture takes the clause
  line only, which is robust to this.
- **Marker-drift ceiling.** `_looks_authorized` matches literal enforcer substrings; if the enforcer
  wording drifts, an authorized skip could slip into the corpus. Fails SAFE toward over-harvest (a human
  reviews the corpus for H2), never toward masking a real dodge.
