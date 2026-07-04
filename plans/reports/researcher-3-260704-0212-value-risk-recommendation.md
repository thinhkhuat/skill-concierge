# generate_catalogs.py — Value, Risk & Recommendation

**Angle:** value / risk / one recommendation. **Mode:** read-only.
**Verdict up front: SHELVE — do not adopt, do not invest, leave inert.**

---

## The one fact that decides everything

`scripts/generate_catalogs.py` **cannot run in this repo.** It loads two data files and
they do not exist:

- `generate_catalogs.py:40` → `load_yaml('commands_data.yaml')`
- `generate_catalogs.py:85` → `load_yaml('skills_data.yaml')`
- Its own error hint (`:33`) says "Run scan_skills.py or scan_commands.py first" — **both
  scanners are also missing.**

Confirmed absent (`ls` + `rg`): `scripts/commands_data.yaml`, `scripts/skills_data.yaml`,
`scripts/scan_skills.py`, `scripts/scan_commands.py`. On invocation it hits `sys.exit(1)`
immediately. It is also **untracked** (`git status` → `?? scripts/generate_catalogs.py`;
`git ls-files` does not list it) and **referenced by nothing** — `rg "generate_catalogs"`
across the whole repo returns only the file itself. It is a non-running, orphan ClaudeKit
artifact that landed in `scripts/` via workbench cross-pollination.

---

## Value candidates — each rebutted

| # | Candidate use | Already solved / verdict |
|---|---------------|--------------------------|
| **(a)** | Human-readable skill/command inventory doc under `docs/` | **No need felt.** skill-concierge ships **4** plugin skills; AGENTS.md:25 already names them in a hand-written brace list and `check_skill_list_parity.py` keeps that list honest against disk. A generated catalog of the *entire host* skill universe is not the plugin's job — the plugin **governs** skills, it does not **own** the catalogue. |
| **(b)** | Input to the reindex / health pipeline | **No.** Reindex reads `skills/*/SKILL.md` directly through the vendored engine → Qdrant (`README.md:228-233`). The pipeline consumes SKILL.md files, not a YAML catalog. This script is a doc *emitter*, not a pipeline *input*. |
| **(c)** | Audit denominator — "what EXISTS" vs "what got USED" | **No.** `skill-usage-audit/SKILL.md:57` defines the denominator as **"applicable turns"** (right skill surfaced-and-used ÷ applicable turns), NOT "all skills." The audit never needs a static full-skill roster; a catalog would answer a question it does not ask. |
| **(d)** | Onboarding / AGENTS.md reference | **Marginal → no.** AGENTS.md already lists the 4 skills and points to README architecture. Nothing here is improved by a generated ClaudeKit-shaped catalog. |
| **(e)** | None / orphan | **This is the honest bucket.** Untracked, non-running, unreferenced. |

**The decisive "already solved" point:** the only real job a skill catalog could serve —
keeping an inventory in sync with reality — is **already owned by two tracked, stdlib-only
scripts**: `check_skill_list_parity.py` (SSOT = on-disk `skills/*/SKILL.md`; asserts
AGENTS.md names exactly those; exit 1 on drift) and `driftcheck.py` (version triple +
every doc-referenced path exists). Both are committed and dependency-free. The niche is
filled. `generate_catalogs.py` adds a *third*, un-tracked, non-running way to describe the
same corpus.

---

## Risks if adopted / adapted

1. **Dual source of truth vs the live index — the core architectural conflict.**
   skill-concierge's whole thesis is *retrieve dynamically from one live semantic index* so
   the catalogue "can't diverge from the model the server uses" (`README.md:164-166`), and
   it spent real effort self-guarding staleness (ADR-0013 engine-freshness, ADR-0014
   auto-reindex). A hand-fed static YAML catalog is the **exact anti-pattern** that
   architecture was built to eliminate — it would drift the moment a skill is added.

2. **Hardcoded ClaudeKit taxonomy that does not match this corpus.** The command
   categories (`:63-76`: core / bootstrap / cook / scout …) and skill categories
   (`:107-118`: ai-ml / frontend / backend …) are **ClaudeKit's**, not skill-concierge's
   namespaced `SKILL.md` corpus (`ck:worktree`, not `worktree` — README.md:63). Output
   would mis-bucket real skills.

3. **Wrong product name baked in.** Metadata strings hardcode **"ClaudeKit Engineer"**
   (`:59`, `:103`) — a foreign product identity, not skill-concierge.

4. **Hard dependency on absent scanners + data files.** Adopting it means *also* importing
   or writing `scan_skills.py` / `scan_commands.py` and their YAML outputs — net-new tooling
   and maintenance burden to feed a catalog nobody consumes.

5. **Ongoing maintenance for zero consumer.** Every skill add/remove would need a manual
   regen to stay truthful — cost with no offsetting reader.

---

## YAGNI / KISS

skill-concierge does not have the problem this script solves. Its design *deliberately
avoids* dumping a static skill catalogue (that is the default behaviour the whole project
exists to replace — README.md:33-43). A generated static catalog is philosophically
opposite to the product. **Present problem it would remove: none.** Discriminating test —
*does it serve any present, unfilled need not already covered by the live index + existing
tracked tooling?* — fails on three independent grounds: (1) can't run, (2) parity/inventory
niche already owned by `check_skill_list_parity.py` + `driftcheck.py`, (3) audit denominator
is "applicable turns," not "all skills."

---

## Recommendation

**SHELVE — do not adopt, do not invest, leave inert.** One line: it is a non-running,
untracked, unreferenced ClaudeKit artifact whose only function (static catalog generation)
is architecturally opposed to skill-concierge's live-index single-source-of-truth design and
already covered — for any real inventory-sync need — by the tracked `check_skill_list_parity.py`
and `driftcheck.py`.

*Not recommending deletion:* the workbench operating mode is explicit "no unsolicited
cleanup; out-of-place files are intentional cross-pollination." An inert untracked file
costs nothing where it sits. The correct action is **leave it alone** — do not wire it in,
do not port the missing scanners, do not spend effort adapting it.

---

## Unresolved questions

- **Intent behind the copy-in is unconfirmed** (provenance is researcher-1 / Task #1's
  angle). It *may* be a scratch tool the operator uses to generate docs for ClaudeKit itself
  while working inside this cross-pollination workbench. Either way it is not
  skill-concierge's concern — the value/risk verdict for *this* repo is unchanged: shelve.
