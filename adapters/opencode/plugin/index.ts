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
 * 3. `ctx.session.hook("prompt")`: remembers each admitted prompt (minus a leading
 *    `<system-context>` block another plugin may prepend) and starts a non-blocking
 *    `ctx.session.get` to learn whether the session is a subagent's child (`parentID`). The
 *    prompt text itself is NEVER edited.
 * 4. `ctx.session.hook("context")`: pushes the doctrine ONCE per session (SessionStart parity;
 *    a child session passes `agent_id`, so doctrine.py's ADR-0020 subagent rule applies) and,
 *    on the first model call after each admission, logs the turn boundary and runs the
 *    semantic enforcer (bounded 10 s, Claude Code's UserPromptSubmit timeout), pushing its
 *    block as a system part. A child session gets neither: Claude Code fires no
 *    UserPromptSubmit inside a subagent.
 * 5. `ctx.permission.hook("evaluate")`: action "skill" → delegates the user-ordered
 *    blocklist decision to hooks/scripts/skill_guard.py (the same denying gate Claude
 *    Code runs on PreToolUse(Skill), ADR-0046) and denies on its verdict. Fails OPEN on
 *    any internal error — a broken guard must never wedge skill invocation.
 * 6. `ctx.tool.hook("execute.after")`: PostToolUse parity — completed skill activations (the
 *    native `skill` tool) and retriever usage (`skill-search_search_skills` /
 *    `skill-search_get_skill`, native tools because the server is registered with
 *    `codemode: false`) go to the ledger, stamped `agent_id` inside a subagent; a refused or
 *    failed call is skipped;
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
    // OpenCode v2 local-server shape (opencode.ai/v2/docs/mcp-servers): command as an
    // argv array, env under `environment` (NOT `env` — v2 silently ignores an `env`
    // field and the server then runs on the inherited process environment alone; found
    // live when the registered server fell back to the default 384-dim embedder). The
    // SKILL_OPENCODE_ROOTS pin rides .mcp.json like every other harness-root flag.
    // codemode: false keeps the tools on the native list (Claude Code parity): the doctrine
    // and the ledger name `skill-search_search_skills`, which Code Mode would hide behind execute.
    return { type: "local", command: ["/bin/bash", ...args], environment: row.env ?? {}, codemode: false };
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

/** The user's own words: drops a leading `<system-context>…</system-context>` block another
 * prompt-hook plugin (e.g. a context injector) prepended, so ranking and the ledger see the
 * prompt Claude Code's UserPromptSubmit would carry. */
function userText(raw: unknown): string {
  return String(raw ?? "").replace(/^\s*<system-context>[\s\S]*?<\/system-context>\s*/, "").trim();
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
    const pendingPrompts = new Map<string, string[]>();  // sessionID → prompts admitted since its last model call
    // sessionID → parent sessionID (a subagent's child session) or null (top level). Looked up
    // WITHOUT awaiting: awaiting ctx.session.get inside a session hook deadlocks the session
    // (found live). The lookup starts at admission and lands before the first model call.
    const parentOf = new Map<string, string | null>();
    // Sessions governed while their lookup was pending. When the lookup lands, one ledger row says
    // whether that session was a child after all, so analyze.py counts misgoverned child sessions
    // (M7) instead of an upper bound.
    const governedPending = new Set<string>();
    const lookUpParent = (sid: string) => {
      if (parentOf.has(sid)) return;
      const landed = (parent: string | null) => {
        parentOf.set(sid, parent);
        if (governedPending.delete(sid)) {
          runLedger({ hook_event_name: "ConciergeParentLookup", session_id: sid, harness: HARNESS,
                      child: parent !== null });
        }
      };
      try {
        Promise.resolve(ctx.session.get({ sessionID: sid })).then(
          (s: any) => landed(typeof s?.parentID === "string" && s.parentID ? s.parentID : null),
          () => landed(null),   // a failed lookup is settled as top level, never retried per prompt
        );
      } catch {
        // unknown stays unknown: governed as top level
      }
    };
    /** Claude Code hook payloads carry agent_id only inside a subagent; ledger.py and
     * doctrine.py key subagent scoping (ADR-0020) on it. */
    const subagentField = (sid: string) => (parentOf.get(sid) ? { agent_id: sid } : {});

    // ── 3. Prompt admission: remember the prompt, start the parent lookup ──
    await ctx.session.hook("prompt", (event: any) => {
      try {
        const sid = sidOf(event);
        const text = userText(event?.prompt?.text);
        if (!text || !sid) return;
        lookUpParent(sid);
        pendingPrompts.set(sid, [...(pendingPrompts.get(sid) ?? []), text]);
      } catch {
        // fail-open: admission proceeds untouched
      }
    });

    // ── 4. Model-call assembly: doctrine once per session + the per-turn enforcer block ──
    // The turn is handled at its first model call, once the parent lookup has landed: a
    // subagent's child session gets no doctrine, no menu and no turn row (Claude Code fires
    // no UserPromptSubmit inside a subagent).
    await ctx.session.hook("context", (event: any) => {
      try {
        const sid = sidOf(event);
        if (!sid) return;
        const child = !!parentOf.get(sid);
        // The lookup has not landed: governed as top level, and the turn row says so, so the
        // rate of possibly misgoverned child sessions is measured from real use (M7).
        const lookupPending = !parentOf.has(sid);
        const system: any[] = Array.isArray(event?.system) ? event.system : [];

        if (!doctrineDone.has(sid)) {
          const out = runHookJson(
            DOCTRINE_SCRIPT,
            { hook_event_name: "SessionStart", session_id: sid, ...subagentField(sid) },
            5_000,
          );
          const doctrine = out?.hookSpecificOutput?.additionalContext;
          if (typeof doctrine === "string" && doctrine.trim()) {
            system.push({ type: "text", text: doctrine.trim() });
          }
          doctrineDone.add(sid);   // pushed-or-not: never re-push within a session
        }

        const texts = pendingPrompts.get(sid);
        if (!texts) return;
        pendingPrompts.delete(sid);
        if (child) return;
        if (lookupPending) governedPending.add(sid);

        // Turn boundary per admitted prompt (ledger.py classifies UserPromptSubmit by
        // hook_event_name); the menu answers the latest one, the prompt this model call serves.
        for (const text of texts) {
          runLedger({ hook_event_name: "UserPromptSubmit", session_id: sid, prompt: text, harness: HARNESS,
                      ...(lookupPending ? { parent_lookup: "pending" } : {}) });
        }
        // Semantic enforcer — bounded; null on timeout/error means NO injection
        // (fail-open), never a blocked prompt.
        const out = runHookJson(ENFORCER_SCRIPT, { prompt: texts[texts.length - 1], session_id: sid }, 10_000);
        const block = out?.hookSpecificOutput?.additionalContext;
        if (typeof block === "string" && block.trim()) {
          system.push({ type: "text", text: block.trim() });
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

        // A refused or failed call is not a use: Claude Code fires no PostToolUse for it
        // (a blocklist-denied `skill` call arrives here with an error).
        if (event?.status !== "completed" || event?.error || event?.result?.metadata?.error) return;
        const base = { hook_event_name: "PostToolUse", session_id: sid, harness: HARNESS, ...subagentField(sid) };

        if (tool === "skill") {
          // Native skill activation. ledger.py's auto lane keys on tool_name + the `id`
          // input key (the OpenCode form of the Skill tool's name parameter).
          const payload = { ...base, tool_name: "skill", tool_input: { id: String(event?.input?.id ?? "") } };
          runLedger(payload);
          // Exclusion echo: a loaded skill's own "not for" lines bounce back so a body that
          // excludes the task forces an open re-rule, appended to the result (never replacing it).
          const echo = runExclusionsSync({ ...payload, tool_response: event?.result });
          if (echo && Array.isArray(event?.result?.content)) {
            event.result.content.push({ type: "text", text: echo });
          }
        } else if (tool.endsWith("skill-search_search_skills")) {
          runLedger({ ...base, tool_name: tool, tool_input: {} });
        } else if (tool.endsWith("skill-search_get_skill")) {
          const payload = { ...base, tool_name: tool, tool_input: { name: event?.input?.name } };
          runLedger(payload);   // ADR-0031 external-take leg: record the pulled name
          const echo = runExclusionsSync({ ...payload, tool_response: event?.result });
          if (echo && Array.isArray(event?.result?.content)) {
            event.result.content.push({ type: "text", text: echo });
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
        pendingPrompts.clear();
        parentOf.clear();
      } catch {
        // never throw from cleanup
      }
    };
  },
};
