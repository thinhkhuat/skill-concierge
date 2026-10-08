# Chisle audit brief (shared by every audit agent)

Repo: `/Users/thinhkhuat/in-PROD/MY-WORKBENCH/skill-concierge` (branch `main`, HEAD `692cab1`, v0.64.0).
Timezone Asia/Saigon. Write English.

## Your job

Audit ONLY your assigned area for bloat on two axes, and write your findings to the ONE file
named in your prompt. **Read-only everywhere else:** no edits, no git operations, no other files.

**Code (YAGNI axis):** reinvented stdlib; an abstraction with one implementation; a dependency
for what a few lines or an installed dep covers; an option or flag that never varies AND has no
documented revert reason; speculative scaffolding with no current caller; dead code (functions,
branches, constants, imports nothing reaches); duplicated logic that should be one function;
verbose code a native feature replaces.

**Prose (compression axis):** comments restating the code; padded docstrings; multi-paragraph
explanations one sentence carries; dead prose (stale TODOs, links to removed files, obsolete
sections describing behaviour the code no longer has).

## Do NOT flag

- Input validation at trust boundaries, error handling that prevents data loss, security, accessibility.
- Comments that explain WHY (a bug it works around, an incident, a measured number, an ADR reason).
- Runtime flags documented in `AGENTS.md` / `docs/runtime-flags.md`: each is a deliberate revert path.
- Fail-silent `try/except` in hooks: hooks must never break a turn (AGENTS.md Guardrails).
- `scripts/doctor.py` and `scripts/analyze.py` are stdlib-only BY RULE; do not suggest a dependency.
- Anything under `vendor/`, `docs/adr/`, `docs/journals/`, `plans/`, `tests/`.
- `// chisle:` or `# chisle:` marked shortcuts.

## Evidence rules (findings without evidence are discarded)

- "No caller" / "dead": prove it with `grep -rn '<symbol>' --include='*.py' --include='*.ts' --include='*.sh' --include='*.cjs' --include='*.json' .`
  (exclude `plans/`, `vendor/` only if the symbol is defined outside them). Quote the grep result count.
  Remember dynamic use: string-built names, `getattr`, CLI subcommands, hooks.json / settings.json wiring,
  `importlib`, tests importing the symbol (a symbol used ONLY by tests is still worth reporting, marked `test-only`).
- "Stale prose": name the code fact that contradicts it, with `file:line`.
- Mark a finding `(check)` when cutting it could lose behaviour you could not verify.
- Prefer fewer, high-confidence findings over a long speculative list.

## Output format (your findings file)

One line per finding, biggest cut first:

```
path:line  [code|prose]  <what's bloated> → <the lean replacement>. (~N lines)  confidence: high|medium|low  evidence: <grep count / file:line>
```

End with:

```
N findings: X code, Y prose. Est. removable: ~A lines code, ~B lines prose.
Biggest win: <one line>.
```

Then reply with: `Status: DONE | DONE_WITH_CONCERNS | BLOCKED` and a one-sentence summary.
