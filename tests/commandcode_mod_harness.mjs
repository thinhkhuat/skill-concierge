// Drives the Command Code mod the way Command Code's mod host does, against a stub `cmd`.
// stdin: {"calls": [...]}; each call is one of
//   {"hook": "transformInput", "text", "ctx"?}
//   {"hook": "transformContext", "messages", "state"?, "ctx"?}
//   {"hook": "afterToolCall", ...event}
//   {"event": "<name>", "payload": {...}}      an agent event on the mod bus (run_start, skill_loaded, ...)
// stdout: one JSON array, one entry per call: the hook's return value (null for events).
// `cmd.sessions.leafId()` answers a fresh tree-entry id on every call, like Command Code's.
// usage: node commandcode_mod_harness.mjs <skill-concierge.mod.ts>
import { readFileSync } from "node:fs";
import { dirname } from "node:path";

globalThis.__dirname = dirname(process.argv[2]);   // CommonJS global the mod reads; Node ESM does not provide it
const mod = (await import(process.argv[2])).default;
const { calls } = JSON.parse(readFileSync(0, "utf8"));
const hooks = {};
const handlers = {};
let leaf = 0;
const cmd = {
  hooks: (h) => Object.assign(hooks, h),
  on: (name, fn) => { (handlers[name] ??= []).push(fn); },
  sessions: { leafId: () => `tree-entry-${++leaf}` },
};
mod(cmd);

const out = [];
for (const call of calls) {
  if (call.event) {
    for (const fn of handlers[call.event] ?? []) await fn(call.payload ?? {});
    out.push(null);
  } else if (call.hook === "transformInput") {
    out.push(await hooks.transformInput({ text: call.text }, call.ctx));
  } else if (call.hook === "transformContext") {
    out.push(await hooks.transformContext({ messages: call.messages, state: call.state }, call.ctx));
  } else {
    out.push((await hooks[call.hook](call)) ?? null);
  }
}
process.stdout.write(JSON.stringify(out));
