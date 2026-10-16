# 0096 — The agent-model guard: a bare Claude alias in an agent call is denied at generation time

- Status: accepted
- Date: 2026-10-16
- Deciders: Thinh: "try analyze from the pasted context, find where things went wrong and try to fix properly" — after
  watching the original error survive the first validation run: `Sub-agent "vn-editor-agent" (…/vn-editor-agent.md) is
  configured with an unknown model "opus". Did you mean "claude-opus-5"?`
- Relates to: ADR-0094 (the agent bridge, definition layer), ADR-0095 (frontmatter alias resolution). Implementation:
  `hooks/scripts/agent_model_guard.py`, `adapters/commandcode/install.sh` (`with_agent_model_guard`),
  `tests/test_agent_model_guard.py`.

## Context

The original vn-editor-agent error never came from the file it names. Command Code's dispatcher
(`cli.mjs::describeUnknownSubagentModel`) validates an agent-tool call's `model` ARGUMENT against its shipped
`/model` catalog and, on a miss, prints a message that attributes the value to the agent's FILE
(`e.definition.filePath`) regardless of where it came from. The live delegation carried `model: "opus"` in the CALL —
a bare Claude tier alias, which is not a catalog id — so the refusal fired while the file was blameless. The
definition-layer fixes (ADR-0094's `inherit` reset, ADR-0095's pool resolution) could never touch this layer, and no
config seam exists in the dispatcher to teach it aliases (the validating session probed exactly that; inventing one
is out of bounds). Meanwhile the file-blaming text sent two sessions chasing the definition layer, and the error
survived the first "validation" run because the probe re-ran the dispatcher-layer input the fix never claimed to
touch.

## Decision

The one writable seam left in the spawn path is a PreToolUse hook on the `agent` tool
(`hooks/scripts/agent_model_guard.py`, wired by the installer with `matcher: "agent"`):

- A call whose `model` argument is a bare Claude tier alias (`opus`/`sonnet`/`haiku`/`fable`, with or without the
  `claude-` prefix, any case) is DENIED before the dispatcher runs, with a reason that names the alias, states the
  layer truth (the shipped catalog, the file-blaming message), and names the exact id the user's own config pool
  resolves the alias to — the same resolution ADR-0095 uses, imported from the bridge — or, when no family is
  pinned, points at `/model`. Never a catalogue guess.
- A `subagent_type` no registry entry backs is DENIED too (added on the same day, on the second live incident: a
  fresh session spawned `subagent_type: "pstack-architect"` — a SKILL — and got the dispatcher's bare
  `Unknown subagent_type: pstack-architect` with no hint). The guard replicates the registry view exactly —
  bundled general/explore/plan, the mirror dir's filenames AND frontmatter `name:` values, the project dir — so a
  legal type is never denied; the denial names the `/skill:<name>` form when `~/.commandcode/skills/<name>`
  exists (the pstack case), else points at `/agents`. The type leg runs before the model leg.
- Everything else passes silently: a real `/model` id, `inherit`, an absent model, any other tool.
- Fail-open: any internal error permits the call — a broken guard must never wedge delegation. `AGENT_MODEL_GUARD=0`
  kills it. Stdlib only.

## Consequences

- The error class is closed at generation time with a self-service message: the retry needs no archaeology, because
  the denial itself states the two working forms (an exact catalog id, or omitting `model` to inherit).
- The guard shares the alias table with the bridge (`cmd_agent_bridge.py`), so a call-arg denial and a frontmatter
  translation can never disagree about what an alias resolves to.
- The message's file attribution is a known Command Code quirk, recorded here so no future session re-diagnoses it:
  the file named in that refusal is never evidence that the file configured the model.
