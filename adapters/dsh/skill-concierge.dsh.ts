/**
 * skill-concierge — DSH (DeepSeek Harness) Cordis Plugin Adapter (ADR-0050).
 *
 * Integrates skill-concierge with DSH as a first-class harness through DSH's
 * Cordis composition system. This plugin provides the per-turn enforcement
 * vehicle — the equivalent of Command Code's mod (transformInput), OMP's
 * extension module (before_agent_start), and Claude Code/ZCode's native hooks.
 *
 * Integration surfaces (mirroring the verified dsh-tool-skill pattern):
 * 1. `agent/pre-step`: DSH's per-turn lifecycle event (the same hook the
 *    stock `tool-skill` uses to inject skill instructions). On the FIRST
 *    pre-step of a session we run doctrine.py and inject the SKILL-FIRST
 *    standing order; on every pre-step we run the semantic enforcer on the
 *    latest user prompt and inject the ranked mandate + top-k preview.
 * 2. Self-heal: fires the detached auto_reindex/auto_overrides/auto_flywheel/
 *    auto_promote scripts at session start (throttled internally).
 * 3. `tools/post-execute` (ADR-0059): on a skill load — DSH's `skill` tool
 *    (`{name}`) or the skill-search get_skill tool — records the load in the
 *    shared ledger and runs skill_exclusions.py; the skill's own "not for" lines
 *    return as an extra `additionalContexts` message, the shape DSH's own
 *    Claude-hooks bridge uses for PostToolUse context
 *    (@deepseek-ai/dsh-hooks-claude-code, tools/post-execute handler).
 *
 * Injection contract (copied from dsh-tool-skill's pre-step handler, which
 * is the verified native shape): the handler calls `next()`, then returns
 * `{ kind: "enter", messages: [...decision.messages, ...extra] }` to append
 * context into the model's next step.
 *
 * Fail-open design: every handler catches exceptions and degrades to no-op —
 * a broken skill-concierge plugin must NEVER block a DSH session turn.
 *
 * LOADING: this plugin must be resolvable by DSH's Cordis loader (as a
 * compiled JS module or a ts-node-eligible path is deployment-dependent).
 * The install script wires a `cordis.patch.yml` row; production installs
 * should publish it as a DSH bundle.
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";
import { randomUUID } from "node:crypto";

/**
 * Resolve the plugin root directory.
 *
 * Ladder (mirrors Command Code / OMP adapters):
 * 1. Explicit env `SKILL_CONCIERGE_ROOT`
 * 2. Sibling directory if this module is inside the repo
 * 3. Fallback to the standard checkout path
 */
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
const DOCTRINE_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/doctrine.py");
const LEDGER_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/ledger.py");
const EXCLUSIONS_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/skill_exclusions.py");
const AUTO_SCRIPTS = ["auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"].map(
  (name) => join(PLUGIN_ROOT, "hooks/scripts", name),
);

/**
 * Extract the latest user prompt text from the agent's message list.
 * Returns "" when no user text is found.
 */
function latestUserPrompt(messages: any[]): string {
  try {
    for (let i = (messages?.length ?? 0) - 1; i >= 0; i--) {
      const msg = messages[i];
      if (msg?.role !== "user") continue;
      // A prompt is a `source.kind: "user"` message; context other plugins (and this one) inject
      // is `kind: "plugin"` and is never read as one. Subagent task prompts are `kind: "user"`
      // too — the pre-step handler skips subagent sessions before it gets here.
      if (msg?.source && msg.source.kind !== "user") continue;
      const content = msg.content;
      if (typeof content === "string" && content.trim()) return content.trim();
      if (Array.isArray(content)) {
        for (const part of content) {
          if (part?.type === "text" && typeof part.text === "string" && part.text.trim()) {
            return part.text.trim();
          }
        }
      }
    }
  } catch {
    // fail-open
  }
  return "";
}

/** Best-effort session id (DSH_SESSION_ID in the agent env, else an empty string). */
/**
 * The session an event belongs to, from the `agent` DSH passes to pre-step and
 * post-execute handlers (`agent.session.header`; DSH's own dsh-hooks-claude-code
 * bridge reads the same field). DSH sets DSH_SESSION_ID only in processes it spawns
 * for tools, never in the host, so it is a last resort. `sub` = a subagent session
 * (`header.parentSession` set): DSH stamps a subagent's task prompt `kind: "user"`,
 * so the source filter alone cannot tell it from typed input.
 */
function sessionOf(agent: any): { id: string; sub: boolean } {
  try {
    const header = agent?.session?.header;
    return { id: String(header?.id ?? process.env.DSH_SESSION_ID ?? ""), sub: Boolean(header?.parentSession) };
  } catch {
    return { id: process.env.DSH_SESSION_ID || "", sub: false };
  }
}

/** Fire-and-forget ledger write — never awaited, never throws. */
function runLedger(payload: Record<string, unknown>): void {
  try {
    if (!existsSync(LEDGER_SCRIPT)) return;
    const child = spawn("python3", [LEDGER_SCRIPT], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "dsh" },
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

/**
 * Run the enforcer synchronously with a bounded timeout on the user-input path.
 * Returns the additionalContext string (or null on timeout/error/empty).
 */
function runEnforcer(promptText: string, sessionId: string): string | null {
  try {
    if (!existsSync(ENFORCER_SCRIPT)) return null;
    const payload = JSON.stringify({ prompt: promptText, session_id: sessionId });
    const res = spawnSync("python3", [ENFORCER_SCRIPT], {
      input: payload,
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "dsh" },
      timeout: 2500, // 2.5s hard timeout on the user input path (Command Code parity)
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

/** Run doctrine.py and return its additionalContext, or null on any failure. */
function runDoctrine(sessionId: string): string | null {
  try {
    if (!existsSync(DOCTRINE_SCRIPT)) return null;
    const payload = JSON.stringify({ hook_event_name: "SessionStart", session_id: sessionId });
    const res = spawnSync("python3", [DOCTRINE_SCRIPT], {
      input: payload,
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "dsh" },
      timeout: 5000,
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

/** skill_exclusions.py on a ledger-shaped payload -> the SKILL-EXCLUDES echo, or null. */
function runExclusions(payload: Record<string, unknown>): Promise<string | null> {
  // Async on purpose: the host awaits the handler, and a spawnSync here froze its event loop
  // for the whole Python run (~270 ms median per skill load, blind-measured). Bounded to 3 s.
  return new Promise((done) => {
    try {
      if (!existsSync(EXCLUSIONS_SCRIPT)) return done(null);
      const child = spawn("python3", [EXCLUSIONS_SCRIPT], {
        env: { ...process.env, SKILL_CONCIERGE_HARNESS: "dsh" },
        stdio: ["pipe", "pipe", "ignore"],
      });
      let out = "";
      const timer = setTimeout(() => { try { child.kill(); } catch { /* gone */ } done(null); }, 3000);
      child.stdout.on("data", (b: Buffer) => { out += b.toString("utf-8"); });
      child.on("error", () => { clearTimeout(timer); done(null); });
      child.on("close", (code: number | null) => {
        clearTimeout(timer);
        try {
          done(code === 0 && out ? JSON.parse(out)?.hookSpecificOutput?.additionalContext || null : null);
        } catch {
          done(null);
        }
      });
      child.stdin.on("error", () => { /* child exited before reading: never crash the host */ });
      child.stdin.end(JSON.stringify(payload));
    } catch {
      done(null);
    }
  });
}

/**
 * The ledger-shaped payload for a DSH skill load, or null for any other tool.
 * DSH's `skill` tool (dsh-tool-skill: parameters `{name}`) maps onto the
 * Skill-tool lane; the get_skill MCP tool keeps its own name.
 */
function skillLoadPayload(exec: any): Record<string, unknown> | null {
  const name = String(exec?.name ?? "");
  const args = exec?.arguments && typeof exec.arguments === "object" ? exec.arguments : {};
  if (name === "skill") return { tool_name: "Skill", tool_input: { skill: args.name } };
  if (/skill[-_]search.*get_skill$/.test(name)) return { tool_name: name, tool_input: args };
  return null;
}

/** Fire one detached self-heal script; never blocks, never throws. */
function fireDetached(script: string): void {
  try {
    if (!existsSync(script)) return;
    const child = spawn("python3", [script], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "dsh" },
      stdio: "ignore",
      detached: true,
    });
    child.unref();
  } catch {
    // fail-silent maintenance
  }
}

/** Build one DSH user-message injection (as the stock tool-skill does). */
/**
 * A DSH user message. DSH's `Message.id` is required ("stable identity preserved across every
 * representation boundary", dsh-llm message types) — its own Claude-hooks bridge builds context
 * with `createUserMessage`, which assigns one; the `plugin` source kind is that bridge's shape.
 */
function makeInjection(text: string): any {
  return {
    id: randomUUID(),
    role: "user",
    content: [
      {
        type: "text",
        text,
      },
    ],
    source: { kind: "plugin", plugin: "skill-concierge" },
  };
}

export default function (ctx: any): void {
  // Doctrine goes once per SESSION — desktop/web hosts run many sessions in one process.
  const doctrineSessions = new Set<string>();

  ctx.on("agent/pre-step", async (event: any, next: () => Promise<any>) => {
    const decision = await next();
    if (decision?.kind !== "enter") return decision;   // only `enter` carries messages to extend

    const extra: any[] = [];
    const { id: sid, sub } = sessionOf(event?.agent);
    // A subagent session gets no doctrine, no mandate and no turn row — Claude Code parity:
    // subagents fire no UserPromptSubmit and ADR-0020 keeps the doctrine out of them.
    if (sub) return decision;
    let doctrineDelivered = false;

    try {
      // ── (a) Doctrine: inject once per session, plus the detached self-heal ──
      if (!doctrineSessions.has(sid)) {
        const doctrine = runDoctrine(sid);
        if (doctrine && doctrine.trim()) {
          extra.push(makeInjection(doctrine.trim()));
          doctrineDelivered = true;
        }
        for (const script of AUTO_SCRIPTS) {
          fireDetached(script);
        }
      }

      // ── (b) Per-turn enforcer on the latest user prompt ──
      const prompt = latestUserPrompt(event?.messages);
      if (prompt) {
        // Log the turn boundary (UserPromptSubmit parity).
        runLedger({
          hook_event_name: "UserPromptSubmit",
          session_id: sid,
          prompt,
          harness: "dsh",
        });
        const additionalContext = runEnforcer(prompt, sid);
        if (additionalContext && additionalContext.trim()) {
          extra.push(makeInjection(
            `<hook_context source="skill-concierge">\n${additionalContext.trim()}\n</hook_context>`,
          ));
        }
      }
    } catch {
      // fail-open — never block the turn
    }

    if (extra.length === 0) return decision;
    if (doctrineDelivered) doctrineSessions.add(sid);   // marked only once actually handed over
    return {
      ...decision,
      messages: [...(decision?.messages ?? []), ...extra],
    };
  });

  // ── 2. Skill loads: ledger row + exclusion echo (PostToolUse parity) ──
  // `tools/post-execute` is DSH's post-tool event (verified in the installed
  // @deepseek-ai/dsh-hooks-claude-code bridge: handler (exec, result, next),
  // exec.name / exec.arguments, returns {...downstream, additionalContexts}).
  ctx.on("tools/post-execute", async (exec: any, result: any, next: () => Promise<any>) => {
    const downstream = await next();
    try {
      const load = skillLoadPayload(exec);
      if (!load) return downstream;
      const { id: sid, sub } = sessionOf(exec?.agent);
      const payload = { hook_event_name: "PostToolUse", session_id: sid, harness: "dsh",
                        ...(sub ? { agent_id: sid } : {}), ...load };   // ledger stamps subagent rows `sub`
      runLedger(payload);
      if (result?.isError || downstream?.kind === "block") return downstream;
      const echo = await runExclusions({ ...payload, tool_response: result?.content });
      if (!echo) return downstream;
      return {
        ...downstream,
        additionalContexts: [makeInjection(echo), ...(downstream?.additionalContexts ?? [])],
      };
    } catch {
      return downstream; // fail-open
    }
  });
}