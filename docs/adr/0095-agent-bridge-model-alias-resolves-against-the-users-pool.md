# 0095 — The agent bridge resolves a Claude tier alias against the user's own model pool

- Status: accepted
- Date: 2026-10-16
- Deciders: Thinh: "we should translate any predefined in the o.g. Claude-style definition to the CURRENT user
  predefined models, either from the current session model, or the cmd config.json/settings.json — do NOT TRANSLATE
  BLINDLY." (after a live Command Code delegation warned `sub-agent "vn-editor-agent" … is configured with an unknown
  model "opus". Did you mean "claude-opus-5"?`, the harness's own suggestion naming a catalogue id rather than the
  user's actual model set).
- Relates to: ADR-0094 (the agent bridge, whose model clause this supersedes in part). Implementation:
  `scripts/cmd_agent_bridge.py` (`configured_models()`, `translate_model()`), `AGENT_BRIDGE_CONFIG` (env override),
  `tests/test_commandcode_agent_bridge.py`, `tests/conftest.py`.

## Context

ADR-0094 decided the bridge resets a non-Command-Code `model:` (a Claude tier alias such as `sonnet`) to `inherit`,
because the harness would drop the bare alias silently and change the model. That keeps the delegation working, but it
throws the author's tier intent away: an agent pinned `model: opus` as "the heavy model" silently becomes "whatever
the session runs", and the only feedback is that the harness's suggestion mechanic names the NEWEST catalogue id with
the matching family word — `claude-opus-5` — which may not even be on the user's plan. The mirror had three ends it
could choose between, and ADR-0094 picked the cautious one; live use showed the other two were wanted when legitimate,
never guessed.

The Command Code config (`~/.commandcode/config.json`) holds a pool of model ids the user has actually pre-picked:
the default `model`, the `featureModels` pair, the `reasoningEffort` keys, the `starredModels`. Every id in the pool
came through the `/model` picker on this machine, so every id already resolves there — the pool is a list of real
ids, not a catalogue.

## Decision

A Claude tier alias (`opus`, `sonnet`, `haiku`, `fable`, case-insensitive, with or without the `claude-` prefix) in
the source's `model:` resolves against that pool, in priority order (default model → `featureModels` →
`reasoningEffort` keys → `starredModels`), by same-family prefix (`claude-opus*`, `claude-sonnet*`, …):

- **A family the user currently configures translates to its family id.** `model: sonnet` → `claude-sonnet-5-5`
  when that id is pinned/effort-configured/… by the user. The note names the resolution.
- **A family the user does NOT currently configure does not translate at all** — no newest-catalogue guess and no
  fallback onto the session default (which could silently downgrade a heavy floor onto a flash tier). The field goes
  to `inherit`, with a note stating the rating: the alias belongs to the dispatcher per the o.g. definition's own
  convention (see the vn-editor-agent source: "the frontmatter field stays unset — a hardcoded `model: opus` fails
  the agent launch outright on non-Claude harnesses").
- **`inherit` and every real `/model` id pass through untouched**, as before; a non-id, non-alias value still goes to
  `inherit` with its drop-named warning, as before.
- `AGENT_BRIDGE_CONFIG` overrides the config path so tests read a fixture pool, never the machine's real one
  (`tests/conftest.py` forces a nonexistent path session-wide).

## Consequences

- The mirror keeps the user's tier intent when the user HAS a current model of that family, and hands the choice
  back to the session (exactly what `inherit` is documented to be) when they don't — never to the catalogue's
  suggestion list. `EMITTER_VERSION` bumps to 3 so the session-start hook rebuilds without a force flag.
- The alias table is Claude-tier-specific on purpose: it names the four words Claude Code's agent files pin. A
  mirror non-Claude alias (`gpt-4o` typed bare) stays in the drop-named `inherit` lane until a live corpus needs it.
- Supersedes, within ADR-0094's decision 3, only the sentence "a Claude alias like `sonnet` … resets to `inherit`
  with a warning". The rest of that ADR stands.
