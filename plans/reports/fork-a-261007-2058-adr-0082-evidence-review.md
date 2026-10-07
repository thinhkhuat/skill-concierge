# Fork A: evidence and premise review of ADR-0082 (whole-shelf ranking as a skip source)

Date: 2026-10-07 ~21:05 (Asia/Saigon). Read-only. My brief: argue as hard as the evidence allows for
keeping the forced search after a whole-shelf ranking, then judge. Fork B covers mechanism and wording.
Prompt text is kept out of this report; raw lists that quote prompts: `~/.claude/skill-concierge/analysis-private/fork-a-261007/` (`lists.txt`,
`turns.jsonl`), produced by `search_value.py --list direct_skip --list other --list search_none`
(305 organic whole-shelf work turns, 22 searched, the same totals as the corrected analysis).

## Verdict: SHIP WITH CHANGES

The single strongest reason to ship: the search-free skips the rule would legalize already take the
rule's form and drew no correction. In the 13 of the 36 `direct_skip` turns I read in the transcripts,
the agent named the top offered skill and why it did not fit in 9 (for example `a7315e91` 10-02 13:38:
"verify-as-claimed fits validating finished work; this is reading toggle state and file timestamps"),
and in all 13 the next user prompt was a continuation or praise, never a correction (detail below).
The forced search is not what prevents bad skips today; agents breach it, and the breaches look right.

The strongest argument against, which the ADR does not name: the rule lowers the price of skipping on
every whole-shelf turn, including the 160 where agents currently take a skill from the menu. The
transcript cannot show how many of those would switch to the cheaper one-line skip. That risk is
behavioural, not about search yield, and W40 as written does not watch it.

## 1. Premise attack

**Is "the search found a skill the agent then used" the right measure?** Only partly. Fact: it counts
search value only where the agent chose to search and then chose to take a hit. It misses three things.

- *Searches that surfaced a plausible skill the agent declined.* Of the 22 organic searched turns, one
  returned a plausible fit that was neither offered nor used: 10-03 02:00, query "assess external github
  repo fit for agent harness" returned `scout-foreign-repo-via-raw-urls` and `github-foreign-repo-scout-study`
  (raw list in the private folder). Inference: a search occasionally helps, and the agent, not the
  search, drops it. Open Question: neither name exists under `~/.claude/skills/` or `~/.omp/agent/skills/`
  (`ls` returned "No such file or directory" for both), so whether either was usable here is unverified.
  The HOIVU 10-07 17:23 search also returned the external `antigravity-i18n-localization` at rank 6.
- *Deterrence.* Judgment Call: the forced search may matter mostly as a price on skipping, which keeps
  agents choosing a `USING:` from the menu. Nothing in a transcript can show a skip that did not happen.
  This is the best argument for keeping the rule, and it is unmeasured either way.
- *Search quality.* Fact: 65 % of the 292 hits on the 46 searched whole-shelf turns are `antigravity-*`
  external rows (corrected analysis), and today's `search_skills` responses carry "skills changed on disk
  since last index — run reindex()". Inference: 0 of 22 partly measures a degraded search, not the value
  of searching. Fixing retrieval could raise the yield.

**Are the 22 searched turns representative of the 36 skips the rule legalizes?** No, and the bias runs
toward the ADR. Fact: the 36 are mostly status, chat and live-probe turns (progress questions, short acknowledgements,
reports that a service is not reachable). The 22
searched turns were ones where the agent suspected a skill might exist. Inference: on the 36, a search
would likely have found even less. The selection does not hurt the ADR's case.

**What does 3 of 46 in skill-concierge sessions say?** Fact: all three finds came from sessions where
the agent searched with specific terms (10-06 21:03 "hedged request fallback double billing latency
tradeoff", 10-07 20:24 "audit whether forced skill searches led to skill use, from transcripts and
ledger"). Inference: the search earns its cost when the agent already suspects a specific missing skill.
The ADR keeps exactly that case available ("rule `SEARCH:` … when you expect a skill it did not show",
`hooks/doctrine/skill-first.md` rule 1), so this evidence supports the design.

## 2. Counter-evidence on disk

I hand-read 13 of the 36 `direct_skip` turns in the transcripts (script `/tmp/forka_turn.py`, which prints
the turn's assistant text and the next three user prompts):

| Turn | Agent's ruling (abridged) | Next user prompt |
|---|---|---|
| `832d2916` 10-07 16:27 | "`vn-editor` is the closest fit, but your standing order for this work is Haiku general agents" | continued the work |
| `832d2916` 10-07 17:40 | "a scope correction, not new work" | compaction |
| `a7315e91` 10-02 00:22 | "diagnose/ak-debug fit code bugs; this is checking one SIP-blocked delete" | a follow-up instruction, no correction |
| `a7315e91` 10-02 13:36 | "diagnose/ak-debug target code bugs; this is two disk-size readings" | new detail, no correction |
| `a7315e91` 10-02 13:38 | "verify-as-claimed fits validating finished work; this is reading toggle state" | — |
| `d3d7a1cb` 09-28 00:07 | "The top-ranked skill is for adding a new auth system, which doesn't fit" | agent relay confirming the cause |
| `d3d7a1cb` 09-27 23:12 | "needs one live probe and a direct answer" | an instruction to speed up, no correction |
| `d3d7a1cb` 09-27 23:20 | "a live status probe; the verify and diagnose skills are for finished work" | the user accepted the explanation |
| `d3d7a1cb` 09-27 23:21 | "this sets up a watcher" | — |
| `d3d7a1cb` 09-28 16:47 | "top offered skill, tk-servers-ssh-doctor, repairs SSH access, and SSH already works" | an instruction to pause cleanly |
| `14904909` 10-04 01:33 | "a question plus a locked constraint… no skill covers explaining them" | continued |
| `754a9f4c` 09-27 13:17 | "a design question… Top hit `update-implementation-plan` edits plan files" | approval and praise |
| `426c1797` 10-05 20:32 | (no text captured by the script) | — |

Fact: no correction by Thinh follows any of them. Judgment Call: two reasons are thin ("needs one live
probe", "sets up a watcher") and name no skill; under the ADR's audit they would count as false skips,
which is the right outcome. Not checked: the other 23 `direct_skip` turns.

**The 50 "no ruling" turns.** Fact: 49 of 50 carry no ruling at all (`ruling: None`), one a `SEARCH`
line with no search call. Several are real work where a skill plausibly applied: fixing and updating a
tool to its upstream version, briefing on a repository, producing a PDF copy of deliverables, filtering a
media file list. These are doctrine
breaches of line 1, not skips the ADR legalizes; the forced search did not run there either. Inference:
they do not bear on ADR-0082, but they show the forced search is not what keeps skill use up on the
turns where it matters.

## 3. Are ADR-0062's and ADR-0056's reasons answered?

- **ADR-0062 reason 1, confounded evidence** (`docs/adr/0062-no-skill-ruling-and-whole-shelf-label.md:26`:
  "17 of the 18 'needless' searches followed an embedding menu that lacked the skill"). Answered: the new
  evidence is whole-shelf turns only.
- **ADR-0062 reason 2 / ADR-0056, "not a new skip class"** (`docs/adr/0056-doctrine-rewrite-writing-for-agents.md:76`:
  "Trivial questions that reach a preview or a getaway line now cost a search… if the trail shows it
  hurting, the fix is the getaway leg's wording, not a new skip class"). Answered more strongly than the
  ADR says: on a whole-shelf turn the router's top 5 replace the embedding menu and the getaway and
  actionability gates (`AGENTS.md:70`, `ENFORCER_JEV_ROUTER`), so no getaway wording can reach these
  turns at all. ADR-0082's "Alternatives rejected" argues from the fit floor instead; it should cite this.
- **ADR-0056's trade-off** ("seconds against the top-severity failure"). Still valid as a principle. The
  new evidence says the seconds bought little on whole-shelf turns; it does not say the top-severity
  failure is rare. The deterrence point above is the unmeasured part of that trade.

## 4. Changes before shipping

1. **Name the price-shift risk in ADR-0082 and watch it in W40.** Record today's baseline on organic
   whole-shelf work turns (Fact, from the lever: 305 turns; skill from the offer 160, 52.5 %; search-free
   `NO SKILL:` 36, 11.8 %) and add a trigger such as "skill-from-offer share falls below 45 % or the skip
   share rises above 20 % on n ≥ 100 turns", with the same revert action. W40 today watches only missed
   skills and hollow reasons (`docs/epoch-watch.md:22`).
2. **Cite `AGENTS.md:70` in "Alternatives rejected"**: the whole-shelf path bypasses the getaway leg, so
   ADR-0056's suggested fix cannot apply. This is the cleanest answer to the decision being reopened.
3. **Treat search quality as a separate open item** and say in the ADR that 0 of 22 was measured against a
   search whose hits are 65 % external rows and whose index reported stale. Re-measure W40's offline
   search replay after a reindex, or the replay inherits the same handicap.

## Not checked

- 23 of the 36 `direct_skip` turns and the outcomes after them.
- Whether the two unused 10-03 02:00 hits were invocable here.
- Any harness other than Claude Code.
- The doctrine wording and the audit code (fork B's scope).

Status: DONE_WITH_CONCERNS

Summary: The evidence supports shipping. The search-free skips the rule would legalize already name
the top offered skill and a reason in 9 of the 13 I read, and no correction from Thinh follows any of
the 13. The searched turns show almost no yield, and the only finds came when the agent searched for a
specific suspected skill, a case the draft keeps. ADR-0062's confound is answered, and ADR-0056's "fix
the getaway wording" route cannot reach whole-shelf turns at all (`AGENTS.md:70`). Two things weaken the
case and belong in the ADR before shipping. First, the rule lowers the price of skipping on every
whole-shelf turn, and that shift, away from the 52.5 % of turns that take a skill from the menu, is
unmeasured and unwatched. Second, the zero was measured against a degraded search (65 % external hits,
stale index). Ship with a W40 baseline-and-trigger for the skip share, the `AGENTS.md:70` citation, and
search quality recorded as an open item.
