# 2026-08-24 (afternoon–evening) — the dual-harness arc: six validation rounds, five releases, and the environment that lied

Fourteen commits, `7c3d89d..323a0a7`. Five releases, 0.25.0 → 0.26.2, both harnesses deployed
and live-verified. Four new ADRs (0034–0037). Three adversarial validation passes on the Claude
side, three live validation rounds on the Codex side — and the single most repeatable lesson of
the day is that **every producer-green artifact that skipped independent validation shipped a
defect, and every defect found was fixed same-day because the validator ran immediately.**

## The offer that lied about what it could do

The morning handoff left one material finding: with ADR-0033 indexing both harnesses into one
Qdrant collection, the per-turn installed offer spanned the union — so in a Claude session, 3–6
of 8 offer rows named Codex plugin skills the Skill tool cannot invoke. A row the agent cannot
act on is worse than no row: it burns a slot and invites a `USING:` the harness refuses.

ADR-0034 fixed it with the ADR-0032 shape one layer up: keep foreign rows out of the installed
offer, re-surface the strong ones in a marked `[codex]`/`[claude]` annex consumed via
`get_skill`. Measured end state: 18 of 48 non-invocable rows → 0, offers still full width.

## Three passes to get one feature right

The first implementation was wrong in a way my own green selftests could not see, and the second
implementation — the fix — introduced a new blocker. An independent validator caught both:

- **Pass 1 (FAIL):** a Qdrant `must_not scope` pre-filter deleted 24 `agent-skills:*` skills the
  session could invoke and labeled them "NOT invocable here." Root truth of the whole arc:
  **scope records where a skill's indexed copy lives; it is not invocability.** Claude Code
  layers `enabledPlugins` user → project → local; discovery reads the user file only, so a
  project-enabled plugin's Codex twin wins dedup. The fix is a per-session post-filter
  (`_invocable_twin`) in the hook — never in the machine-global index (the ADR-0028 hazard).
  Same pass: `Path("").resolve()` is the cwd, and OR-ing over `env or ""` turned harness
  detection into a CWD probe.
- **Pass 2 (FAIL):** my pass-1 fix put `Path.cwd()` at module scope — a deleted worktree turned
  the fail-silent hook into a traceback on every turn. And the "unknown" twin path did the exact
  opposite of its docstring: unknown filtered *everything*. The repaired rule: **condition a
  destructive branch on positive knowledge, never on the absence of a negative.**
- **Pass 3 (PASS)** — with three advisories, all fixed, including a pre-existing unguarded
  `Path.cwd()` in the chain-hint path that silently cost whole offers.

The producer's selftests were green through both failures because they pinned the mechanism
while the bugs lived in the premise. That is what an adversarial pass is *for*.

## Codex, live: the organ that was silently dead

Handing validation prompts to a live Codex session (three rounds, each a written report in
`plans/reports/`) found what no Claude-side pass could:

- **Round 1:** the retrieval organ did not exist in Codex sessions — 248 tools, zero
  skill-search. Codex expands `${CLAUDE_PLUGIN_ROOT}` in plugin *hook* commands and leaves it
  literal in plugin *MCP* commands (openai/codex#35762). ADR-0035: a Codex-specific descriptor
  with a relative command resolved against `"cwd": "."` — Codex's native plugin-root mechanism.
  The outage had been invisible in every metric because the enforcer offer queries Qdrant over
  REST and kept logging normally.
- **Round 2:** retrieval end-to-end PASS; four telemetry/test-harness defects, all fixed
  (selftest harness-direction pin; underscore-normalized tool names as dormant ledger armor;
  doctor's durable-home trigger resolution; and ADR-0037 — see below).
- **Round 3:** clean sweep, seven for seven, zero defects.

ADR-0037 deserves its own line: the Codex MCP's pinned cwd derives a **phantom manifest key**
nothing ever writes, so health reported "degraded — never indexed" forever against a fresh
shared collection, with a "run reindex()" whose obedience would have indexed under the phantom
root. The engine now borrows the newest *other* root's manifest for freshness — and keeps
staleness honestly `None`, because the borrowed signature belongs to another cwd. Unknowable is
not false.

## The fixed "2" becomes a read of the inventory

With the plumbing proven, the operator asked for the day's one pure feature: replace the
hardcoded 2-slot annexes with something that reads intent against inventory. The data made the
design: the 0.40 floor discriminates *nothing* (the 1.9k-skill external pool clears it 8+ deep
on every turn), and on the compressed mpnet band only a tight margin separates anything —
0.10 saturates, 0.05 discriminates. ADR-0036: an annex row earns its slot by scoring within
0.05 of the top installed row, caps 4/2. Strong inventory → annex shrinks to 0–1 (less noise
than the old fixed 2); thin inventory → widens to cap. The annex width itself is now the glance
the operator asked for. Round 3 verified the same behavior from the Codex direction.

## The environment that lied, three ways in one day

The quiet thread through everything: `~/.claude/settings.json`'s `env` block is a
**Claude-only environment**, and three separate incidents traced to forgetting that —
the flywheel invisible from Codex; a `CLAUDE_PLUGIN_ROOT` literal that masked a real Codex-side
selftest failure on this machine; a bash-profile export of the expanded path that would invert
harness detection for any non-Claude harness born of a bash login shell.

The closing fix gave shared env one canonical home: `~/.config/harness-env.sh` (0600), sourced
from `~/.zshenv` — the file that reaches every zsh, which on this machine means everything —
plus the bash entry files, verified from clean `env -i` across six launch shapes. And one
correction I owe the record: I first removed that `CLAUDE_PLUGIN_ROOT` literal as "debris,"
then found it is the deliberate hookify workaround (claude-code#46915) feeding user-level hooks
by two-stage shell expansion, and restored it same-session. **An ugly config value is not
debris until its consumer is proven absent.** Caveats §20 now holds the whole class.

## What carries forward

- The validation cadence is not overhead; it is the reason five releases in one day shipped
  with every known defect closed. Producer-green ≠ correct — six of six rounds proved it.
- `scope` ≠ invocability; settings env ≠ machine env; unknowable ≠ false; a positive-knowledge
  condition beats a negated-unknown every time.
- Open, recorded, deliberate: D3-class twin-blindness under Codex (a TOML-readable path or
  sidecar manifest is a product decision); Codex fires no PostToolUse, so its skill-use stays
  ledger-invisible (underscore armor pre-fitted for the day that changes).
