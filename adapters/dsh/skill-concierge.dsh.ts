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
 * 3. Telemetry: ledger capture is Phase 2 — the Cordis tool-call event
 *    surface for DSH is not yet pinned here (see the OMP adapter for the
 *    reference observation pattern).
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
function sessionIdOf(): string {
  try {
    return process.env.DSH_SESSION_ID || "";
  } catch {
    return "";
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
function makeInjection(text: string): any {
  return {
    role: "user",
    content: [
      {
        type: "text",
        text,
      },
    ],
    source: { kind: "skill-concierge-injection" },
  };
}

export default function (ctx: any): void {
  let doctrineInjected = false;

  ctx.on("agent/pre-step", async (event: any, next: () => Promise<any>) => {
    const decision = await next();
    if (decision?.kind === "reject") return decision;

    const extra: any[] = [];
    const sid = sessionIdOf();

    try {
      // ── (a) Doctrine: inject once per session, plus the detached self-heal ──
      if (!doctrineInjected) {
        doctrineInjected = true;
        const doctrine = runDoctrine(sid);
        if (doctrine && doctrine.trim()) {
          extra.push(makeInjection(doctrine.trim()));
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
    return {
      kind: "enter",
      messages: [...(decision?.messages ?? []), ...extra],
    };
  });

  // ── 2. Tool telemetry (Phase 2) ──
  // The DSH Cordis tool-call observation surface (the equivalent of OMP's
  // `tool_result`) is not yet pinned here. Reference pattern:
  // the OMP adapter's tool_result observer (adapters/omp/skill-concierge.ext.ts)
  // adapted to DSH's ctx.tools / agent event names once those are verified live.
}