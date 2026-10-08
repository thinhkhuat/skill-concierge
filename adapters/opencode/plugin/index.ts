/**
 * skill-concierge — OpenCode v2 plugin adapter (ADR-0085, octa-harness parity).
 *
 * A native OpenCode v2 plugin (`Plugin.define` shape: default-export { id, setup(ctx) } —
 * the zero-build local-plugin form; no @opencode/plugin import required, matching local
 * plugins OpenCode loads from `.opencode/plugins/` and path entries). Mirrors the OMP
 * adapter (adapters/omp/skill-concierge.ext.ts) — same resolvePluginRoot ladder, same
 * enforcer/ledger/doctrine/exclusions/self-heal scripts — mapped onto OpenCode v2's
 * surfaces:
 *
 * 1. `ctx.mcp.transform`: registers the skill-search MCP server (editor.set) from the
 *    repo's own .mcp.json — Claude Code's `${CLAUDE_PLUGIN_ROOT}` auto-connect parity,
 *    zero manual MCP config. A duplicate `skill-search` declaration elsewhere stays a
 *    hazard: this transform REPLACES the name, so it wins deterministically.
 * 2. `setup` body: fires the detached SessionStart-parity self-heal batch
 *    (auto_reindex / auto_overrides / auto_flywheel / auto_promote — each internally
 *    throttled and fail-silent).
 * 3. `ctx.session.hook("prompt")`: per admitted user prompt — logs the turn boundary to
 *    the shared invocation ledger and runs the semantic enforcer (bounded 10 s, the
 *    Claude Code UserPromptSubmit timeout parity); the resulting SKILL-FIRST block is
 *    stashed for the next agent-loop model call. The prompt text itself is NEVER edited
 *    (prompt-hook edits become the canonical persisted user input — governance text
 *    rides system parts instead).
 * 4. `ctx.session.hook("context")`: pushes the doctrine ONCE per session (SessionStart
 *    parity) and the pending per-turn enforcer block on the first agent-loop call after
 *    each admission (UserPromptSubmit additionalContext parity).
 * 5. `ctx.permission.hook("evaluate")`: action "skill" → delegates the user-ordered
 *    blocklist decision to hooks/scripts/skill_guard.py (the same denying gate Claude
 *    Code runs on PreToolUse(Skill), ADR-0046) and denies on its verdict. Fails OPEN on
 *    any internal error — a broken guard must never wedge skill invocation.
 * 6. `ctx.tool.hook("execute.after")`: PostToolUse parity — skill activations (the
 *    native `skill` tool) and retriever usage (`skill-search_search_skills` /
 *    `skill-search_get_skill`, the transform-registered effective ids) go to the ledger;
 *    a loaded skill's own "not for" lines echo back through skill_exclusions.py
 *    (ADR-0059), appended to the result's text content when the shape allows.
 *
 * Fail-open design: every handler catches exceptions and degrades to a no-op — this
 * plugin must never block a turn. The one denying path (the blocklist permission hook)
 * fails OPEN exactly like skill_guard.py itself.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

/** Harness stamp every spawned hook script runs under. */
const HARNESS = "opencode";

// Resolve plugin root — identical ladder to the OMP / Command Code adapters:
// 1. Explicit env `SKILL_CONCIERGE_ROOT`
// 2. The repo checkout this module lives in (adapters/opencode/plugin → ../../..)
// 3. The standard workbench checkout
function resolvePluginRoot(): string {
  if (process.env.SKILL_CONCIERGE_ROOT && existsSync(process.env.SKILL_CONCIERGE_ROOT)) {
    return process.env.SKILL_CONCIERGE_ROOT;
  }
  const candidate = resolve(__dirname, "../../..");
  if (existsSync(join(candidate, "hooks/scripts/enforcer.py"))) {
    return candidate;
  }
  const defaultPath = join(homedir(), "in-PROD/MY-WORKBENCH/skill-concierge");
  if (existsSync(defaultPath)) {
    return defaultPath;
  }
  return candidate;
}

const PLUGIN_ROOT = resolvePluginRoot();
const ENFORCER_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/enforcer.py");
const LEDGER_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/ledger.py");
const DOCTRINE_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/doctrine.py");
const GUARD_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/skill_guard.py");
const EXCLUSIONS_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/skill_exclusions.py");
const MCP_JSON = join(PLUGIN_ROOT, ".mcp.json");
// SessionStart self-heal batch (hooks/hooks.json parity). Each script is fail-silent,
// throttled, and spawns its own detached work; fired detached so plugin setup never waits.
const AUTO_SCRIPTS = ["auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"].map(
  (name) => join(PLUGIN_ROOT, "hooks/scripts", name),
);

/** The MCP server config OpenCode should run, read from the repo's own .mcp.json so the
 * plugin and every other harness share ONE source of truth (setup.sh reads the same file
 * to build the index). `${CLAUDE_PLUGIN_ROOT}` is expanded to this checkout. */
function mcpServerConfig(): Record<string, unknown> | null {
  try {
    if (!existsSync(MCP_JSON)) return null;
    const parsed = JSON.parse(readFileSync(MCP_JSON, "utf-8"));
    const row = parsed?.mcpServers?.["skill-search"];
    if (!row || !Array.isArray(row.args)) return null;
    const args = row.args.map((a: unknown) =>
      typeof a === "string" ? a.replaceAll("${CLAUDE_PLUGIN_ROOT}", PLUGIN_ROOT) : a,
    );
    // OpenCode local-server shape: command as an argv array, env merged verbatim. The
    // SKILL_OPENCODE_ROOTS pin rides .mcp.json like every other harness-root flag.
    return { type: "local", command: ["/bin/bash", ...args], env: row.env ?? {} };
  } catch {
    return null;
  }
}

function childEnv(): Record<string, string> {
  return { ...process.env, SKILL_CONCIERGE_HARNESS: HARNESS } as Record<string, string>;
}

/** Fire-and-forget ledger write — never awaited, never throws. */
function runLedger(payload: Record<string, unknown>): void {
  try {
    if (!existsSync(LEDGER_SCRIPT)) return;
    const child = spawn("python3", [LEDGER_SCRIPT], {
      env: childEnv(),
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    });
    child.stdin.on("error", () => { /* child gone: telemetry only */ });
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
    child.unref();
  } catch {
    // fail-silent telemetry
  }
}

/** Run a hook script synchronously with a bounded timeout; returns its parsed stdout
 * JSON (Claude Code hook contract: {hookSpecificOutput: {additionalContext, ...}}) or
 * null on timeout / non-zero / any error. */
function runHookJson(script: string, payload: Record<string, unknown>, timeoutMs: number): any | null {
  try {
    if (!existsSync(script)) return null;
    const res = spawnSync("python3", [script], {
      input: JSON.stringify(payload),
      env: childEnv(),
      timeout: timeoutMs,
      encoding: "utf-8",
    });
    if (res.status === 0 && res.stdout) {
      try {
        return JSON.parse(res.stdout);
      } catch {
        return null;
      }
    }
  } catch {
    // fail-open
  }
  return null;
}

/** Run skill_exclusions.py on a ledger-shaped PostToolUse payload; resolves the
 * SKILL-EXCLUDES echo or null (skill excludes nothing, timeout, any error). */
function runExclusionsSync(payload: Record<string, unknown>): string | null {
  const out = runHookJson(EXCLUSIONS_SCRIPT, payload, 3000);
  return out?.hookSpecificOutput?.additionalContext || null;
}

/** Fire one detached self-heal script; never blocks, never throws. */
function fireDetached(script: string): void {
  try {
    if (!existsSync(script)) return;
    const child = spawn("python3", [script], {
      env: childEnv(),
      stdio: "ignore",
      detached: true,
    });
    child.unref();
  } catch {
    // fail-silent maintenance
  }
}

/** sessionID of an event-ish object (readonly on every OpenCode hook event). */
function sidOf(event: any): string {
  try {
    return String(event?.sessionID ?? "");
  } catch {
    return "";
  }
}

export default {
  id: "skill-concierge",

  async setup(ctx: any) {
    // ── 1. skill-search MCP server (Claude Code .mcp.json auto-connect parity) ──
    try {
      const server = mcpServerConfig();
      if (server) {
        await ctx.mcp.transform((editor: any) => {
          editor.set("skill-search", server);
        });
      }
    } catch {
      // fail-open: retrieval still works if the operator configured the server manually
    }

    // ── 2. SessionStart-parity detached self-heal batch ──
    for (const script of AUTO_SCRIPTS) {
      fireDetached(script);
    }

    // ── Per-session governance state (plugin lifetime spans sessions) ──
    const doctrineDone = new Set<string>();   // sessionID → doctrine pushed once
    const pendingBlock = new Map<string, string>();  // sessionID → enforcer block awaiting the next model call

    // ── 3. Prompt admission: ledger turn boundary + semantic enforcer ──
    await ctx.session.hook("prompt", (event: any) => {
      try {
        const text = String(event?.prompt?.text ?? "").trim();
        const sid = sidOf(event);
        if (!text || !sid) return;

        // Turn boundary (ledger.py classifies UserPromptSubmit by hook_event_name).
        runLedger({
          hook_event_name: "UserPromptSubmit",
          session_id: sid,
          prompt: text,
          harness: HARNESS,
        });

        // Semantic enforcer — bounded; null on timeout/error means NO injection
        // (fail-open), never a blocked prompt.
        const out = runHookJson(ENFORCER_SCRIPT, { prompt: text, session_id: sid }, 10_000);
        const block = out?.hookSpecificOutput?.additionalContext;
        if (typeof block === "string" && block.trim()) {
          pendingBlock.set(sid, block.trim());
        }
      } catch {
        // fail-open: admission proceeds untouched
      }
    });

    // ── 4. Model-call assembly: doctrine once per session + per-turn enforcer block ──
    await ctx.session.hook("context", (event: any) => {
      try {
        const sid = sidOf(event);
        if (!sid || !Array.isArray(event?.system)) return;

        if (!doctrineDone.has(sid)) {
          const out = runHookJson(
            DOCTRINE_SCRIPT,
            { hook_event_name: "SessionStart", session_id: sid },
            5_000,
          );
          const doctrine = out?.hookSpecificOutput?.additionalContext;
          if (typeof doctrine === "string" && doctrine.trim()) {
            event.system.push({ type: "text", text: doctrine.trim() });
          }
          doctrineDone.add(sid);   // pushed-or-not: never re-push within a session
        }

        const block = pendingBlock.get(sid);
        if (block) {
          pendingBlock.delete(sid);
          event.system.push({ type: "text", text: block });
        }
      } catch {
        // fail-open: the model call proceeds without governance text
      }
    });

    // ── 5. Blocklist deny gate (PreToolUse(Skill) parity, ADR-0046) ──
    // The `skill` permission action covers OpenCode's native skill tool; the decision is
    // delegated to skill_guard.py so ONE blocklist implementation serves every harness.
    await ctx.permission.hook("evaluate", (event: any) => {
      try {
        if (event?.action !== "skill") return;
        const sid = sidOf(event);
        const id = String(event?.resources?.[0] ?? "");
        if (!id) return;
        const out = runHookJson(
          GUARD_SCRIPT,
          { hook_event_name: "PreToolUse", session_id: sid,
            tool_name: "Skill", tool_input: { skill: id } },
          5_000,
        );
        const decision = out?.hookSpecificOutput?.permissionDecision;
        if (decision === "deny") {
          event.effect = "deny";
          event.message = out?.hookSpecificOutput?.permissionDecisionReason
            || `skill-concierge: ${id} is on the user-ordered blocklist`;
        }
      } catch {
        // fail-OPEN: a broken guard never wedges skill invocation
      }
    });

    // ── 6. PostToolUse parity: ledger + the ADR-0059 exclusion echo ──
    await ctx.tool.hook("execute.after", (event: any) => {
      try {
        const tool = String(event?.tool ?? "");
        const sid = sidOf(event);
        if (!sid) return;

        if (tool === "skill") {
          // Native skill activation. ledger.py's auto lane keys on tool_name + the `id`
          // input key (the OpenCode form of the Skill tool's name parameter).
          const id = String(event?.input?.id ?? "");
          const payload = {
            hook_event_name: "PostToolUse",
            session_id: sid,
            tool_name: "skill",
            tool_input: { id },
            harness: HARNESS,
          };
          runLedger(payload);

          // Exclusion echo: a loaded skill's own "not for" lines bounce back so a body
          // that excludes the task forces an open re-rule. Appended to the result's text
          // content only when the shape allows (kept whole, never replaced).
          if (event?.status === "completed" && !event?.error) {
            const echo = runExclusionsSync({ ...payload, tool_response: event?.result });
            if (echo && Array.isArray(event?.result?.content)) {
              event.result.content.push({ type: "text", text: echo });
            }
          }
        } else if (tool.endsWith("skill-search_search_skills")) {
          runLedger({
            hook_event_name: "PostToolUse", session_id: sid,
            tool_name: tool, tool_input: {}, harness: HARNESS,
          });
        } else if (tool.endsWith("skill-search_get_skill")) {
          const payload = {
            hook_event_name: "PostToolUse",
            session_id: sid,
            tool_name: tool,
            tool_input: { name: event?.input?.name },
            harness: HARNESS,
          };
          runLedger(payload);   // ADR-0031 external-take leg: record the pulled name
          if (event?.status === "completed" && !event?.error && Array.isArray(event?.result?.content)) {
            const echo = runExclusionsSync({ ...payload, tool_response: event?.result });
            if (echo) event.result.content.push({ type: "text", text: echo });
          }
        }
        // Everything else is intentionally skipped — no ledger noise.
      } catch {
        // fail-silent telemetry
      }
    });

    // Optional cleanup on unload.
    return () => {
      try {
        doctrineDone.clear();
        pendingBlock.clear();
      } catch {
        // never throw from cleanup
      }
    };
  },
};
