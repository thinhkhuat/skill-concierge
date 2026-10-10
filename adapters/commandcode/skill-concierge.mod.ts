/**
 * skill-concierge — Command Code Mod Adapter (ADR-0038).
 *
 * Integrates skill-concierge with Command Code (`cmd`) as a first-class citizen:
 * 1. `transformContext` is the one place a prompt is governed. It runs before every model
 *    call in the TUI and in print mode (`cmd -p`), sees every prompt (typed, image, IDE
 *    context), and carries `state.sessionId`. It picks the newest user message that is not
 *    a tool-results message and skips it when Command Code itself generated it
 *    (`meta.isMeta`, `isAutomated`, `isSummary`, a stop-hook, scheduled or mod source) or
 *    when it holds no text. Otherwise it runs the semantic enforcer once per prompt (one
 *    `turn` ledger row), prefixes the SKILL-FIRST mandate and ranked top-k preview, and
 *    re-applies the cached menu on later model calls of the same turn (the tool loop).
 * 2. `transformInput` never runs the enforcer. It records the raw typed text, so
 *    `transformContext` can rank on it when IDE context or another mod prepended text to
 *    the stored message, and logs a `manual` ledger row for a typed `/slash` command.
 * 3. Tool telemetry: observes `skill_loaded` and `tool_completed` to record skill
 *    and retriever usage in the shared invocation ledger.
 * 4. `afterToolCall`: on a skill load (`activate_skill`, or the skill-search
 *    get_skill tool) runs skill_exclusions.py and returns the skill's own
 *    "not for" lines as `additionalContext`, which Command Code appends as a
 *    separate text block to the tool result the model reads (ADR-0059; mod-builder
 *    reference/hooks-and-events.md, afterToolCall contract).
 *
 * Session id, in order: an explicit `ctx.sessionId`, `state.sessionId`, the id on the
 * `run_start` event, `COMMANDCODE_SESSION_ID`. `sessions.leafId()` is a session-tree entry
 * id that changes with every appended entry, so it is never used. Every ledger row of a
 * session carries the same id.
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
const EXCLUSIONS_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/skill_exclusions.py");

// Latest id seen on ctx, state or the run_start event; the ledger rows that carry no ctx or
// state (skill_loaded, tool_completed, a typed slash command) use it.
let knownSid = "";

function sessionIdOf(ctx?: any, state?: any): string {
  try {
    const explicit = ctx?.sessionId ? String(ctx.sessionId) : "";
    const fromState = state?.sessionId ? String(state.sessionId) : "";
    const sid = explicit || fromState;
    if (sid) knownSid = sid;
    return sid || knownSid || process.env.COMMANDCODE_SESSION_ID || "";
  } catch {
    return knownSid; // fail-open: session id is telemetry only
  }
}

function runLedger(payload: Record<string, unknown>): void {
  try {
    if (!existsSync(LEDGER_SCRIPT)) return;
    const child = spawn("python3", [LEDGER_SCRIPT], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "commandcode" },
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

function runEnforcer(promptText: string, sessionId: string): string | null {
  try {
    if (!existsSync(ENFORCER_SCRIPT)) return null;
    const payload = JSON.stringify({ prompt: promptText, session_id: sessionId });
    const res = spawnSync("python3", [ENFORCER_SCRIPT], {
      input: payload,
      // The Jev router's budget must end before this kill window (ADR-0079): 1.6 s leaves room for the
      // TypeSafe tier (1.5 s per call); the slower Command Code tier never fits here and is skipped.
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "commandcode", ENFORCER_JEV_BUDGET: "1.6" },
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

/** A skill load: Command Code's own skill tool, or the skill-search get_skill tool. */
function isSkillLoad(toolName: string): boolean {
  return toolName === "activate_skill" || /skill[-_]search.*get_skill$/.test(toolName);
}

/** skill_exclusions.py on a ledger-shaped payload -> the SKILL-EXCLUDES echo, or null. */
function runExclusions(toolName: string, input: unknown, result: unknown): string | null {
  try {
    if (!existsSync(EXCLUSIONS_SCRIPT)) return null;
    const res = spawnSync("python3", [EXCLUSIONS_SCRIPT], {
      input: JSON.stringify({ hook_event_name: "PostToolUse", tool_name: toolName,
                              tool_input: input ?? {}, tool_response: result }),
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "commandcode" },
      timeout: 3000,
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

const HOOK_OPEN = '<hook_context source="skill-concierge">';
const CACHE_CAP = 64;
// typed: raw prompt texts transformInput saw, newest last; the value says the text is a slash command.
// governed: enforcer output per prompt message, so a tool loop runs the enforcer once.
const typed = new Map<string, boolean>();
const governed = new Map<string, string | null>();

/** Make `key` the newest entry and evict the oldest beyond CACHE_CAP. */
function remember<V>(map: Map<string, V>, key: string, value: V): void {
  map.delete(key);
  map.set(key, value);
  while (map.size > CACHE_CAP) map.delete(map.keys().next().value as string);
}

function textOf(msg: any): string {
  if (typeof msg?.content === "string") return msg.content;
  if (!Array.isArray(msg?.content)) return "";
  return msg.content.filter((p: any) => p?.type === "text").map((p: any) => String(p.text ?? "")).join("\n");
}

/** A user-role message that carries tool results back to the model, not a prompt. */
function isToolResults(msg: any): boolean {
  return Array.isArray(msg?.content) && msg.content.some((p: any) => p?.type === "tool_result");
}

/** A user-role message Command Code made itself: stop-hook continuation, compaction summary,
 *  cron/loop/goal wakeup, mod custom message. */
function isHarnessGenerated(msg: any): boolean {
  const meta = msg?.meta;
  if (!meta) return false;
  if (meta.isMeta || meta.isAutomated || meta.isSummary) return true;
  return typeof meta.source === "string" && /^(stop_hook|scheduled-|mod:)/.test(meta.source);
}

function withPrefix(msg: any, prefix: string): any {
  if (typeof msg.content === "string") return { ...msg, content: prefix + msg.content };
  return { ...msg, content: [{ type: "text", text: prefix }, ...msg.content] };
}

export default function (cmd: any): void {
  cmd.hooks({
    // transformInput does not govern: it hands transformContext the raw typed text (IDE context
    // or another mod may prepend text to the stored message) and logs a typed slash command.
    transformInput: ({ text }: { text: string }, ctx?: any) => {
      try {
        const trimmed = String(text ?? "").trim();
        if (!trimmed) return { action: "continue" };
        const slash = trimmed.startsWith("/");
        remember(typed, trimmed, slash);
        if (slash) {
          runLedger({
            hook_event_name: "UserPromptSubmit",
            session_id: sessionIdOf(ctx),
            prompt: trimmed,
            harness: "commandcode",
          });
        }
      } catch {
        // fail-open
      }
      return { action: "continue" };
    },

    // The only place a prompt is governed; runs before every model call, in TUI and print mode.
    transformContext: ({ messages, state }: { messages: any[]; state?: any }, ctx?: any) => {
      try {
        const sid = sessionIdOf(ctx, state);
        // The newest user message that is not a tool-results message is the current turn's
        // prompt. Never look further back: an earlier turn's prompt is not this turn's.
        let i = messages.length - 1;
        while (i >= 0 && !(messages[i]?.role === "user" && !isToolResults(messages[i]))) i--;
        if (i < 0) return messages;
        const msg = messages[i];
        if (isHarnessGenerated(msg)) return messages;
        const text = textOf(msg).trim();
        if (!text || text.includes(HOOK_OPEN)) return messages;

        // The message itself is stable across the model calls of one turn, so it keys the cache.
        const key = `${sid}\u0000${String(msg?.meta?.messageId ?? msg?.meta?.createdAt ?? "")}\u0000${text}`;
        if (!governed.has(key)) {
          // IDE context or another mod may have prepended text: rank on what was typed.
          let rankText = text;
          let slash = false;
          for (const t of [...typed.keys()].reverse()) {
            if (text.endsWith(t)) {
              rankText = t;
              slash = typed.get(t) === true;
              typed.delete(t);
              break;
            }
          }
          if (slash || rankText.startsWith("/")) {
            remember(governed, key, null); // a slash command is never ranked, on any model call
          } else {
            runLedger({ hook_event_name: "UserPromptSubmit", session_id: sid, prompt: rankText, harness: "commandcode" });
            remember(governed, key, runEnforcer(rankText, sid));
          }
        }
        const enforcerCtx = governed.get(key);
        if (!enforcerCtx || !enforcerCtx.trim()) return messages;
        const out = messages.slice();
        out[i] = withPrefix(msg, `${HOOK_OPEN}\n${enforcerCtx.trim()}\n</hook_context>\n\n`);
        return out;
      } catch {
        return messages; // fail-open
      }
    },

    // Skill-exclusion echo (PostToolUse parity). Fires only on a skill load;
    // every other tool call returns undefined (no opinion) without spawning.
    afterToolCall: ({ toolName, input, result, isError }: { toolName: string; input: unknown; result?: unknown; isError?: boolean }) => {
      try {
        if (isError || !isSkillLoad(String(toolName || ""))) return undefined;
        const echo = runExclusions(String(toolName), input, result);
        return echo ? { additionalContext: echo } : undefined;
      } catch {
        return undefined; // fail-open
      }
    },
  });

  // The agent loop announces the session id on run_start, before any model call.
  cmd.on("run_start", (event: any) => {
    try {
      if (event?.sessionId) knownSid = String(event.sessionId);
    } catch {
      // fail-silent
    }
  });

  // ── Tool & Skill telemetry via Agent Events ──
  // Session id threaded through ledger rows so analyze.py can join
  // offer/turn/auto across turns — ZCode/OMP parity (ADR-0042).
  cmd.on("skill_loaded", ({ name }: { name: string }) => {
    runLedger({
      hook_event_name: "PostToolUse",
      session_id: sessionIdOf(),
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
          session_id: sessionIdOf(),
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
