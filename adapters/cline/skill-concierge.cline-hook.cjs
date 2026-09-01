#!/usr/bin/env node
/**
 * skill-concierge — Cline file-hook bridge (ADR-0051).
 *
 * Single dispatch point for the two Cline file hooks the installer drops into
 * ~/.cline/hooks/ (UserPromptSubmit.cjs / PostToolUse.cjs shims require this
 * module with a mode argument). Cline maps hook FILE NAMES to events
 * (hook-file-config.ts): `UserPromptSubmit.*` -> prompt_submit, `PostToolUse.*`
 * -> tool_result. Multiple same-event files co-fire and their `context`
 * strings are merged (hook-file-hooks.ts mergeHookControls), so the operator's
 * own extension-less bridges are never touched.
 *
 * Cline 3.0.60 payload contract (binary Zod schemas, confirmed by the
 * operator's existing bridges):
 *   prompt_submit : { userPromptSubmit: { prompt, attachments }, taskId, ... }
 *   tool_result   : { postToolUse: { toolName, parameters, result, success, executionTimeMs } }
 *   out           : { cancel: bool, contextModification?: string }
 *
 * Modes:
 *   prompt_submit — (a) once per session (TTL-swept flag file; file hooks are
 *   stateless processes): doctrine.py + detached auto_reindex/auto_overrides/
 *   auto_flywheel/auto_promote; (b) ledger UserPromptSubmit turn row;
 *   (c) enforcer.py mandate + ranked preview wrapped in <hook_context>.
 *   tool_result   — ledger capture only: `use_skill`/`skills` -> the Skill-tool `auto`
 *   lane; the flattened `skill-search__search_skills`/`skill-search__get_skill` MCP
 *   names -> the `search`/`get_skill` lanes (live-verified 2026-09-01, Cline 3.0.60
 *   Claude Agent SDK runtime; `use_mcp_tool` kept for the classical surface).
 *   ADR-0051 §4.
 *
 * Fail-open everywhere: any throw returns {cancel:false} — a dead bridge
 * degrades to a plain Cline session, never a blocked turn.
 */
"use strict";

const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawn, spawnSync } = require("child_process");

function resolvePluginRoot() {
  if (process.env.SKILL_CONCIERGE_ROOT && fs.existsSync(process.env.SKILL_CONCIERGE_ROOT)) {
    return process.env.SKILL_CONCIERGE_ROOT;
  }
  // __dirname = <repo>/adapters/cline
  const candidate = path.resolve(__dirname, "..", "..");
  if (fs.existsSync(path.join(candidate, "hooks", "scripts", "enforcer.py"))) {
    return candidate;
  }
  const fallback = path.join(os.homedir(), "in-PROD", "MY-WORKBENCH", "skill-concierge");
  if (fs.existsSync(path.join(fallback, "hooks", "scripts", "enforcer.py"))) {
    return fallback;
  }
  return candidate;
}

const PLUGIN_ROOT = resolvePluginRoot();
const ENFORCER = path.join(PLUGIN_ROOT, "hooks", "scripts", "enforcer.py");
const DOCTRINE = path.join(PLUGIN_ROOT, "hooks", "scripts", "doctrine.py");
const LEDGER = path.join(PLUGIN_ROOT, "hooks", "scripts", "ledger.py");
const AUTO_SCRIPTS = ["auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"]
  .map((n) => path.join(PLUGIN_ROOT, "hooks", "scripts", n));
const CLINE_ENV = { ...process.env, SKILL_CONCIERGE_HARNESS: "cline" };
const STATE_DIR = path.join(os.homedir(), ".claude", "skill-concierge");
const SESSION_TTL_MS = 24 * 60 * 60 * 1000;

const out = (o) => { process.stdout.write(JSON.stringify(o) + "\n"); process.exit(0); };
const failOpen = () => out({ cancel: false });

function additionalContext(stdout) {
  try {
    const lines = String(stdout || "").trim().split("\n")
      .filter((l) => l.trim().startsWith("{"));
    if (!lines.length) return "";
    const j = JSON.parse(lines[lines.length - 1]);
    return j && j.hookSpecificOutput && j.hookSpecificOutput.additionalContext
      ? String(j.hookSpecificOutput.additionalContext) : "";
  } catch { return ""; }
}

function runScript(script, payload, timeout) {
  try {
    if (!fs.existsSync(script)) return null;
    const r = spawnSync("python3", [script], {
      input: JSON.stringify(payload), timeout: timeout || 10000, encoding: "utf8", env: CLINE_ENV,
    });
    return r.status === 0 ? (r.stdout || "") : null;
  } catch { return null; }
}

function fireDetached(script) {
  try {
    if (!fs.existsSync(script)) return;
    const child = spawn("python3", [script], { env: CLINE_ENV, stdio: "ignore", detached: true });
    child.unref();
  } catch { /* fail-silent maintenance */ }
}

function sweepSessionFlags() {
  try {
    for (const f of fs.readdirSync(STATE_DIR)) {
      if (!f.startsWith("cline-session-")) continue;
      const p = path.join(STATE_DIR, f);
      try {
        if (Date.now() - fs.statSync(p).mtimeMs > SESSION_TTL_MS) fs.unlinkSync(p);
      } catch { /* raced removal is fine */ }
    }
  } catch { /* no state dir yet */ }
}

function doctrineOncePerSession(taskId) {
  try {
    fs.mkdirSync(STATE_DIR, { recursive: true });
    sweepSessionFlags();
    const key = String(taskId || "unknown").replace(/[^A-Za-z0-9_-]/g, "").slice(0, 64) || "unknown";
    const flag = path.join(STATE_DIR, `cline-session-${key}.flag`);
    if (fs.existsSync(flag)) return "";
    fs.writeFileSync(flag, String(Date.now()));
    for (const s of AUTO_SCRIPTS) fireDetached(s);
    const doctrineOut = runScript(DOCTRINE, {
      hook_event_name: "SessionStart", session_id: taskId || "cline-hook",
    }, 8000);
    return additionalContext(doctrineOut);
  } catch { return ""; }
}

function promptSubmit(payload) {
  const ups = payload.userPromptSubmit || {};
  const prompt = String(ups.prompt || "");
  if (!prompt.trim()) return failOpen();
  const sid = String(payload.taskId || "cline-hook");

  const contexts = [];
  const doctrine = doctrineOncePerSession(sid);
  if (doctrine.trim()) contexts.push(doctrine.trim());

  runScript(LEDGER, {
    hook_event_name: "UserPromptSubmit", session_id: sid, prompt, harness: "cline",
  }, 5000);

  const enforced = runScript(ENFORCER, { prompt, session_id: sid }, 20000);
  const ctx = additionalContext(enforced);
  if (ctx.trim()) {
    contexts.push(`<hook_context source="skill-concierge">\n${ctx.trim()}\n</hook_context>`);
  }
  out(contexts.length ? { cancel: false, contextModification: contexts.join("\n\n") } : { cancel: false });
}

function toolResult(payload) {
  const ptu = payload.postToolUse || {};
  const toolName = String(ptu.toolName || "");
  const params = (ptu.parameters && typeof ptu.parameters === "object") ? ptu.parameters : {};
  const sid = String(payload.taskId || "cline-hook");

  const isSkillLane = toolName === "use_skill" || toolName === "skills";
  if (isSkillLane) {
    // Ledger's Skill-tool lane matches tool_name "Skill"/"activate_skill" and reads
    // the name from the _NAME_KEYS set over tool_input — forward the raw parameters.
    // `skills` is the live Cline 3.0.60 name (verified 2026-09-01); `use_skill` is
    // kept for the classical Cline surface.
    runScript(LEDGER, {
      hook_event_name: "PostToolUse", session_id: sid, harness: "cline",
      tool_name: "Skill", tool_input: params,
    }, 5000);
  } else if (toolName === "skill-search__search_skills" || toolName === "skill-search__get_skill") {
    // LIVE-VERIFIED 2026-09-01 (Cline 3.0.60, Claude Agent SDK runtime): MCP tools
    // arrive FLATTENED as `<server>__<tool>` with the tool args directly in the
    // parameters (no {tool_name, arguments} wrapper) — ADR-0051 §4 caveat closed.
    // Payload shape `postToolUse:{toolName, parameters,...}` confirmed from the
    // shipped binary's own hook-contract construction.
    runScript(LEDGER, {
      hook_event_name: "PostToolUse", session_id: sid, harness: "cline",
      tool_name: toolName,
      tool_input: params,
    }, 5000);
  } else if (toolName === "use_mcp_tool") {
    // Classical Cline surface (VS Code extension runs): the server/tool pair
    // arrives in parameters. Map onto the ledger's suffix-matched MCP lanes.
    const tname = String(params.tool_name || "");
    if (tname.endsWith("search_skills") || tname.endsWith("get_skill")) {
      runScript(LEDGER, {
        hook_event_name: "PostToolUse", session_id: sid, harness: "cline",
        tool_name: tname.includes("get_skill") ? "skill-search__get_skill" : "skill-search__search_skills",
        tool_input: params.arguments && typeof params.arguments === "object" ? params.arguments : {},
      }, 5000);
    }
  }
  // Anything else is not skill-concierge traffic — silent pass-through.
  out({ cancel: false });
}

function main(mode) {
  let payload;
  try { payload = JSON.parse(fs.readFileSync(0, "utf8")); } catch { return failOpen(); }
  if (!payload || typeof payload !== "object") return failOpen();
  if (mode === "prompt_submit") return promptSubmit(payload);
  if (mode === "tool_result") return toolResult(payload);
  return failOpen();
}

module.exports = function dispatch(mode) {
  try { main(mode); } catch { failOpen(); }
};

// Direct execution (node skill-concierge.cline-hook.cjs <mode>) for testing.
if (require.main === module) {
  module.exports(process.argv[2] || "");
}

