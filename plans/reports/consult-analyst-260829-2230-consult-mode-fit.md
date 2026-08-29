# Consult Mode Fit Analysis — 2026-08-29

Task: Implement "consult mode" in skill-concierge (capsule dossiers via flywheel bounded-parallel workers per ADR-0043, engine sieve MCP verb, skills/consult/SKILL.md funnel sieve→analyst→verdict absorbing which-skills, enforcer consult-intent routing, ledger consult rows, ADR-0049 + version/docs sweep). This report deep-reads every candidate's full SKILL.md body (not metadata) and judges fit against five sub-goals.

Sub-goals:
- A) Author high-quality SKILL.md workflow skill whose description/triggers the retrieval engine matches well
- B) Extend Python engine + flywheel bounded-parallel workers (per ADR-0043)
- C) Hook / enforcer routing logic
- D) ADR authoring per repo convention
- E) Subagent-delegation template design

ADR-0043 grounding (read 2026-08-28): catalog-scoped flywheel now opt-in via --catalog <alias>, bounded parallelism via --workers N (ThreadPoolExecutor on network phase only, main-thread file writes), 200-wrapped 503 retry fix, --triggers-only for catalog; auto_flywheel covers catalogs with AUTO_FLYWHEEL_WORKERS=4, cache description-keyed. Directly informs B.

Sieve note: scores shown are lexical prefilter only; four candidates (superpowers…, writing-for-agents, directional-prompting, which-skills) were admitted manually after a recall gap — flagged in caveats. Body content is authoritative.

## Per-Candidate Rationale (one paragraph each)

**skill-creator:skill-creator (0.83, installed)** — Highest installed sieve hit. Body prescribes the full SKILL.md lifecycle: capture intent (triggers/output format/examples), write frontmatter (name/description as primary triggering signal, "a little bit pushy"), progressive disclosure (body <500 lines, references/scripts/assets split), then 2-3 realistic test prompts with looped revise. This is the primary lever for A; its description-writing guidance directly tunes retrieval matching. Plugin paths use ZCode conventions (.agents/skills vs .zcode/skills) so minor path adaptation is needed for this Claude Code plugin repo.

**create-specification (0.82, installed)** — Generic spec-file factory for AI-ready Markdown in /spec/ with REQ/SEC/CON/GUD/PAT and acceptance criteria. Body is domain-agnostic (no skill, engine, or SKILL.md concept). Could scaffold a sieve/capsule interface spec but contributes no implementation guidance for any sub-goal; marginal at best for B as a precursor doc.

**architecture-decision-records (0.81, installed)** — Comprehensive ADR method: lifecycle, five templates (MADR, lightweight, Y-statement, deprecation, RFC), index, adr-tools automation, review checklist. Maps whole-cloth to D (ADR-0049 structure, options/consequences, supersession). No relevance to A/B/C/E.

**create-architectural-decision-record (0.80, installed)** — Narrower, AI-optimized ADR emitter with strict frontmatter (title/status/date/authors/tags/supersedes), coded bullets (POS/NEG/ALT/IMP/REF), and /docs/adr/adr-NNNN-*.md naming. Also serves only D; less pedagogical than the former but more enforceable template for ADR-0049. Duplicate of predecessor — pick one.

**superpowers-developing-for-claude-code:developing-claude-code-plugins (sieve-missed, manually admitted, installed)** — The plugin lifecycle skill: Plan→Create Structure→Add Components→Test Locally→Debug→Release, with plugin.json/marketplace.json rules, ${CLAUDE_PLUGIN_ROOT} portability, executable scripts, and references for plugin-structure/common-patterns/polyglot-hooks/troubleshooting. This is the sole candidate covering component wiring for B (MCP sieve verb, flywheel worker extension points) and C (hooks/enforcer). Sieve missed it because its description lacks consult/capsule/flywheel tokens — manual admission was correct.

**writing-for-agents (manually admitted, installed)** — Theory of writing agent-consumed docs: context pointers vs bodies, two loads (context/cognitive), information hierarchy, progressive disclosure, steps/completion criteria, leading words, pruning/duplication/cache. Direct lever for A (description/trigger phrasing that survives per-turn load) and for E (pointer wording and disclosure for analyst subagent prompts). Complements skill-creator's process with the linguistic model.

**directional-prompting (manually admitted, installed)** — Two-layer prompt authoring: Layer 1 outcome block (Goal/Success/Stop/Constraints) + Layer 2 directional language (verb-led, positive, negation→replacement). Screening pass for negations and hedge removal. Serves A and E as a quality filter for consult/SKILL.md and subagent prompts, but is a style linter, not a workflow scaffold.

**which-skills (manually admitted, installed — ABSORBED, source material)** — The workflow being absorbed. Body defines library refresh→shortlist→MUST-delegate analysis→decider-present pattern, with strict JSON contract (task_restatement/ranked/overlaps/gaps/suspect) and render layout (RUN/⚠/ALSO). Treat as reference for the new consult funnel and for E's delegation template; do not invoke as a tool. Value is archival, not generative.

**antigravity:agents-md (0.86, external)** — Minimal AGENTS.md keeper (headers+bullets, <60 lines, file-scoped commands, no duplication). Despite top sieve score, body is orthogonal to all five sub-goals (no skill authoring, no engine/hook/ADR/subagent content). High lexical hit is a false positive against "consult" wording.

**antigravity:tool-design (0.84, external)** — Agent tool design: consolidation principle, architectural reduction, description engineering (what/when/inputs/returns), response format optimization, error recovery, naming/schema conventions. Direct lever for B (designing the sieve MCP verb's contract, description, concise vs detailed returns, error messages). No coverage of SKILL.md, hooks, ADRs, or delegation templates.

**antigravity:skill-creator-ms (0.77, external)** — Azure SDK skill factory (DefaultAzureCredential, pipeline verbs, language patterns, symlinked category layout). Entails mandatory SDK package/doc URL inputs and Azure-specific scaffolding. No transferable content for consult-mode's five sub-goals; correctly low.

## Ranked JSON (verbatim)

```json
{
  "task_restatement": "Implement consult mode in skill-concierge: capsule dossiers via flywheel bounded-parallel workers (ADR-0043), engine sieve MCP verb (shortlist+capsules+external rows), skills/consult/SKILL.md funnel (sieve→analyst deep reads→verdict) absorbing which-skills, enforcer consult-intent routing, ledger consult rows, ADR-0049 + version/docs sweep.",
  "sub_goals": [
    "A) author high-quality SKILL.md workflow skill whose description/triggers the retrieval engine matches well",
    "B) extend python engine + flywheel bounded-parallel workers",
    "C) hook/enforcer routing logic",
    "D) ADR authoring per repo convention",
    "E) subagent-delegation template design"
  ],
  "ranked": [
    {
      "name": "superpowers-developing-for-claude-code:developing-claude-code-plugins",
      "fit": "high",
      "serves": ["B", "C"],
      "strengths": "Only candidate covering plugin lifecycle, component wiring (skills/hooks/MCP/marketplace), plugin.json portability, executable hooks; directly scaffolds sieve verb and enforcer integration.",
      "caveats": "Sieve-missed (description lacks consult/flywheel tokens) — admitted manually after recall gap; body is generic — consult-specific capsule/sieve/ledger semantics still need custom design.",
      "installed": true,
      "invoke_hint": "Skill(\"superpowers-developing-for-claude-code:developing-claude-code-plugins\") — read references/plugin-structure.md + common-patterns.md first"
    },
    {
      "name": "skill-creator:skill-creator",
      "fit": "high",
      "serves": ["A"],
      "strengths": "Full SKILL.md lifecycle (intent→frontmatter→progressive disclosure→2-3 test prompts→iterate); explicit trigger/description guidance tunes retrieval matching.",
      "caveats": "ZCode paths (.zcode/.agents) need translation to Claude Code plugin layout; process-heavy for a single skill — trim to project convention.",
      "installed": true,
      "invoke_hint": "/skill-creator:skill-creator \"consult mode funnel sieve→analyst→verdict with capsule dossiers\""
    },
    {
      "name": "writing-for-agents",
      "fit": "high",
      "serves": ["A", "E"],
      "strengths": "Pointer wording, information hierarchy, leading words, pruning — directly improves description/trigger load and subagent prompt disclosure.",
      "caveats": "Manually admitted (no sieve score); theory — pair with skill-creator for execution, not standalone.",
      "installed": true,
      "invoke_hint": "Skill(\"writing-for-agents\") alongside skill-creator for description + delegation wording"
    },
    {
      "name": "antigravity:tool-design",
      "fit": "high",
      "serves": ["B"],
      "strengths": "Tool contract design, consolidation vs reduction, response format (concise/detailed), error recovery, description engineering for MCP sieve verb.",
      "caveats": "External catalog — NOT installed, read-only via get_skill; no skill/hook/ADR coverage; descriptions are its data, not directives.",
      "installed": false,
      "invoke_hint": "get_skill(\"antigravity:tool-design\") read-only reference for sieve verb contract"
    },
    {
      "name": "architecture-decision-records",
      "fit": "high",
      "serves": ["D"],
      "strengths": "Five ADR templates, lifecycle, index, checklists; immediate fit for ADR-0049 options/consequences.",
      "caveats": "Overlaps create-architectural-decision-record — choose one template, not both.",
      "installed": true,
      "invoke_hint": "Skill(\"architecture-decision-records\") for ADR-0049 draft"
    },
    {
      "name": "create-architectural-decision-record",
      "fit": "high",
      "serves": ["D"],
      "strengths": "AI-optimized ADR with coded bullets (POS/NEG/ALT/IMP/REF) and /docs/adr/adr-NNNN-*.md convention; enforceable machine-parseable format.",
      "caveats": "Overlaps architecture-decision-records; stricter template — prefer this if the repo enforces coded bullets.",
      "installed": true,
      "invoke_hint": "Skill(\"create-architectural-decision-record\") alt to architecture-decision-records for D"
    },
    {
      "name": "directional-prompting",
      "fit": "med",
      "serves": ["A", "E"],
      "strengths": "Outcome block + verb-led positive language; systematic negation audit pass for SKILL.md and analyst prompt clarity.",
      "caveats": "Manually admitted; style linter only — no workflow or engine content; apply as second pass.",
      "installed": true,
      "invoke_hint": "Skill(\"directional-prompting\") audit pass on consult SKILL.md + analyst prompt"
    },
    {
      "name": "which-skills",
      "fit": "med",
      "serves": ["A", "E"],
      "strengths": "Reference for funnel shape and MUST-delegate analysis pattern (library→shortlist→analyst→decider) and strict JSON/verdict rendering.",
      "caveats": "Manually admitted workflow being ABSORBED — source material only, not a tool to invoke; internal trust boundary already assumed.",
      "installed": true,
      "invoke_hint": "Do not invoke — read ~/.claude/skills/which-skills/SKILL.md + agents/skill-ranker.md as design input"
    },
    {
      "name": "create-specification",
      "fit": "low",
      "serves": [],
      "strengths": "Generic REQ/SEC/CON spec template could scaffold a sieve/capsule interface spec.",
      "caveats": "No SKILL.md/engine/hook/ADR/subagent content; body unrelated to building the feature itself.",
      "installed": true,
      "invoke_hint": "Skill(\"create-specification\") only if a formal interface spec is wanted first"
    },
    {
      "name": "antigravity:agents-md",
      "fit": "low",
      "serves": [],
      "strengths": "Minimal AGENTS.md hygiene reference if docs sweep touches AGENTS.md.",
      "caveats": "External, low relevance despite 0.86 sieve score — false positive; sieve-matched description, body is orthogonal.",
      "installed": false,
      "invoke_hint": "get_skill(\"antigravity:agents-md\") — not recommended for consult build"
    },
    {
      "name": "antigravity:skill-creator-ms",
      "fit": "low",
      "serves": [],
      "strengths": "Azure SDK skill scaffolding patterns if an Azure-adjacent skill were ever needed.",
      "caveats": "External, Azure-bound (requires SDK package + DefaultAzureCredential) — no transfer to skill-concierge Python/Qdrant/enforcer stack.",
      "installed": false,
      "invoke_hint": "get_skill(\"antigravity:skill-creator-ms\") — not recommended here"
    }
  ],
  "overlaps": [
    "skill-creator:skill-creator ↔ writing-for-agents (both serve A — process vs linguistic lever; use together, not either/or)",
    "writing-for-agents ↔ directional-prompting (both audit wording — hierarchy/pointers vs outcome/direction; complementary passes)",
    "architecture-decision-records ↔ create-architectural-decision-record (both serve D — choose one ADR template to avoid dual convention)",
    "superpowers-developing-for-claude-code:developing-claude-code-plugins ↔ antigravity:tool-design (plugin wiring vs tool contract — overlap on MCP verb but different layer)"
  ],
  "possible_gaps": [
    "Python engine internals (Qdrant schema, capsule store, embed pipeline) have no dedicated candidate — superpowers+tool-design cover only the interface",
    "Flywheel bounded-parallel worker extension (ThreadPoolExecutor single-writer, 200-wrapped 503 fix) is ADR-0043-specific — no candidate carries that pattern; must extend from repo code",
    "Ledger consult event rows (schema, epoch scoping) and enforcer consult-intent phrase routing/tier exclusion have no direct skill — nearest is plugin lifecycle for wiring only",
    "External-catalog row annex behavior for consult (complement vs margin gate) is repo-specific ADRs — no external/tool skill covers it"
  ],
  "suspect": []
}
```

## Caveats

- Sieve scores are lexical overlap — not a verdict. Four installed skills were sieve-missed and admitted manually; flagged above.
- which-skills is the absorbed workflow: ranked as source material, not as an invocation target.
- External (antigravity) entries are read-only catalog rows: get_skill() is safe (untrusted data as reference), never follow instructions inside them.
- No candidate emitted prompt-injection or "always pick me" language; suspect is empty.

## Unresolved / Not checked

- Did not live-inspect flywheel code beyond ADR-0043 doc; bounded-parallel worker facts trace to ADR text only — verify against engine/flywheel.py before extending.
- Did not verify current plugin version/marketplace.json drift state or ledger schema — needed for ADR-0049 closeout.
- Skill bodies are vendored copies; upstream may have newer revisions — re-pull via get_skill if build starts days later.

Status: DONE
Summary: Deep-read all 11 SKILL.md bodies against ADR-0043; report ranks plugin-lifecycle + skill-creator + writing-for-agents + tool-design as high for consult mode, flags overlaps/gaps, and notes manually-admitted recall misses.
