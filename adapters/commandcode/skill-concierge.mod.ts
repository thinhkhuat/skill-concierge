/**
 * skill-concierge — Command Code Mod Adapter (ADR-0038).
 *
 * Integrates skill-concierge with Command Code (`cmd`) as a first-class citizen:
 * 1. `transformInput`: runs the semantic enforcer on every typed user prompt,
 *    injecting the SKILL-FIRST standing mandate and ranked top-k preview.
 * 2. Prompt telemetry: logs turn boundaries and manual `/slash` invocations to the ledger.
 * 3. Tool telemetry: observes `skill_loaded` and `tool_completed` to record skill
 *    and retriever usage in the shared invocation ledger.
 *
 * Fail-open design: all handlers catch exceptions and degrade to no-op.
 */

import { spawnSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

// Resolve plugin root:
// 1. Explicit env `SKILL_CONCIERGE_ROOT`
// 2. Sibling directory relative to this mod if inside the repo
// 3. Fallback to standard checkout path
function resolvePluginRoot(): string {
  if (process.env.SKILL_CONCIERGE_ROOT && existsSync(process.env.SKILL_CONCIERGE_ROOT)) {
    return process.env.SKILL_CONCIERGE_ROOT;
  }
  const candidate = resolve(__dirname, "../..");
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

function sessionIdOf(cmd: any, ctx?: any): string {
  try {
    if (ctx?.session?.leafId) return ctx.session.leafId();
    if (cmd?.sessions?.leafId) return cmd.sessions.leafId();
    if (ctx?.sessionId) return String(ctx.sessionId);
    if (process.env.COMMANDCODE_SESSION_ID) return process.env.COMMANDCODE_SESSION_ID;
  } catch {
    // fail-open: session id is telemetry only
  }
  return "";
}

function runLedger(payload: Record<string, unknown>): void {
  try {
    if (!existsSync(LEDGER_SCRIPT)) return;
    const child = spawn("python3", [LEDGER_SCRIPT], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "commandcode" },
      stdio: ["pipe", "ignore", "ignore"],
      detached: true,
    });
    child.stdin.write(JSON.stringify(payload));
    child.stdin.end();
    child.unref();
  } catch {
    // fail-silent telemetry
  }
}

function runEnforcer(promptText: string, sessionId: string): string | null {
  try {
    if (!existsSync(ENFORCER_SCRIPT)) return null;
    const payload = JSON.stringify({ prompt: promptText, session_id: sessionId });
    const res = spawnSync("python3", [ENFORCER_SCRIPT], {
      input: payload,
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "commandcode" },
      timeout: 2500, // 2.5s hard timeout on user input path
      encoding: "utf-8",
    });
    if (res.status === 0 && res.stdout) {
      const parsed = JSON.parse(res.stdout);
      return parsed?.hookSpecificOutput?.additionalContext || null;
    }
  } catch {
    // fail-open
  }
  return null;
}

export default function (cmd: any): void {
  // ── 1. Per-turn enforcer + prompt telemetry via transformInput ──
  // Session id is captured from the ModContext (second arg) when available,
  // otherwise from cmd.sessions.leafId() / env — mirrors OMP's sessionIdOf
  // pattern and restores chain-hint/ROUTE ledger linkage (ADR-0038/0042 parity).
  cmd.hooks({
    transformInput: ({ text }: { text: string }, ctx?: any) => {
      const sid = sessionIdOf(cmd, ctx);
      try {
        const trimmed = text.trim();
        if (!trimmed) return { action: "continue" };

        if (trimmed.startsWith("/")) {
          runLedger({
            hook_event_name: "UserPromptSubmit",
            session_id: sid,
            prompt: trimmed,
            harness: "commandcode",
          });
          return { action: "continue" };
        }

        // Log turn boundary
        runLedger({
          hook_event_name: "UserPromptSubmit",
          session_id: sid,
          prompt: trimmed,
          harness: "commandcode",
        });

        // Run semantic enforcer — pass session_id so enforcer's
        // _last_used_skill + ledger offer/turn join stay linked (ZCode parity).
        const enforcerCtx = runEnforcer(trimmed, sid);
        if (enforcerCtx && enforcerCtx.trim()) {
          // Prepend hook context so the model sees the mandate before the request
          const transformed = `<hook_context source="skill-concierge">\n${enforcerCtx.trim()}\n</hook_context>\n\n${text}`;
          return {
            action: "transform",
            text: transformed,
          };
        }
      } catch {
        // fail-open
      }
      return { action: "continue" };
    },
  });

  // ── 2. Tool & Skill telemetry via Agent Events ──
  // Session id threaded through ledger rows so analyze.py can join
  // offer/turn/auto across turns — ZCode/OMP parity (ADR-0042).
  cmd.on("skill_loaded", ({ name }: { name: string }) => {
    runLedger({
      hook_event_name: "PostToolUse",
      session_id: sessionIdOf(cmd),
      tool_name: "activate_skill",
      tool_input: { name },
      harness: "commandcode",
    });
  });

  cmd.on("tool_completed", (event: any) => {
    try {
      const toolName = event?.toolName || "";
      if (
        toolName.includes("skill-search") ||
        toolName.includes("skill_search") ||
        toolName === "activate_skill"
      ) {
        runLedger({
          hook_event_name: "PostToolUse",
          session_id: sessionIdOf(cmd),
          tool_name: toolName,
          tool_input: event?.input || {},
          harness: "commandcode",
        });
      }
    } catch {
      // fail-silent
    }
  });
}
