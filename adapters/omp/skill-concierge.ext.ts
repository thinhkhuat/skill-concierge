/**
 * skill-concierge — Oh My Pi (OMP) Extension Adapter (ADR-0039).
 *
 * Integrates skill-concierge with OMP as a first-class harness. OMP loads this
 * module via package.json `omp.extensions` (see adapters/omp/install.sh) and
 * invokes the default factory with the ExtensionAPI (`pi`). It mirrors the
 * Command Code adapter (adapters/commandcode/skill-concierge.mod.ts) — same
 * resolvePluginRoot pattern, same enforcer/ledger/doctrine/auto_* scripts —
 * adapted to OMP's event surface:
 *
 * 1. `session_start`: (a) runs doctrine.py and delivers the SKILL-FIRST
 *    standing order as a custom message via pi.sendMessage (SessionStart
 *    parity), (b) fires the detached self-heal scripts (auto_reindex.py,
 *    auto_overrides.py, auto_flywheel.py, auto_promote.py) — SessionStart
 *    self-heal parity.
 * 2. `before_agent_start`: runs the semantic enforcer on the typed prompt and
 *    returns the SKILL-FIRST re-assert + top-k preview as an injected custom
 *    message (UserPromptSubmit parity); logs the turn boundary to the ledger.
 * 3. `tool_result`: observes skill activation (`read` with a `skill://` path)
 *    and retriever usage (`skill-search__search_skills` / `get_skill`) and
 *    records them in the shared invocation ledger (PostToolUse parity). On a
 *    skill load it also runs skill_exclusions.py on the same payload and, when
 *    the skill's own SKILL.md says what it is NOT for, appends that echo to the
 *    tool result the model reads (ADR-0059; Claude Code's PostToolUse
 *    additionalContext parity — OMP `tool_result` handlers may return
 *    replacement `content`, shared-events.d.ts ToolResultEventResult).
 *
 * Fail-open design: every handler catches exceptions and degrades to no-op —
 * an OMP extension must NEVER throw from a handler (tool_call is fail-closed;
 * tool_result is the safe observation point). No `pi.sendMessage` is called
 * during module load (runtime actions throw until the runner initializes).
 */
import { spawnSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

// Resolve plugin root — identical ladder to the Command Code adapter:
// 1. Explicit env `SKILL_CONCIERGE_ROOT`
// 2. Sibling directory relative to this module if inside the repo
// 3. Fallback to the standard checkout path
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
const DOCTRINE_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/doctrine.py");
const EXCLUSIONS_SCRIPT = join(PLUGIN_ROOT, "hooks/scripts/skill_exclusions.py");
// SessionStart self-heal batch (hooks/hooks.json parity). Each script is
// fail-silent, throttled and spawns its own detached work; we fire them
// detached too so session start never waits on engine maintenance.
const AUTO_SCRIPTS = ["auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"].map(
  (name) => join(PLUGIN_ROOT, "hooks/scripts", name),
);

/** Best-effort session id from the read-only session manager (may be absent). */
function sessionIdOf(ctx: { sessionManager?: { getSessionId?: () => string } }): string {
  try {
    return ctx.sessionManager?.getSessionId?.() ?? "";
  } catch {
    return "";
  }
}

/** Fire-and-forget ledger write — never awaited, never throws. */
function runLedger(payload: Record<string, unknown>): void {
  try {
    if (!existsSync(LEDGER_SCRIPT)) return;
    const child = spawn("python3", [LEDGER_SCRIPT], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "omp" },
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
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "omp" },
      timeout: 10_000, // 10s hard timeout on the user input path
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
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "omp" },
      timeout: 5_000,
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

/**
 * Run skill_exclusions.py on a ledger-shaped PostToolUse payload and return the
 * SKILL-EXCLUDES echo, or null (skill excludes nothing, timeout, any error).
 * Fires only on a skill ROOT load, never per tool call.
 */
function runExclusions(payload: Record<string, unknown>): Promise<string | null> {
  // Async on purpose: the host awaits the handler, and a spawnSync here froze its event loop
  // for the whole Python run (~270 ms median per skill load, blind-measured). Bounded to 3 s.
  return new Promise((done) => {
    try {
      if (!existsSync(EXCLUSIONS_SCRIPT)) return done(null);
      const child = spawn("python3", [EXCLUSIONS_SCRIPT], {
        env: { ...process.env, SKILL_CONCIERGE_HARNESS: "omp" },
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

/** Fire one detached self-heal script; never blocks, never throws. */
function fireDetached(script: string): void {
  try {
    if (!existsSync(script)) return;
    const child = spawn("python3", [script], {
      env: { ...process.env, SKILL_CONCIERGE_HARNESS: "omp" },
      stdio: "ignore",
      detached: true,
    });
    child.unref();
  } catch {
    // fail-silent maintenance
  }
}

/** Extract the skill name from a `skill://<name>...` read path. */
function skillNameFromPath(pathValue: unknown): string {
  const raw = String(pathValue ?? "");
  const marker = "skill://";
  const idx = raw.indexOf(marker);
  if (idx === -1) return "";
  const rest = raw.slice(idx + marker.length);
  // The name runs to the first `/`, `?`, `#`, whitespace or end of string.
  const name = rest.split(/[/?#\s]/)[0];
  return name || "";
}

export default function (pi: any): void {
  // ── 1. SessionStart: doctrine injection + detached self-heal ──
  pi.on("session_start", (event: { type: "session_start" }, ctx: any) => {
    const sessionId = sessionIdOf(ctx);
    // (a) Doctrine — delivered as a custom message so it lands in context
    // (TUI-visible per the OMP docs), with triggerTurn:false so it never
    // starts a turn by itself. Attribution "agent" keeps billing honest.
    try {
      const doctrine = runDoctrine(sessionId);
      if (doctrine && doctrine.trim()) {
        pi.sendMessage(
          {
            customType: "skill-concierge-doctrine",
            content: doctrine.trim(),
            display: true,
            attribution: "agent",
          },
          { triggerTurn: false },
        );
      }
    } catch {
      // fail-open
    }
    // (b) Detached SessionStart self-heal batch — never awaited.
    for (const script of AUTO_SCRIPTS) {
      fireDetached(script);
    }
  });

  // ── 2. Per-turn enforcer + turn-boundary ledger (UserPromptSubmit parity) ──
  pi.on("before_agent_start", (event: { type: string; prompt: string }, ctx: any) => {
    try {
      const trimmed = (event.prompt || "").trim();
      if (!trimmed) return undefined;
      const sessionId = sessionIdOf(ctx);

      // Log turn boundary (ledger.py classifies by hook_event_name + prompt).
      runLedger({
        hook_event_name: "UserPromptSubmit",
        session_id: sessionId,
        prompt: trimmed,
        harness: "omp",
      });

      // Run the semantic enforcer; on timeout/error it returns null → no injection.
      const additionalContext = runEnforcer(trimmed, sessionId);
      if (additionalContext && additionalContext.trim()) {
        return {
          message: {
            customType: "skill-concierge",
            content: additionalContext.trim(),
            // Hidden from the editable pending queue; the message is still
            // pushed into the provider-bound message list (display only
            // controls TUI visibility, not LLM delivery).
            display: false,
            attribution: "agent",
          },
        };
      }
    } catch {
      // fail-open
    }
    return undefined;
  });

  // ── 3. Tool telemetry via tool_result (PostToolUse parity) ──
  // tool_result is the safe observation point: tool_call handlers are
  // FAIL-CLOSED (a throw blocks the tool), so all observation lives here,
  // fully try/caught and fire-and-forget on the hot path.
  pi.on("tool_result", (event: any, ctx: any) => {
    try {
      const toolName: string = event?.toolName || "";
      const input: Record<string, unknown> = event?.input || {};
      const sessionId = sessionIdOf(ctx);

      if (toolName === "read") {
        // Skill activation = read tool with a skill:// path (ADR-0039). The raw
        // `path` is forwarded verbatim: ledger.py's read branch keys on
        // tool_input.path starting "skill://" and extracts the name itself —
        // a pre-extracted {skill} key would fall through every branch and the
        // activation would be silently dropped from the ledger.
        const path = String(input?.path ?? "");
        if (path.startsWith("skill://")) {
          const payload = {
            hook_event_name: "PostToolUse",
            session_id: sessionId,
            tool_name: "read",
            tool_input: { path },
            harness: "omp",
          };
          runLedger(payload);
          // Echo only on a skill ROOT load — a sub-resource read (skill://x/references/y.md)
          // is not a load, so no Python spawn for it.
          const [name, ...tail] = path.slice("skill://".length).split("/");
          const rest = tail.join("/");
          return name && (rest === "" || rest === "SKILL.md") ? withExclusions(event, payload) : undefined;
        }
      } else if (toolName.endsWith("skill-search/search_skills") || toolName.endsWith("skill_search_search_skills")) {
        // Retriever usage — ledger classifies by suffix; input is empty. The single-underscore
        // form is OMP's flattened mangled name (observed live 2026-08-26:
        // mcp__skill_concierge_skill_search_search_skills — every separator becomes `_`).
        runLedger({
          hook_event_name: "PostToolUse",
          session_id: sessionId,
          tool_name: toolName,
          tool_input: {},
          harness: "omp",
        });
      } else if (toolName.endsWith("skill-search/get_skill") || toolName.endsWith("skill_search_get_skill")) {
        // Deep pull (ADR-0031 external-take leg) — record the pulled name. Single-underscore
        // form: OMP's flattened mangled name, same class as the search matcher above.
        const payload = {
          hook_event_name: "PostToolUse",
          session_id: sessionId,
          tool_name: toolName,
          tool_input: { name: input?.name },
          harness: "omp",
        };
        runLedger(payload);
        return withExclusions(event, payload);
      }
      // Everything else is intentionally skipped — no ledger noise.
    } catch {
      // fail-silent telemetry
    }
    return undefined;
  });
}

/**
 * The tool result with the skill's own exclusion echo appended as one more text
 * block — the original content is kept whole — or undefined (no change) when the
 * loaded skill excludes nothing or the result was an error.
 */
async function withExclusions(event: any, payload: Record<string, unknown>): Promise<{ content: any[] } | undefined> {
  if (event?.isError || !Array.isArray(event?.content)) return undefined;   // never replace what we cannot keep
  const content = event.content;
  // The loaded text rides along: when it is the SKILL.md itself the echo quotes exactly that copy;
  // otherwise skill_exclusions.py resolves the skill by name.
  const echo = await runExclusions({ ...payload, tool_response: content });
  if (!echo) return undefined;
  return { content: [...content, { type: "text", text: echo }] };
}
