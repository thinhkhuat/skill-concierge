// Drives the OpenCode v2 plugin the way OpenCode's server does: setup(ctx) once, then hook
// events in sequence. stdin: {"sessions": {sid: {parentID?}}, "calls": [{"hook", "event", "pauseMs"}]};
// "hook" is "setup", "prompt", "context", "evaluate" or "execute.after". stdout: one JSON array
// of {event, servers?, ms} — each event as the plugin left it (system parts, result content, effect).
// usage: node opencode_plugin_harness.mjs <index.ts>
import { readFileSync } from "node:fs";
import { dirname } from "node:path";

globalThis.__dirname = dirname(process.argv[2]);   // Bun provides __dirname to plugins; Node ESM does not
const plugin = (await import(process.argv[2])).default;
const { sessions = {}, calls } = JSON.parse(readFileSync(0, "utf8"));
const hooks = {};
const servers = {};
const ctx = {
  mcp: { transform: async (fn) => fn({ set: (name, cfg) => { servers[name] = cfg; } }) },
  session: {
    hook: async (name, fn) => { hooks[name] = fn; },
    get: async ({ sessionID }) => ({ id: sessionID, ...(sessions[sessionID] ?? {}) }),
  },
  permission: { hook: async (name, fn) => { hooks[name] = fn; } },
  tool: { hook: async (name, fn) => { hooks[name] = fn; } },
};
const out = [];
for (const call of calls) {
  if (call.pauseMs) await new Promise((r) => setTimeout(r, call.pauseMs));
  const t0 = Date.now();
  if (call.hook === "setup") {
    await plugin.setup(ctx);
    out.push({ servers, ms: Date.now() - t0 });
    continue;
  }
  const event = call.event;
  await hooks[call.hook](event);
  out.push({ event, ms: Date.now() - t0 });
}
process.stdout.write(JSON.stringify(out));
