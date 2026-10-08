# F-docs dispositions (worktree chisle-cuts, base 692cab1)

One line per finding in F-docs.md, in file order. Timezone Asia/Saigon, 2026-10-09.

- docs/always-on-skill-set-proposal.md:1 — FIXED: archived to ~/_ARCHIVE/skill-concierge-retired-docs-20261009/ (byte-compared), deleted from worktree; no inbound link anywhere outside plans/ (ADRs, journals, openwiki, README, tests, scripts checked)
- docs/skill-search-deployment-readme.md:1 — FIXED: archived the same way; no inbound links
- README.md:466 — FIXED: release-history block replaced by "Current release: `0.64.0` — **published**" plus link to CHANGELOG.md; driftcheck's README regex still matches (occurrence first)
- docs/skill-search-trial-setup-260625-2233-report.md:1 — FIXED: archived; no inbound links
- docs/plan.md:1 — SKIPPED: finding marked (check) and not approved; driftcheck.json still lists docs/plan.md
- openwiki/operations.md:175 — FIXED: flag table and 20-line utterance-layer caveat replaced by links to AGENTS.md -> Runtime flags and docs/runtime-flags.md; the four flags documented only in the copies (ENFORCER_SELFREF_SKIP ON, SKILL_SUBAGENT_STOP ON, SKILL_TRIGGER_PURITY unset = `shadow`, SKILL_PLUGIN_FILTER ON) verified in code (enforcer.py:933, doctrine.py:52, skills_discovery.py:443 and :200) and added to the AGENTS.md table and docs/runtime-flags.md
- docs/skill-first-enforcement-mental-model.md:219 — FIXED: section 10 (v0.3.0 standing order, EFFORT order, old trigger) replaced by a pointer to hooks/doctrine/skill-first.md; history note reworded
- docs/multivector-retrieval-arc.md:1 — FIXED: archived; only self-reference
- openwiki/architecture/enforcement-gate.md:34 — FIXED: doctrine paraphrase replaced by a short summary, ADR links and a link to hooks/doctrine/skill-first.md
- openwiki/operations.md:303 — FIXED: commit-guardrails section reduced to a pointer to AGENTS.md -> Guardrails; now names all three denying gates and the one warning hook
- openwiki/quickstart.md:147 — FIXED: annex release narrative cut to a current-behaviour summary linking ADR-0032/0034/0036/0047/0048/0059
- README.md:631 — FIXED: trajectory and open question removed with the history block (the `find-skills` mention went with it)
- README.md:315 — FIXED: external-catalog narrative condensed to current behaviour, values read from enforcer.py (EXTERNAL_FLOOR 0.32, ANNEX_BEAT 0.04, GETAWAY_FLOOR 0.45, MIN_TAKES 3)
- README.md:366 — FIXED: architecture tree replaced by a link to docs/repository-layout.md; that file's "full tree is in the README" pointer reversed
- README.md:229 — FIXED: runtime-flags table replaced by a link; parity check passes
- README.md:435 — FIXED: request-flow list replaced by a link to openwiki/architecture/three-organs.md; the two details only the README had (second PostToolUse matcher with the "not for" echo, jevd env warning, harness-skip and deterministic routes) were added to three-organs.md first
- openwiki/operations.md:86 — FIXED: five-step epoch checklist cut to two sentences plus link to AGENTS.md -> Guardrails (canonical copy kept in AGENTS.md; CLAUDE.md and AGENTS-ONBOARDING.md kept as short pointers/summaries)
- openwiki/quickstart.md:88 — FIXED: Codex and OMP installer narratives cut to short pointers; "four harnesses" and "seven" corrected
- docs/caveats.md:141 — FIXED: section 9 folded into section 3 (symptom, fallback rate, retired shim); a two-line stub keeps the section numbers stable because CHANGELOG and an immutable ADR cite them
- docs/caveats.md:619 — FIXED: resolved non-issue cut to two sentences
- docs/caveats.md:271 — FIXED: section 15 rewritten: all ten skills carry a bare `name:` (verified in skills/*/SKILL.md); history of why the namespaced form was dropped is UNVERIFIED and not asserted
- CLAUDE.md:8 — SKIPPED: finding is (check)/low and the `@AGENTS.md` import was not approved; only the embed_server.py phrase on line 15 now says "retired, archived in v0.64.1"
- openwiki/architecture/enforcement-gate.md:246 — FIXED: heading "three legs, two formerly silent" -> "five legs" (both inbound anchors updated), leg C bullet shortened to a pointer, paragraph kept as the single description
- docs/anti-dodge-integration-v0.14.md:3 — SKIPPED: (check), ADRs 0019-0023 link it
- docs/ideas/consult-mode.md:3 — SKIPPED: low confidence (check), ADRs link it
- docs/caveats.md:686 — FIXED: section 26 release-time measurements replaced by one line pointing at ADR-0087; limits and Do kept
- README.md:727 — FIXED: `rm -f ~/.codex/hooks.json` deleted. Verified: grep of adapters/scripts/hooks/setup.sh shows the Codex installer only checks repo-relative `.codex/hooks.json`, never writes ~/.codex/hooks.json. Replacement steps use `codex plugin remove skill-concierge@skill-concierge` and `codex plugin marketplace remove` (both verbs confirmed with `codex plugin remove --help` and `codex plugin marketplace --help`)
- README.md:786 — FIXED: Contributing points to AGENTS.md -> Conventions for the manifest list
- docs/caveats.md:111 — FIXED: section 7 points to AGENTS.md -> Conventions
- docs/caveats.md:200 — FIXED: section 11 Do rewritten from bin/skill-search-mcp (stamp, background resync, first spawn serves the old engine); setup.sh only for dependency changes
- docs/caveats.md:161 — FIXED: section 10 body removed, stub kept (numbering stable; immutable ADR-0008 cites it)
- openwiki/architecture/enforcement-gate.md:363 — FIXED: skill table now lists all ten (blocklist, reputation, catalogs, consult added from their SKILL.md descriptions), heading "six" dropped, pointer to the AGENTS.md brace list
- openwiki/architecture/retrieval-engine.md:211 — FIXED: five tools (consult_candidates row added from server.py:1332); TOP_K row now 6 (.mcp.json:10, server.py:83)
- openwiki/operations.md:278 — FIXED: SKILL_TOP_K=6, keep-on seed 31 entries (counted); README "32" occurrences fixed too (README :259; the :382 tree line went with the tree)
- openwiki/operations.md:151 — FIXED: "(current: v0.20.0)" dropped
- README.md:8 — FIXED: README lines 8, 33, 71, 146 and Uninstall intro now cover all eight harnesses; quickstart.md lines 3-5 and 61 likewise; an uninstall section for DSH, Cline and OpenCode v2 was added from the installers' own headers (cordis.patch.yml inserts, ~/.cline/plugins/skill-concierge.ts and ~/.agents/plugins/skill-concierge/, opencode.json `plugins` entry and .skill-concierge-managed.json)
- README.md:178 — FIXED: stale hit@k "pending" note deleted
- README.md:682 — FIXED: troubleshooting row for the 0.1.2 bug deleted
- docs/epoch-watch.md:87 — FIXED: header "Unreleased" -> "v0.59.0" (CHANGELOG.md has `## [0.59.0]`)
- docs/caveats.md:522 — FIXED: section 21 opener now points at section 23 item 6 for the event list instead of repeating it
- docs/how-it-works-plain-language.md:46 — SKIPPED: low confidence

Extra edits (not in the findings, same class, all verified):
- AGENTS-ONBOARDING.md (was never audited): removed brittle line/ADR/landmine counts, "warm shim 200ms"/Qdrant wording, the epoch command's embed_server.py path (now index_owner.py), "bump both manifests" (now four, links AGENTS.md), `name: skill-concierge:<name>` skill rule (now bare `name:`), caveats section 15 reference
- README.md: removed source-line coordinates (`setup.sh:47`, `install.sh:41-51` etc.) that are stale by nature
- docs/repository-layout.md: dropped the embed_server.py entry from the scripts list, added "retired, archived in v0.64.1" note
- driftcheck.json: unchanged. It names none of the four archived docs and none of the four scripts being archived, so no path entry needed dropping.

Dropped content, per RULES [32]: README release history for 0.1.x-0.63.0 (86 entries). 85 of them have a `## [x.y.z]` heading in CHANGELOG.md. `0.22.0` does NOT: its README entry (ADR-0031 external catalog roots, first catalog `antigravity` with 1,603 skills) now survives only in git history, ADR-0031 and the README/quickstart catalog sections. Suggest the main session add a 0.22.0 CHANGELOG entry or accept the loss.

Concerns for the main session (not mine to fix):
1. tests/test_sibling_installers.py::test_readme_054_1_line_mentions_the_zcode_missing_registry_entry_refusal reads README.md for the "`0.54.1` —" line and now fails (ValueError: substring not found). The README history it pinned was cut by order. CHANGELOG [0.54.1] does not contain "no matching entry" either. Either retarget the test at CHANGELOG.md after adding that fact to the 0.54.1 entry, or delete the test. It is in the tests lane, so I did not touch it.
2. docs/plan.md:155 still describes the retired embed shim; it is a dated build log and a (check) item, left as is.

Verification (run in /Users/thinhkhuat/.worktrees/skill-concierge/chisle-cuts):
- `python3 scripts/driftcheck.py driftcheck.json` -> exit 0, "IN SYNC: every fact matches its source of truth." (version 0.64.0 everywhere; four command checks OK)
- `python3 scripts/check_flag_docs_parity.py` -> "flag-docs-parity OK: 45 table rows, 43 full entries; 45 table defaults and 40 stated docs defaults match the code"
- relative-link and anchor check over README.md, AGENTS.md, CLAUDE.md, AGENTS-ONBOARDING.md, docs/*.md, docs/ideas/*.md, openwiki/**/*.md -> 0 missing targets, 0 missing anchors
- `python3 -m pytest -q -p no:cacheprovider tests/test_flag_docs_parity.py tests/test_codex_installer.py tests/test_sibling_installers.py tests/test_git_stash_guard.py tests/test_jev_client.py` -> "1 failed, 204 passed" (the failure is concern 1)
- not checked: rendering of the edited Markdown tables in a viewer; the DSH/Cline/OpenCode uninstall steps were taken from installer headers and code, not executed
