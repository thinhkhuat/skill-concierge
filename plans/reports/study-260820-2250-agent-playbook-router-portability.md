# Study: agent-playbook → skill-concierge portability (router focus)

**Date:** 2026-08-20 · **Mode:** read-only investigation (RULES [1] — no writes to either repo beyond this report)
**Method:** direct read of both repos' core files + two scout agents (full 24-skill inventory of `FORKED/agent-playbook`; full retrieval/enforcement/heal inventory of `skill-concierge`). All claims below carry file:line cites.

## 1. What agent-playbook (apb) actually is

24 content skills + a meta layer. The pieces relevant to routing:

| Piece | What it is | Cite |
|---|---|---|
| `skill-router` | Prompt-only conversational router: catalog tables in SKILL.md, intent analysis (task type/context/complexity), keyword + "semantic" (Claude's judgment) matching, clarification templates, confidence labels, canonical multi-skill sequences | `skills/skill-router/SKILL.md:81-236` |
| `metadata.hooks` spec | Declarative per-skill frontmatter: `after_complete`/`on_error` follow-ups with modes `auto`/`background`/`ask_first` + `condition:` | `skills/auto-trigger/SKILL.md:68-98` |
| `workflow-orchestrator` | Reads hook metadata at milestones (file-existence checks), runs follow-ups by mode | `skills/workflow-orchestrator/SKILL.md:71-142` |
| `self-improving-agent` | Multi-memory learning loop (episodic JSON + semantic patterns w/ confidence counter + working), abstraction rules (3+ repeats → promote), capture-first promotion policy, on_error self-correction | `skills/self-improving-agent/SKILL.md:111-342` |
| MCP server | 4 tools; `search_skills` is **keyword substring filter** — no embeddings, no vectors | `mcp-server/index.js:296-307` |
| `apb` CLI | init/doctor/skills-manager + hook runtime; pattern-based skill-completion detection (`Write *-prd.md`→prd-planner, `git commit`→commit-helper, `gh pr create`→create-pr) | `packages/agent-playbook/src/cli.js:382-464` |

## 2. The honest comparison

apb's router is **strictly weaker** than skill-concierge's engine on every retrieval axis:

- apb search = substring match on name/description/category (`mcp-server/index.js:296-307`). skill-concierge = multilingual mpnet + Qdrant multi-vector MAX-pool over name+desc+body+trigger layers (`vendor/skill-search/skill_search/server.py:474-497,677-728`).
- apb routing = static tables Claude reads. skill-concierge = live per-turn retrieval + floors + intent-margin actionability gate + enforcement doctrine (`hooks/scripts/enforcer.py:625-728`).
- apb's own local-inventory doc admits the hook chains **do not auto-fire** on this machine (symlink install, no runtime wiring) — `docs/apb-skills-inventory-and-orchestration.md:107-114`.
- skill-concierge already ships the soft-chaining primitive apb's spec gestures at: ADR-0029 `next-skills:` → sidecar → CHAIN-HINT line, keep-off + catalogue filtered, TTL-bounded (`enforcer.py:188-280`).

## 3. Verdict per candidate novelty

### Worth porting (1 item, zero code)

**Named multi-skill workflow chains surfaced at routing time.** apb's canonical sequences ("API project: api-designer → api-documenter → test-automator", `skills/skill-router/SKILL.md:193-197`) are the one idea skill-concierge has the mechanism for but a thin corpus of: `next-skills.json` currently holds 3 non-empty chains (verify→handoff, doctor→flywheel, ak-plan→ak-cook). Daisy-chaining already composes — using Y fires Y's own successors within the 15-min TTL. The port is **authoring, not engineering**: add `next-skills:` frontmatter to the workflow-head skills (ak-brainstorm→ak-plan, ak-plan→ak-cook→ak-test, ak-fix→ak-test, ak-cook→ak-code-review→ak-ship, …). No engine change; the sidecar, filters, and CHAIN-HINT line all exist.

### Deferred candidate (needs its own ADR, not a port now)

**Outcome/`on_error` capture.** apb's only whole leg skill-concierge lacks: recording skill-failure episodes for self-correction (`self-improving-agent/SKILL.md:297-342`; CLI `on_error` via Bash non-zero, `cli.js:441-464`). skill-concierge's ledger records offers/takes but no outcome dimension (`hooks/scripts/ledger.py:29-97`). Cheap-ish version: an `outcome` ledger row class + recurrence rule in `analyze.py`. Blockers: no hook currently observes skill completion/error — needs new surface (Stop hook or PostToolUse(Bash) watcher); the flywheel + rationalization-harvest (ADR-0021/0026/0027) already cover the input side; memsearch already journals sessions. Signal value unproven — epoch-scoped measurement required before building (AGENTS.md:85-104).

### Already covered — no port needed

- `get_skill_hooks` MCP tool → `get_skill` already returns full SKILL.md incl. frontmatter (`server.py:731-750`).
- Interactive clarification templates → contradicts additive-only gate design; ambiguity escalates to `find-skills` (ADR-0015 library doctrine).
- Milestone detection via file greps → owned by ak:* workflow skills + workbench rules routing, not a governance layer's job.
- Session logging with structured extraction → memsearch journals + invocation ledger.
- Multi-platform (Codex/Gemini) distribution → out of scope by design.
- Pattern-based completion detection → apb needed it because its skills have no invocation event; skill-concierge has the native PostToolUse(Skill) signal.

### Anti-port (would be a regression)

- **Confidence labels (High/Medium/Low)** on recommendations — ADR-0009 evidence: cosine is *anti-correlated* with adoption (taken median 0.414 < dodged 0.457); `_ranked_mandate` deliberately renders relative share, "not confidence" (`enforcer.py:527-540`). apb's labels would launder rank into fake confidence.
- **`catalog.json` hand-curated category map** — drift-prone manual file; skill-concierge derives everything from frontmatter at index time.
- **Mode-based follow-up execution** (`auto`/`background`/`ask_first` as *behavior*) — contradicts the accepted soft-hint stance (ADR-0029: hard routing rejected; hooks additive-only, never execute).
- Porting apb's keyword MCP search or static-table routing in any form.

## 4. Recommendation — item 1 EXECUTED same session (2026-08-20 ~23:00)

1. **DONE — next-skills chains seeded.** 7 ak workflow-head skills edited in `~/.claude/skills/*/SKILL.md` (plain dirs; byte-precedent from the prior session's `ak-plan→ak-cook` seed; component-install marker used per hook protocol, removed after): brainstorm→plan, cook→test+code-review, fix→test, debug→fix, test→code-review, code-review→ship, ship→journal. Plus `skills/setup/SKILL.md` → `skill-concierge:doctor` in-repo. Reindexed with SSOT env (365 skills, 9 embedded). Sidecar now holds **10 non-empty chains** (was 3); `enforcer.py --selftest` OK; `doctor.py` status WARN only for the pre-existing stale-MCP-server-build issue (pid 87989 predates last engine deploy; remedy = restart Claude Code; enforcer unaffected — it reads the sidecar from disk per turn).
   - **Pending deploy:** `setup→doctor` lives in the repo but the index reads the installed copy at `plugins/cache/skill-concierge/skill-concierge/0.21.2` — activates at the next version cut (0.21.3+). Cache NOT patched (upstream-managed; workbench rule).
   - **Known limit — RESOLVED same session by ADR-0030.** The owner flagged the loaned frontmatter edits as a critical flaw: any upstream upgrade rewrites the file and silently wipes the curation. Fix shipped: chains for third-party skills now live in the operator-owned `~/.claude/skill-concierge/next-skills-overrides.json`, merged reader-side in `enforcer.py::_visible_sidecar_names` (override-wins, fail-open, no engine patch). The 8 loaned frontmatter lines were reverted (upstream files pristine) and the chains migrated to the overrides file; verified end-to-end — with an upstream-clean sidecar, `CHAIN-HINT: after ak-cook …` still fires from overrides alone. See [ADR-0030](../../docs/adr/0030-operator-owned-chain-overrides.md).
   - **Epoch note:** chain-hint legs change behavior from this deploy — window any `analyze.py --chains` / hint-adoption metric from 2026-08-20, never pool across it.
2. **Record, don't build:** the outcome/`on_error` ledger leg as a future ADR candidate, contingent on first showing the current ledger's take-rate signal is even consumed.
3. **Nothing else from apb's router is worth the diff.**

## 5. Unresolved questions

- Which ak:* skills should own which successor lists is a curation judgment (owner's call) — the mechanism imposes no opinion.
- Whether an `outcome` event class is measurable without a new hook surface is unproven (no prototype built; read-only study).

**Process note:** executed as direct repo study + two scouts; the `study-extract-integrate` skill exists on the shelf as the formal wrapper for this task class and should front any follow-up integration work.
