# Proposal — ZCode as the fifth first-class harness (ADR-0042 draft)

Date: 2026-08-28 · Studied live from inside a ZCode session (evidence cited per finding).

## 1. Current state, measured

ZCode already runs the plugin natively — it recognizes `.claude-plugin/` manifests, fires
Claude-format plugin hooks, and injects `additionalContext`. Verified working TODAY under ZCode
(v0.20.8 cache, installed 2026-08-16 from the `skill-concierge` marketplace → GitHub repo):

| Organ | Status under ZCode | Evidence (this session, 2026-08-28) |
|---|---|---|
| Doctrine (SessionStart) | ✅ fires, injects | SKILL-FIRST standing order present in session context |
| Enforcer (UserPromptSubmit) | ⚠️ fires, but 0.20.8-era and mis-identified | ledger `offer` row for this session's prompt; externals rendered as plain installed rows (pre-0.23 behavior); no `harness` stamp (pre-0.29) |
| Ledger (PostToolUse) | ✅ fires | `auto` rows for `ak:code-review`, `zcode-guide:diagnosing-hooks` (Skill-tool matcher matches; ZCode's flattened MCP tool names match the 0.29 suffix-tolerant matchers) |
| Retrieve (MCP `search_skills`) | ❌ **dead — no tools in any ZCode session** | reproduced: `Permission denied` on manual spawn |
| Self-heals (auto_reindex/overrides/flywheel) | ⚠️ fire detached, but auto_overrides writes `~/.claude/settings.json`, which ZCode never reads | hooks.json entries fire; ZCode has no skillOverrides seam |
| keep-on budget organ | ❌ N/A under ZCode | ZCode injects every discovered skill's full description (this session's context carries ~500 of them); config.json only offers binary skill disable, no name-only tier |

## 2. Root causes (all reproduced, not inferred)

1. **The MCP launcher loses its exec bit in ZCode's plugin cache.**
   `~/.zcode/cli/plugins/cache/skill-concierge/.../0.20.8/bin/skill-search-mcp` is `-rw-r--r--`;
   the Claude cache copy of the same file is `-rwxr-xr-x`. Manual spawn: `Permission denied`
   before any protocol handshake. ZCode's own `diagnosing-hooks` pitfall 4 names this class and
   the cure: *invoke through an interpreter so the executable bit is irrelevant.*
2. **The ZCode plugin cache is 13 versions stale (0.20.8 vs 0.33.1).**
   Marketplace `skill-concierge` last updated 2026-08-16. The running enforcer therefore predates
   external-annex markers (0.23), cross-harness offer isolation (0.25), dynamic annex sizing
   (0.26), harness stamps (0.29), multi-intent/route (0.32).
3. **Harness mis-detected as `claude`.** `_running_harness()` checks `SKILL_CONCIERGE_HARNESS`,
   `OMPCODE`, then `.omp`/`.codex`/`.claude` path markers, then falls back to `"claude"`. The
   ZCode hook's `CLAUDE_PLUGIN_ROOT` resolves to `~/.zcode/cli/plugins/cache/...` — no marker
   matches → `"claude"`. Consequences: the offer consults Claude's registries
   (`~/.claude/plugins/installed_plugins.json` + Claude settings `enabledPlugins`) instead of
   ZCode's (`~/.zcode/cli/plugins/installed_plugins.json` + `~/.zcode/cli/config.json`), and
   foreign-scope filtering uses Claude's set. **Live proof:** this session's offer included
   `add-harness-to-skill-concierge`, whose Qdrant point is scope `omp-managed` — an OMP-managed
   skill ZCode cannot invoke (absent from the session's skill list).
4. **Latent shared-venv downgrade ping-pong.** The launcher's ADR-0018 self-heal resyncs the
   venv engine FROM the deployed cache when versions differ. Venv is stamped 0.33.0; the ZCode
   cache says 0.20.8 — the moment MCP is fixed, every ZCode spawn would *downgrade* the shared
   venv to 0.20.8 until the next Claude spawn re-upgrades it. (Did not fire yet only because the
   exec bit killed the spawn first.)
5. **`.mcp.json` carries `${HOME}` in `SKILL_SERVER_RECORDS`.** ZCode expands templates only
   from a whitelist (`${CLAUDE_PLUGIN_ROOT}`/`${ZCODE_PLUGIN_ROOT}`, `${CLAUDE_PROJECT_DIR}`,
   `${user_config.*}`) and only for plugin-provided servers — `${HOME}` is not in the set. Same
   literal-variable class ADR/0.21.1 already fixed once for `SKILL_TRIGGERS` (absolute path).

### Key structural fact (simplifies everything)

`~/.agents/skills` **is a symlink to `~/.claude/skills`** — ZCode's ~400-skill shelf IS the
already-indexed `personal` scope (2,551 points). Genuinely new-to-index content is small:
`~/.zcode/skills` (27) + the ZCode plugin cache (~7 on installed paths, ~30 across all cached
versions, plus builtin plugins under `cache/zcode-plugins-official/` that live outside
`installed_plugins.json`). **This integration is a correctness job (identity + isolation + MCP),
not a corpus job.**

## 3. Proposed design (ADR-0042, follows the ADR-0039 template with two simplifications)

ZCode is the first harness in the set with **native Claude-format plugin-hook parity** — no mod
adapter (Command Code) and no extension module (OMP) are needed. The enforcement vehicle is the
existing shared `hooks/hooks.json`, unchanged.

### 3.1 Harness identity (`enforcer.py`, `doctrine.py`, `ledger.py`)

- `_running_harness()` returns `"zcode"`; new `UNDER_ZCODE` constant. Precedence:
  1. `SKILL_CONCIERGE_HARNESS=zcode`
  2. `ZCODE_PLUGIN_ROOT` env set — ZCode injects it (with `${CLAUDE_PLUGIN_ROOT}`) into
     plugin-hook processes, so it is a cheap positive signal available even before path checks
  3. `.zcode/` path marker on the existing `CLAUDE_PLUGIN_ROOT` / `__file__` candidate loop
     (cannot false-positive on Claude/Codex/OMP paths)
- `_foreign_scopes()` under zcode: `("plugin", "codex-plugin", "codex-personal",
  "commandcode-personal", "omp-personal", "omp-managed", "omp-plugin", "personal*")` —
  `personal` **pending twin test** (see below). `project:` scopes stay shared by construction.
  Foreign annex label: `"claude/codex/omp"` (compound label, Command Code precedent).
- `_invocable_plugin_ids()` under zcode reads `~/.zcode/cli/plugins/installed_plugins.json`
  (NOTE: `plugins` is a **list** of `{id, installPath, …}` — different shape from Claude's dict)
  gated by `~/.zcode/cli/config.json` → `plugins.enabledPlugins` (absent key = enabled, mirroring
  Claude's rule), and **unions the builtin roots** `cache/zcode-plugins-official/**` minus
  `suppressedBuiltins` (builtins are enabled-but-not-in-the-registry). Claude's registry is NOT
  consulted under zcode.
- `_invocable_twin()` under zcode becomes a **filesystem check** (exact, no registry guessing):
  a foreign-scoped row is rescued iff `<name>/SKILL.md` exists in a ZCode-readable root
  (`~/.agents/skills/`, `~/.zcode/skills/`). On this machine `~/.agents/skills → ~/.claude/skills`,
  so every `personal` row resolves — matching reality. On a machine where they diverge, only real
  twins survive. Unreadable root ⇒ treat as unknown ⇒ keep the row (ADR-0034's drop-only-on-
  positive-knowledge rule).
- `doctrine.py _harness_adapt()` gains a `zcode` branch: tool id
  `mcp__plugin_skill-concierge_skill-search__search_skills` (the flattened `plugin:<plugin>:<server>`
  form ZCode uses — same rendering Command Code needed; today the 0.20.8 cache doctrine carries it
  only because the cached file was hand-patched). Slash form: verify empirically whether ZCode
  resolves `/skill-concierge:skill-search` or the double-prefixed canonical form.

### 3.2 Discovery mirror (`skills_discovery.py`)

`SKILL_ZCODE_ROOTS` (default ON, one-var revert, `=0` + reindex ⇒ byte-identical):

| Root | Scope |
|---|---|
| `~/.zcode/skills` | `zcode-personal` |
| `<cwd>/.zcode/skills`, `<cwd>/.agents/skills` | `zcode-project:<abspath>` |
| ZCode plugin roots | `zcode-plugin` |

- **Do NOT add `~/.agents/skills` as a root** — it realpath-dedups into `personal` anyway; its
  ZCode-invocability is handled by the twin check (3.1), which is per-session and per-machine
  correct rather than baking a symlink assumption into the machine-global index (the ADR-0028
  hazard).
- Plugin roots are enumerated from `installed_plugins.json[].installPath` **plus builtin roots**,
  never a wholesale cache glob — the ZCode cache is append-only exactly like Claude's, and an
  unfiltered glob would index every stale version (the ADR-0028/0.19.0 pollution class). Glob
  both `skills/*/SKILL.md` and `skills/*/*/SKILL.md` (category-grouped plugins, the 0.25.0 fix).
- `visible_scopes()` gains the zcode scopes; `SKILL_ZCODE_ROOTS` joins the
  `auto_reindex._mcp_env()` forwarding tuple only if ever pinned in `.mcp.json` (the AGENTS.md
  invariant — default-on needs no pin).

### 3.3 MCP wiring (fixes root cause #1 and #5)

Two changes, both to the shared descriptor — no per-harness descriptor needed (the OMP happy
path, not the Codex `cwd` rewrite):

1. **Interpreter form, exec-bit-proof** (`.mcp.json`):
   `"command": "bash", "args": ["${CLAUDE_PLUGIN_ROOT}/bin/skill-search-mcp"]`.
   Works whether or not a cache copy preserves modes, in every harness that imports the plugin
   descriptor. This kills the failure class instead of chmod-ing after each update.
2. **Absolute path for `SKILL_SERVER_RECORDS`** (drop `${HOME}`) — config-file scopes never
   expand templates and ZCode's plugin whitelist doesn't include `${HOME}`.
3. Belt-and-braces: `adapters/zcode/install.sh` chmods the cached bins anyway, and
   `adapters/zcode/mcp.json` ships as the documented **manual fallback** (user-scope
   `~/.zcode/cli/config.json` → `mcp.servers.skill-search`, absolute paths — config-file servers
   must not use templates). Same duplicate-server caution as ADR-0039: when the plugin layer
   works, do not also write the user-scope entry.
4. Verification: restart ZCode → `mcp__plugin_skill-concierge_skill-search__search_skills`
   present in the tool list; `doctor`'s "MCP reachable" class of check extended to zcode.

### 3.4 Launcher downgrade guard (`bin/skill-search-mcp`)

The ADR-0018 self-heal becomes **one-directional**: resync only when the deployed cache version
is NEWER than the venv stamp (semver compare). A stale cache must never downgrade a newer shared
venv — warn on stderr, serve the existing engine. Protects any multi-harness machine even when a
marketplace copy goes stale again.

### 3.5 Ops mirror

- `scripts/doctor.py check_zcode()` (WARN-only, fail-open when `~/.zcode` absent): cache version
  vs SSOT, bin exec bits (+ `--fix` chmod), MCP server present (plugin layer or user scope),
  `zcode-*` scopes present in the index, hooks registered.
- `adapters/zcode/install.sh` (idempotent, mirrors commandcode/omp): marketplace update →
  chmod bins → optional user-scope MCP fallback → doctor check.
- Release rule: the version-bump ritual (4 manifests + package.json + CHANGELOG) gains "update
  the ZCode marketplace" — one command, and `check_zcode`'s version row makes skipping it loud.
- README harness-matrix row + uninstall section; `driftcheck.json` `paths_exist` += adapter
  files; `check_mcp_env_parity.py` covers `adapters/zcode/mcp.json`.
- **Ledger epoch boundary** at ship time (enforcer + discovery change); per the guardrails,
  pre-ship ZCode-session rows are a different epoch and never pooled with post-ship rates.

### 3.6 Accepted caveats (stated, not solved)

- **No budget organ under ZCode.** ZCode injects every discovered skill's full description; it
  has no `skillOverrides` seam. The enforcement organ (ranked offers) is the only lever. The
  27-skill `~/.zcode/skills` + plugin skills are resident regardless. Revisit if ZCode grows a
  description-budget setting.
- **Doctrine tool-name line under the other harnesses**: `_harness_adapt` already rewrites it
  per harness; the static line in `hooks/doctrine/skill-first.md` is the template, keep it
  harness-neutral (the current hand-patched flattened name should become the zcode/commandcode
  branch's substitution, not the global default).
- ZCode desktop vs CLI may diverge on config-file MCP parsing (diagnosing-mcp pitfall 13);
  the plugin-layer primary path avoids the desktop-managed list entirely.

## 4. Phased plan (each phase independently verifiable)

| Phase | Change | Verification bar |
|---|---|---|
| **0 — unblock retrieval** (ship alone if needed) | `.mcp.json` bash-interpreter form + absolute `SKILL_SERVER_RECORDS`; chmod cached bins; update ZCode marketplace to 0.33.x | ZCode session shows `search_skills` in tools; live query returns ranked rows; `doctor` MCP row green |
| **1 — discovery** | `SKILL_ZCODE_ROOTS` + reindex | scope histogram shows `zcode-personal` ≈ 27, `zcode-plugin` ≈ installed+builtin count; counts match disk; `=0`+reindex reverts |
| **2 — identity + isolation** | `_running_harness` zcode branch, `UNDER_ZCODE`, foreign scopes, zcode registries, filesystem twin, doctrine zcode branch | 20-prompt live sweep: 0 non-invocable rows in offers (ADR-0034 bar); ledger rows stamped `harness: "zcode"`; this session's `omp-managed` row class disappears |
| **3 — hardening + ops** | launcher downgrade guard, `check_zcode()`, install.sh, docs/driftcheck/parity, ADR-0042 | doctor green end-to-end; kill-switch revert proven byte-identical; epoch-scoped analyze baseline |

## 5. Why this shape (alternatives rejected)

- **No `adapters/zcode/` extension vehicle** — ZCode runs the shared hooks natively; an adapter
  would duplicate what already fires (contrast ADR-0038/0039, where the harness ignored hooks).
- **No wholesale cache glob for zcode plugins** — append-only cache ⇒ registry-enumerated roots
  (the pollution class is already documented twice in-repo).
- **No `~/.agents/skills` index root** — symlink twin of `personal`; per-session filesystem twin
  check is the correct seam (machine-global index must not bake a per-machine symlink).
- **Interpreter invocation over chmod-only** — chmod treats this cache copy; `bash <script>`
  treats every future copy, in every harness.
