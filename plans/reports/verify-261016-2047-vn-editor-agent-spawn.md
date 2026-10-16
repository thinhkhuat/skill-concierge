# Verification — vn-editor-agent spawn after the model-floor fix

| | |
|---|---|
| **Validated** | 2026-10-16 20:47 (+07) |
| **Claim under test** | "The vn-editor agent spawn failure is fixed in another session" |
| **Original failure (this session, earlier)** | `agent` + `subagent_type: vn-editor-agent` + `model: "opus"` → rejected: `Sub-agent "vn-editor-agent" (/Users/thinhkhuat/.commandcode/agents/vn-editor-agent.md) is configured with an unknown model "opus". Did you mean "claude-opus-5"? Run /model to see the available models, or drop the model: line to inherit the session's model.` |
| **Method** | verify-as-claimed — live probes against the real spawn path, exact original failing call replayed, raw output below |

---

## 1. The artifact (read this turn)

`/Users/thinhkhuat/.commandcode/agents/vn-editor-agent.md` frontmatter, now:

```
# MODEL FLOOR (rewritten 2026-09-01, user order): opus-class or above, passed
# EXPLICITLY in the spawn call by the dispatcher. The frontmatter field stays
# unset — a hardcoded `model: opus` fails the agent launch outright on
# non-Claude harnesses (observed), a total outage worse than the silent
# downgrade the field once guarded against. Revert = restore `model: opus`.
tools: "*"
```

No `model:` field in the frontmatter. So the fix's shape: the agent definition no
longer pins the model; the dispatcher passes one explicitly per spawn.

## 2. Live probes (raw outputs, this turn)

**Probe 1 — the exact original failing call (`model: "opus"`):**

```
Sub-agent "vn-editor-agent" (/Users/thinhkhuat/.commandcode/agents/vn-editor-agent.md) is configured with an unknown model "opus". Did you mean "claude-opus-5"? Run /model to see the available models, or drop the `model:` line to inherit the session's model.
```

Spawn refused; no agent ran.

**Probe 2 — exact model id (`model: "claude-opus-5"`), trivial read-only task:**

```
spawn-ok v1.2.0

<usage>total_tokens: 148922  tool_uses: 1  turns: 2  duration_ms: 9340</usage>
```

**Probe 3 — no model line (inherit session model):**

```
spawn-ok v1.2.0

<usage>total_tokens: 563171  tool_uses: 1  turns: 2  duration_ms: 47819</usage>
```

All three probes used the same one-line task (read the SKILL.md `version:` line,
answer `spawn-ok v<X.Y.Z>`, edit nothing) — the agent under test edited nothing.

## 3. Verdict per case

- **Probe 1 — FAIL, reproduces the original error verbatim.** The bare alias
  `"opus"` in the spawn call is still rejected by Command Code's model resolution.
  The fix did not touch this path — and per the artifact's own comment it was not
  meant to: the rewritten MODEL FLOOR addresses the frontmatter-pinned model, not
  the spawn-call alias.
- **Probe 2 — PASS.** Exact id spawns and runs; the agent read the SKILL.md and
  reported `v1.2.0`, which matches the version on disk (verified this session
  earlier against `references/changelog.md`).
- **Probe 3 — PASS.** Frontmatter-unset fallback works: spawn inherits and runs.

## 4. Synthesis

**The fix is validated for what it changed** — the agent definition no longer pins
a model, so plain spawns and explicit-exact-id spawns both work where the old
hardcoded `model: opus` frontmatter would have failed outright. **One failure mode
survives and is real, not fixture noise:** Command Code refuses the bare alias
`"opus"` in a spawn call's `model:` field, exact vendor-qualified id
(`claude-opus-5`) only. The error message itself points the way ("drop the
`model:` line to inherit", or use the exact id).

**Operational rule that follows (for every dispatcher, this harness):** spawn
vn-* agents either with no `model:` line, or with the exact id — never the bare
alias. The agent definition's own comment ("passed EXPLICITLY in the spawn call by
the dispatcher") plus the two passing probes confirm the intended usage works.

## 5. Open items

1. **(Resolved in a follow-up probe, same turn.)** The alias refusal is a shipped
   model **catalog** lookup, not a user-configurable alias map. Evidence from
   `/opt/homebrew/lib/node_modules/command-code/dist/cli.mjs` (read this turn):
   `describeUnknownSubagentModel` accepts a model only when
   `knownModelIds.includes(canonicalizeModelId(...))`, where `listKnownModelIds`
   reads `resolveCatalog(catalog).catalog.models` — a bundled catalog. Bypasses
   exist for empty `knownModelIds` and for BYOK models (`e.isByok?.({model})`).
   Your `config.json` carries `model` / `featureModels` / `starredModels` but no
   alias map, so `model: "opus"` in a spawn call cannot be made to work by
   config; the catalog id or the no-model-line form are the two working forms.
   The fix from the other session (`cmd_agent_bridge.py::translate_model`,
   regenerating agent mirrors: "a Claude alias is not [a Command Code id] and
   would be dropped by the harness: -> inherit") lives at the *definition* layer
   — which is exactly why the frontmatter in the artifact above is now unset.
   The dispatcher call-arg layer is untouched by it and stays strict.
2. The other harnesses named in the MODEL FLOOR comment (non-Claude) were not
   probed — out of scope here; the comment records their failure as already
   observed.

---

## Addendum — 2026-10-16, the implementing session (agent bridge), landed at its owner home

This report was written one root above the repo it is about (`~/in-PROD/MY-WORKBENCH/plans/reports/`);
it now lives in `skill-concierge/plans/reports/`, where artifacts about this bridge belong. Three
items recorded with evidence so the file is complete and correct where it now lives.

**1. One attribution in §5.1 is corrected.** The report credits
`cmd_agent_bridge.py::translate_model` for the artifact's unset frontmatter. The source
(`~/.claude/agents/vn-editor-agent.md`) carries **no `model:` line at all** (grep, this turn), and
across the 45 mirrored sources the only model line present is `model: inherit` (20 files) — already
a legal Command Code id. So `translate_model` rewrote nothing live: probe 3's success rests on the
source's own 2026-09-01 MODEL FLOOR rewrite plus the bridge's byte-faithful passthrough. The
alias→`inherit` rewrite path stays test-exercised (`tests/test_commandcode_agent_bridge.py`) and
fires only if a future source pins a Claude alias.

**2. The protections the implementing session applied** (file:line, read this turn):

- `scripts/cmd_agent_bridge.py:451` — build refuses a symlinked destination, so the mirror can never
  write through `~/.claude/agents`.
- `scripts/cmd_agent_bridge.py:441-443,:476` — every source is SHA-256'd into `_agent_bridge.json`,
  and `verify` fails the moment a source drifts: silent source edits are impossible.
- `scripts/cmd_agent_bridge.py:619` — `verify` re-checks every mirrored `tools:` token (translation
  table target, `*`, or `mcp__*`) and requires the tools line to exist (omission = no tools in
  Command Code); `:670` — `clean` deletes only manifest-named files.
- `scripts/cmd_agent_bridge.py:324` — a non-Command-Code `model:` is rewritten to `inherit` with an
  explicit note, never left to be dropped in silence.
- `adapters/commandcode/install.sh:330,:338,:345-359` — the installer records the symlink target and
  restores it verbatim (`agent_restore`) if the mirror build or its check fails.

**3. Unresolved, needs the owner's one word.** The handback phrase "the router 445/53 forwards" does
not resolve on disk: the literal `445/53` appears in no today-dated file (searched this report,
`skill-concierge/plans`, `MY-WORKBENCH/plans`, `~/.commandcode/plans`); the only hits are a
2026-07-09 index-split plan and scratch HTML. Name the file or check it points at and this addendum
closes.
