/**
 * unlazy — DSH (DeepSeek Harness) Cordis Stop Hook Plugin (ADR-0050 companion).
 *
 * Bridges unlazy's gate-enforcement into DSH via the `agent/pre-step` event.
 * When the current workspace has an unresolved unlazy pipeline (unmet gates,
 * invalid ledgers, or incomplete dispatch waves), this plugin rejects the
 * turn with a blocking reason — the DSH equivalent of the Claude Code
 * Stop hook.
 *
 * The enforcement logic is DELEGATED to the packaged `stop-hook.mjs` script
 * (the same script the Claude Code hook runs), called as a subprocess with
 * the session's cwd and id. The plugin translates the `decision: "block"`
 * response into a DSH `{ kind: "reject" }` return.
 *
 * Design contract:
 *   • FAIL-SILENT — any error degrades to allow, never block a turn.
 *   • ZERO-DEPENDENCY — no npm packages needed; calls the installed unlazy
 *     script via `node <unlazy-dir>/scripts/stop-hook.mjs`.
 *   • SIX-BLOCK PROGRESS GUARD — inherited from stop-hook.mjs: releases
 *     after 6 consecutive blocks without gate/dispatch progress.
 *   • SESSION-SCOPED — the hook's state file is in the workspace's
 *     `.unlazy/` or `~/.unlazy-hook-state.json` (shared with Claude Code).
 *
 * Phase 1: delegates to the stop-hook subprocess. Phase 2: import the
 * gate/dispatch logic directly (the lib modules are zero-dependency).
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";

/**
 * Resolve the unlazy skill directory.
 *
 * Ladder:
 * 1. Explicit env `UNLAZY_DIR`
 * 2. Standard install paths: ~/.agents/skills/unlazy, ~/.claude/skills/unlazy
 * 3. Sibling directory from the concierge plugin (dev layout)
 */
function resolveUnlazyDir(): string {
  if (process.env.UNLAZY_DIR && existsSync(process.env.UNLAZY_DIR)) {
    return process.env.UNLAZY_DIR;
  }
  const home = process.env.HOME || "~";
  const candidates = [
    resolve(home, ".agents", "skills", "unlazy"),
    resolve(home, ".claude", "skills", "unlazy"),
    resolve(__dirname, "..", "..", "..", "unlazy"),
  ];
  for (const cand of candidates) {
    if (existsSync(join(cand, "scripts/stop-hook.mjs"))) {
      return cand;
    }
  }
  return "";
}

const UNLAZY_DIR = resolveUnlazyDir();
const STOP_HOOK = join(UNLAZY_DIR, "scripts", "stop-hook.mjs");

/**
 * Extract the workspace root (cwd) from the DSH context.
 */
function cwdOf(ctx: any): string {
  try {
    if (ctx?.agent?.session?.header?.cwd) return ctx.agent.session.header.cwd;
    if (ctx?.session?.header?.cwd) return ctx.session.header.cwd;
    return process.cwd();
  } catch {
    return process.cwd();
  }
}

/**
 * Extract a session id from the DSH context.
 */
function sessionIdOf(ctx: any): string {
  try {
    if (ctx?.agent?.session?.id) return ctx.agent.session.id;
    if (ctx?.session?.id) return ctx.session.id;
    if (process.env.DSH_SESSION_ID) return process.env.DSH_SESSION_ID;
    return "anonymous";
  } catch {
    return "anonymous";
  }
}

/**
 * Call the stop-hook script as a subprocess.
 *
 * Passes the same stdin payload the Claude Code hook would receive:
 *   { "cwd": "...", "session_id": "..." }
 *
 * Returns the parsed JSON response, or null on any failure.
 */
function runStopHook(
  cwd: string,
  sessionId: string,
): { decision?: string; reason?: string; systemMessage?: string } | null {
  try {
    if (!UNLAZY_DIR || !existsSync(STOP_HOOK)) return null;
    const payload = JSON.stringify({ cwd, session_id: sessionId });
    const res = spawnSync(process.execPath, [STOP_HOOK], {
      input: payload,
      cwd,
      timeout: 5000,
      encoding: "utf-8",
    });
    if (res.status === 0 && res.stdout) {
      const trimmed = res.stdout.trim();
      if (!trimmed) return null;
      return JSON.parse(trimmed);
    }
  } catch {
    // fail-silent
  }
  return null;
}

export default function (ctx: any): void {
  ctx.on("agent/pre-step", async (event: any, next: () => Promise<any>) => {
    const decision = await next();
    if (decision?.kind === "reject") return decision;

    try {
      if (!UNLAZY_DIR || !existsSync(STOP_HOOK)) return decision;

      const cwd = cwdOf(ctx);
      const sid = sessionIdOf(ctx);

      // Quick probe: skip if the workspace has no unlazy artifacts.
      if (!existsSync(join(cwd, ".unlazy")) && !existsSync(join(cwd, "GATES.md"))) {
        return decision;
      }

      const result = runStopHook(cwd, sid);
      if (!result) return decision;

      if (result.decision === "block" && result.reason) {
        return { kind: "reject", reason: result.reason };
      }

      return decision;
    } catch {
      return decision;
    }
  });
}