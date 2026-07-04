# Research Summary — Does `scripts/generate_catalogs.py` bring value to skill-concierge?

**Date:** 2026-07-04 · **Method:** 3-agent `ck:team` research fan-out (provenance / architecture-fit / value-risk).
**Source reports:** researcher-1/2/3 (linked at bottom).

## Verdict (unanimous, 3/3)

**SHELVE — leave inert.** Zero value as-is; the static-catalog model is architecturally
opposed to skill-concierge's design. Do NOT wire it in, do NOT port its missing scanners,
do NOT delete it (workbench "no unsolicited cleanup" mode). Leave the untracked file where it sits.

## What the script is

Emits static, category-grouped `COMMANDS.yaml` / `SKILLS.yaml` catalogs from two YAML data
files — built for a DIFFERENT project ("ClaudeKit Engineer").

- **Untracked orphan.** `git status` → `?? scripts/generate_catalogs.py`; empty `git log`; not
  among the 14 tracked scripts (researcher-1 §5).
- **Cannot run here.** System python: `ModuleNotFoundError: No module named 'yaml'`. With a
  yaml interpreter it `sys.exit(1)`s — all 5 deps are missing: `commands_data.yaml`,
  `skills_data.yaml`, `scan_skills.py`, `scan_commands.py`, `win_compat.py` (researcher-1 §2-3).
- **Zero consumers.** Repo-wide `rg` matches only the file itself (researcher-1 §4).
- **Foreign branding + taxonomy.** Lines 58/103 hardcode "ClaudeKit Engineer"; category lists
  (`:63-76`, `:107-118`) are ClaudeKit's, not skill-concierge's namespaced `SKILL.md` corpus.

## Why a static catalog contradicts the design (holds even if the script were fixed)

- The project exists to **kill the full-catalog dump**: `README.md:8-10, 33-36, 49` — replaces
  "hope" with "retrieve-precisely"; the enforcer injects "a PREVIEW of ~500, not all"
  (`enforcer.py:244-248`) (researcher-2 §1).
- **One live source of truth.** `discover_skills()` globs `SKILL.md` at index time;
  `skills_discovery.py:5-16` warns a second discovery path causes "silent budget leaks." A
  static YAML is exactly that second path — it drifts the instant a skill changes, while the
  index self-heals via `auto_reindex.py` (researcher-2 §2,4).
- **COMMANDS half is out of scope entirely.** Slash-commands are excluded by design
  (ADR-0001 / `README.md:53-58` — "the model can't fire them") (researcher-2 §4c).
- skill-concierge ships **no** static catalog today; its only static config is curated
  SUBSETS (`config/keep-on.json` / `keep-off.json`), never full dumps (researcher-2 §3).

## "How could it be beneficial?" — honest answer

**As-is: it can't.** The one latent want it gestures at — a human-readable "what skills exist"
inventory — is already covered three ways over:

- served live by the engine's `health` tool + `discover_skill_paths()` (`server.py:113`);
- kept honest by two tracked, stdlib-only scripts — `check_skill_list_parity.py` (asserts
  AGENTS.md names == on-disk `SKILL.md`) and `driftcheck.py` (researcher-3 decisive point);
- not needed by the audit either — `skill-usage-audit/SKILL.md:57` sets the denominator to
  "applicable turns," NOT "all skills" (researcher-3 (c)).

The ONLY architecture-neutral way to have a generated inventory (researcher-2 §5): source it
from `discover_skills()` (the SSOT) **and** never inject it per-turn (offline snapshot only).
This ClaudeKit script fails both — it scans its own parallel `*_data.yaml`, and its docstring
says the output is "for consumption by Claude." Even the salvage path routes AWAY from this file.

## Recommendation

Leave it inert and untracked. If a real "generated inventory doc" need ever surfaces, write a
thin wrapper over the existing `discover_skills()` SSOT that emits an offline doc — do not
adopt or adapt this file.

## Unresolved

- Intent of the copy-in is unconfirmed — plausibly a scratch tool the operator uses to
  generate docs for ClaudeKit *itself* while working inside this cross-pollination workbench.
  Does not change the verdict for skill-concierge.

## Source reports

- `plans/reports/researcher-1-260704-0212-generate-catalogs-provenance.md`
- `plans/reports/researcher-2-260704-0212-static-catalog-architecture-fit.md`
- `plans/reports/researcher-3-260704-0212-value-risk-recommendation.md`
