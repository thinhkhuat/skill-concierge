/**
 * skill-concierge — Cline code plugin (ADR-0086). The primary Cline vehicle.
 *
 * Loaded from this checkout through a one-line loader the installer writes to
 * ~/.cline/plugins/skill-concierge.ts, so the plugin always runs this repo's
 * code (no installed copy to go stale). Cline runs it in its plugin sandbox,
 * where every hook call must answer within 3 s; each hook here answers within
 * HOOK_BUDGET_MS and fails open.
 *
 *   setup        SKILL-FIRST standing order as a system-prompt rule (read live
 *                from hooks/doctrine/skill-first.md) + detached self-heal batch,
 *                which also re-syncs the generated Agent Plugin (agent_plugin.py).
 *   beforeModel  per-turn enforcer menu, inserted right after the run's prompt.
 *                The request's message list is RETURNED IN FULL: Cline replaces
 *                the request messages with whatever this hook returns.
 *   beforeTool   blocklist deny: {skip, reason} refuses that one call only.
 *   afterTool    ledger capture + "not for" echo via appendContext (the tool's
 *                own output is never rewritten).
 *
 * The prompt is read in beforeModel because Cline calls beforeRun before it
 * adds the run's input message. Each run starts two enforcer passes: the full
 * one (Jev ranks the whole shelf) and a
 * fast preview (ENFORCER_JEV_ROUTER=0, ~0.3 s). The full pass runs on jevd's
 * TypeSafe tier only (ENFORCER_JEV_TIER=typesafe, ~0.7-0.9 s live), so the first
 * model call usually carries it; the preview covers a slow or failed pass, and
 * later calls carry the full menu once it lands. Both passes run with
 * ENFORCER_LEDGER=defer and hand their offer row back, so the turn's one offer
 * row is the menu the model saw first (`seen`); a full row that lands after the
 * preview was sent is kept as `offer_late` (ADR-0087).
 * Subagents (snapshot.parentAgentId set) get no menu and write no turn row
 * (ADR-0020). Fail-open everywhere: a broken plugin is a plain Cline session.
 */

import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// Cline times each sandboxed hook at 3 s from the moment it sends the call, so the conversation
// travels in and out inside that window too; 2 s leaves room for a long transcript.
const HOOK_BUDGET_MS = 2000;
const ENFORCER_TIMEOUT_MS = 20000;
// ADR-0087 (owner's choice: TypeSafe only for Cline): the full pass runs on jevd's TypeSafe tier alone,
// whose full route (~0.7-0.9 s live) fits the first model call's 2 s wait; Command Code's takes 2-2.5 s.
const JEV_TIER = "typesafe";
const MAX_TRACKED_RUNS = 32;

type Json = Record<string, unknown>;

function findRoot(): string | null {
  const own = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..");
  for (const c of [own, process.env.SKILL_CONCIERGE_ROOT ?? ""]) {
    if (c && existsSync(join(c, "hooks", "scripts", "enforcer.py"))) return c;
  }
  return null;
}

const ROOT = findRoot();
const script = (name: string) => (ROOT ? join(ROOT, "hooks", "scripts", name) : "");
const ENV = { ...process.env, SKILL_CONCIERGE_HARNESS: "cline" };
const SELF_HEAL = ["auto_reindex.py", "auto_overrides.py", "auto_flywheel.py", "auto_promote.py"];

/** Run a hook script without blocking the sandbox; null on any failure or timeout. */
function run(name: string, payload: unknown, timeoutMs: number, args: string[] = [],
  env: Record<string, string> = {}): Promise<string | null> {
  const path = script(name);
  if (!path || !existsSync(path)) return Promise.resolve(null);
  return new Promise((done) => {
    let out = "";
    let settled = false;
    const finish = (v: string | null) => { if (!settled) { settled = true; clearTimeout(timer); done(v); } };
    let child: ReturnType<typeof spawn>;
    try {
      child = spawn("python3", [path, ...args], { env: { ...ENV, ...env }, stdio: ["pipe", "pipe", "ignore"] });
    } catch { finish(null); return; }
    const timer = setTimeout(() => { try { child.kill("SIGKILL"); } catch { /* gone */ } finish(null); }, timeoutMs);
    child.on("error", () => finish(null));
    child.stdout?.setEncoding("utf8");   // a multi-byte character split across chunks stays whole
    child.stdout?.on("data", (d: unknown) => { out += String(d); });
    child.on("close", (code: number | null) => finish(code === 0 ? out : null));
    child.stdin?.on("error", () => { /* script exited before reading */ });
    child.stdin?.end(JSON.stringify(payload ?? {}));
  });
}

/** Fire-and-forget (ledger rows, self-heal): never awaited, never blocks a hook. */
function fire(path: string, payload?: unknown, args: string[] = []): void {
  if (!path || !existsSync(path)) return;
  try {
    const child = spawn("python3", [path, ...args], { env: ENV, stdio: ["pipe", "ignore", "ignore"], detached: true });
    child.on("error", () => { /* fail-silent telemetry */ });
    child.stdin?.on("error", () => { /* ignore */ });
    child.stdin?.end(JSON.stringify(payload ?? {}));
    child.unref();
  } catch { /* fail-silent telemetry */ }
}

function lastJson(stdout: string | null): Json | null {
  const line = String(stdout ?? "").trim().split("\n").map((l) => l.trim()).filter((l) => l.startsWith("{")).pop();
  if (!line) return null;
  try { const p = JSON.parse(line); return p && typeof p === "object" ? p : null; } catch { return null; }
}

function hookSpecific(stdout: string | null): Json {
  return (lastJson(stdout)?.["hookSpecificOutput"] as Json | undefined) ?? {};
}

function additionalContext(stdout: string | null): string {
  const ctx = hookSpecific(stdout)["additionalContext"];
  return typeof ctx === "string" ? ctx.trim() : "";
}

function wait<T>(p: Promise<T>, ms: number): Promise<T | undefined> {
  if (ms <= 0) return Promise.resolve(undefined);
  let timer: ReturnType<typeof setTimeout> | undefined;
  const limit = new Promise<undefined>((r) => { timer = setTimeout(() => r(undefined), ms); });
  return Promise.race([p, limit]).finally(() => clearTimeout(timer));
}

function textOf(message: Json): string {
  const content = message["content"];
  if (!Array.isArray(content)) return "";
  return content.filter((p) => (p as Json)?.["type"] === "text")
    .map((p) => String((p as Json)["text"] ?? "")).join("\n").trim();
}

/** The run's prompt: the newest user message that is not hook context or a runtime reminder. */
function findPrompt(messages: readonly Json[]): { id: string; text: string } | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.["role"] !== "user") continue;
    const meta = (m["metadata"] as Json | undefined) ?? {};
    // Hook context carries displayRole "system"; runtime reminders ("[SYSTEM] This run is not
    // complete…") carry userRunSpan 0. Typed input carries neither (Cline's own rule).
    if (meta["displayRole"] === "system" || meta["userRunSpan"] === 0) continue;
    let text = textOf(m);
    if (!text || text.startsWith("<hook_context") || text.startsWith("[SYSTEM]")) continue;
    // Cline wraps typed input as <user_input mode="act">…</user_input>.
    const wrapped = /^<user_input\b[^>]*>([\s\S]*?)<\/user_input>\s*$/.exec(text);
    if (wrapped) text = wrapped[1].trim();
    return text ? { id: String(m["id"] ?? ""), text } : null;
  }
  return null;
}

function sessionIdOf(snapshot: Json | undefined): string {
  return String(snapshot?.["conversationId"] ?? snapshot?.["agentId"] ?? "") || setupSessionId || "cline";
}

function isSubagent(snapshot: Json | undefined): boolean {
  const parent = snapshot?.["parentAgentId"];
  return typeof parent === "string" && parent.length > 0;
}

/**
 * Skill-tool lane for the ledger: "skill" | "search" | "get" | "". Cline names an MCP tool
 * `<server>__<tool>` plus, for an Agent Plugin server, a hash suffix
 * (`skill-concierge_skill-search__get_skill_d998a651`).
 */
function lane(toolName: string): string {
  if (toolName === "skills" || toolName === "use_skill") return "skill";
  const mcp = /(?:^|__)(search_skills|get_skill)(?:_[0-9a-f]{8})?$/.exec(toolName);
  if (mcp) return mcp[1] === "search_skills" ? "search" : "get";
  return "";
}

/** A menu one pass produced: its text and the offer row it would log. */
type Menu = { text: string; offer?: Json };
type RunState = {
  promptId: string; sid: string; menu: Promise<string>; value?: string; offer?: Json;
  preview?: Menu; chosen?: string; seen?: string;
};
const runs = new Map<string, RunState>();
let setupSessionId = "";

function offerOf(stdout: string | null): Json | undefined {
  const o = lastJson(stdout)?.["skillConciergeOffer"];
  return o && typeof o === "object" ? (o as Json) : undefined;
}

function logOffer(offer: Json | undefined, seen: string, ev?: string): void {
  if (offer) fire(script("ledger.py"), { hook_event_name: "ConciergeOffer", offer: { ...offer, ev: ev ?? offer["ev"], seen } });
}

/**
 * Called once, at the run's first model call: pick the best menu ready now and log its offer row.
 * Order (ADR-0087): the full pass (TypeSafe's full Jev route), then the embedding preview. A full row that
 * lands after the preview was sent is kept as `offer_late`, which offer counts never read.
 */
function recordSeen(state: RunState): void {
  const fullDone = state.value !== undefined;
  const picks: [string, Menu | undefined][] = [
    ["full", fullDone ? { text: state.value as string, offer: state.offer } : undefined], ["preview", state.preview]];
  const hit = picks.find(([, m]) => m && m.text);
  if (!hit) {
    state.seen = "none";   // no menu yet: the full row is logged when it lands (seen "late")
    if (fullDone) { state.seen = "full"; logOffer(state.offer, "full"); }
    return;
  }
  const [seen, menu] = hit as [string, Menu];
  state.seen = seen;
  state.chosen = menu.text;
  logOffer(menu.offer, seen);
  if (seen !== "full" && fullDone) logOffer(state.offer, "later", "offer_late");
}

function startRun(runId: string, prompt: { id: string; text: string }, sid: string): RunState {
  fire(script("ledger.py"), { hook_event_name: "UserPromptSubmit", session_id: sid, prompt: prompt.text, harness: "cline" });
  const payload = { prompt: prompt.text, session_id: sid };
  const state = { promptId: prompt.id, sid } as RunState;
  state.menu = run("enforcer.py", payload, ENFORCER_TIMEOUT_MS, [],
    { ENFORCER_LEDGER: "defer", ENFORCER_JEV_TIER: JEV_TIER }).then((out) => {
    state.offer = offerOf(out);
    return additionalContext(out);
  });
  // Same callback as the value, so recordSeen never sees a menu without its done-ness.
  const settle = (v: string) => {
    state.value = v;
    if (state.seen === "none") logOffer(state.offer, "late");
    else if (state.seen && state.seen !== "full") logOffer(state.offer, "later", "offer_late");
  };
  state.menu.then(settle, () => settle(""));
  run("enforcer.py", payload, HOOK_BUDGET_MS, [], { ENFORCER_JEV_ROUTER: "0", ENFORCER_LEDGER: "defer" })
    .then((out) => { state.preview = { text: additionalContext(out), offer: offerOf(out) }; },
      () => { /* full menu only */ });
  runs.set(runId, state);
  while (runs.size > MAX_TRACKED_RUNS) runs.delete(runs.keys().next().value as string);
  return state;
}

function withMenu(messages: readonly Json[], promptId: string, menu: string): Json[] {
  const now = Date.now();
  const block: Json = {
    id: `skill-concierge-${now}`, role: "user", createdAt: now, metadata: { displayRole: "system" },
    content: [{ type: "text", text: `<hook_context source="skill-concierge">\n${menu}\n</hook_context>` }],
  };
  const list = [...messages];
  const at = list.findIndex((m) => String(m?.["id"] ?? "") === promptId);
  list.splice(at >= 0 ? at + 1 : list.length, 0, block);
  return list;
}

async function doctrineRule(): Promise<string> {
  // SKILL_CONCIERGE_HARNESS=cline (ENV) selects the Cline rendering of the standing order.
  return additionalContext(await run("doctrine.py", {}, HOOK_BUDGET_MS * 3));
}

const plugin = {
  name: "skill-concierge",
  manifest: { capabilities: ["rules", "hooks"] },

  setup(api: { registerRule: (rule: Json) => void }, ctx: { session?: { sessionId?: string } }) {
    if (!ROOT) return;
    setupSessionId = ctx?.session?.sessionId?.trim() || "";
    api.registerRule({ id: "skill-concierge:skill-first", source: "skill-concierge", content: doctrineRule });
    for (const name of SELF_HEAL) fire(script(name));
    // Keep the generated Agent Plugin (skills + MCP) in step with this checkout (next session).
    fire(join(ROOT, "adapters", "cline", "agent_plugin.py"), {}, ["sync"]);
  },

  hooks: {
    async beforeModel(context: Json) {
      const started = Date.now();
      try {
        const snapshot = context["snapshot"] as Json | undefined;
        const request = context["request"] as Json | undefined;
        const messages = (request?.["messages"] ?? []) as readonly Json[];
        if (!ROOT || isSubagent(snapshot) || !messages.length) return undefined;
        const runId = String(snapshot?.["runId"] ?? "");
        let state = runs.get(runId);
        if (!state) {
          const prompt = findPrompt(messages);
          if (!prompt) return undefined;
          state = startRun(runId, prompt, sessionIdOf(snapshot));
          await wait(state.menu, HOOK_BUDGET_MS - (Date.now() - started));
          recordSeen(state);
        }
        const menu = state.value || state.chosen;
        if (!menu) return undefined;
        return { messages: withMenu(messages, state.promptId, menu) };
      } catch { return undefined; }
    },

    async beforeTool(context: Json) {
      try {
        const call = (context["toolCall"] as Json | undefined) ?? {};
        if (lane(String(call["toolName"] ?? "")) !== "skill") return undefined;
        const input = ((context["input"] ?? call["input"]) ?? {}) as Json;
        const name = String(input["skill"] ?? input["name"] ?? "").trim().replace(/^\/+/, "");
        if (!name) return undefined;
        const out = await run("skill_guard.py", { tool_name: "Skill", tool_input: { skill: name } }, HOOK_BUDGET_MS);
        const hs = hookSpecific(out);
        if (hs["permissionDecision"] !== "deny") return undefined;
        const reason = String(hs["permissionDecisionReason"] ?? "")
          || `Skill '${name}' is disabled by the skill-concierge blocklist.`;
        return { skip: true, reason };
      } catch { return undefined; }
    },

    async afterTool(context: Json) {
      try {
        const call = (context["toolCall"] as Json | undefined) ?? {};
        const which = lane(String(call["toolName"] ?? ""));
        if (!ROOT || !which) return undefined;
        const snapshot = context["snapshot"] as Json | undefined;
        const input = ((context["input"] ?? call["input"]) ?? {}) as Json;
        const result = (context["result"] as Json | undefined) ?? {};
        const payload = {
          hook_event_name: "PostToolUse", session_id: sessionIdOf(snapshot), harness: "cline",
          tool_name: which === "skill" ? "Skill" : `skill-search__${which === "search" ? "search_skills" : "get_skill"}`,
          tool_input: input,
          // ledger.py stamps `sub` from agent_id, so subagent uses stay out of main-session counts.
          ...(isSubagent(snapshot) ? { agent_id: String(snapshot?.["agentId"] ?? "subagent") } : {}),
        };
        // A refused or failed call is not a use (Claude Code fires no PostToolUse for it).
        if (result["isError"] === true) return undefined;
        fire(script("ledger.py"), payload);
        if (which === "search") return undefined;
        const echo = additionalContext(await run("skill_exclusions.py",
          { ...payload, tool_response: result["output"] ?? null }, HOOK_BUDGET_MS));
        return echo ? { appendContext: echo } : undefined;
      } catch { return undefined; }
    },
  },
};

export { plugin };
export default plugin;
