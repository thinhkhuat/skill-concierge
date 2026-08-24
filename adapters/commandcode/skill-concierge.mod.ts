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

function runEnforcer(promptText: string): string | null {
  try {
    if (!existsSync(ENFORCER_SCRIPT)) return null;
    const payload = JSON.stringify({ prompt: promptText });
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
  cmd.hooks({
    transformInput: ({ text }: { text: string }) => {
      try {
        const trimmed = text.trim();
        if (!trimmed) return { action: "continue" };

        if (trimmed.startsWith("/")) {
          runLedger({
            hook_event_name: "UserPromptSubmit",
            prompt: trimmed,
            harness: "commandcode",
          });
          return { action: "continue" };
        }

        // Log turn boundary
        runLedger({
          hook_event_name: "UserPromptSubmit",
          prompt: trimmed,
          harness: "commandcode",
        });

        // Run semantic enforcer
        const ctx = runEnforcer(trimmed);
        if (ctx && ctx.trim()) {
          // Prepend hook context so the model sees the mandate before the request
          const transformed = `<hook_context source="skill-concierge">\n${ctx.trim()}\n</hook_context>\n\n${text}`;
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
  cmd.on("skill_loaded", ({ name }: { name: string }) => {
    runLedger({
      hook_event_name: "PostToolUse",
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
