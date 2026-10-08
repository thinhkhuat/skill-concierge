// Drives the Cline code plugin the way Cline's runtime does: one process, hooks called in
// sequence with runtime-shaped contexts. stdin: {"calls": [{"hook", "context", "pauseMs"}]};
// "hook" is a hook name or "setup". stdout: one JSON array of {result, ms}.
// usage: node cline_plugin_harness.mjs <plugin.ts>
import { readFileSync } from "node:fs";

const plugin = (await import(process.argv[2])).default;
const { calls } = JSON.parse(readFileSync(0, "utf8"));
const out = [];
for (const call of calls) {
  if (call.pauseMs) await new Promise((r) => setTimeout(r, call.pauseMs));
  const t0 = Date.now();
  let result;
  if (call.hook === "setup") {
    const rules = [];
    plugin.setup({ registerRule: (r) => rules.push(r) }, { session: { sessionId: "harness" } });
    result = { rules: await Promise.all(rules.map(async (r) => ({
      id: r.id, content: typeof r.content === "function" ? await r.content() : r.content,
    }))) };
  } else {
    result = (await plugin.hooks[call.hook](call.context)) ?? null;
  }
  out.push({ result, ms: Date.now() - t0 });
}
process.stdout.write(JSON.stringify(out));
