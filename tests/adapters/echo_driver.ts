/**
 * Drives one adapter's skill-load handler the way its host calls it and prints the
 * handler's return value as JSON. The event and return shapes are the hosts' own
 * (cited in each adapter's header); only the host object is a stand-in.
 * Usage: bun tests/adapters/echo_driver.ts <omp|commandcode|dsh> <case>
 */
const [, , which, kase] = process.argv;
const root = new URL("../../adapters/", import.meta.url).pathname;

async function main(): Promise<unknown> {
  if (which === "omp") {
    const handlers: Record<string, Function> = {};
    (await import(root + "omp/skill-concierge.ext.ts")).default({ on: (ev: string, fn: Function) => (handlers[ev] = fn) });
    const path = kase === "subresource" ? "skill://echo-fixture/references/x.md" : "skill://echo-fixture";
    const toolName = kase === "other" ? "bash" : "read";
    return handlers.tool_result(
      { toolName, input: { path }, content: [{ type: "text", text: "ORIGINAL BODY" }], isError: false },
      { sessionManager: { getSessionId: () => "drv" } });
  }
  if (which === "commandcode") {
    const hooks: Record<string, Function> = {};
    (await import(root + "commandcode/skill-concierge.mod.ts")).default({
      hooks: (h: Record<string, Function>) => Object.assign(hooks, h), on: () => {}, sessions: {} });
    const toolName = kase === "other" ? "read_file" : kase === "get_skill" ? "mcp__skill-search__get_skill" : "activate_skill";
    return hooks.afterToolCall({ toolCallId: "c1", toolName, input: { name: "echo-fixture" }, result: [], isError: false, state: {} });
  }
  if (which === "dsh" && kase === "prestep") {
    const handlers: Record<string, Function> = {};
    (await import(root + "dsh/skill-concierge.dsh.ts")).default({ on: (ev: string, fn: Function) => (handlers[ev] = fn) });
    const agent = (id: string, parent?: string) => ({ session: { header: { id, ...(parent ? { parentSession: parent } : {}) } } });
    const step = async (a: any) => (await handlers["agent/pre-step"](
      { agent: a, messages: [], step: 1 }, async () => ({ kind: "enter", messages: [] }))).messages.length;
    return { sub: await step(agent("s1", "parent")), mainFirst: await step(agent("s2")),
             mainAgain: await step(agent("s2")), otherSession: await step(agent("s3")) };
  }
  if (which === "dsh") {
    const handlers: Record<string, Function> = {};
    (await import(root + "dsh/skill-concierge.dsh.ts")).default({ on: (ev: string, fn: Function) => (handlers[ev] = fn) });
    const name = kase === "other" ? "bash" : "skill";
    return handlers["tools/post-execute"](
      { name, arguments: { name: "echo-fixture" }, callId: "d1" }, { content: [] },
      async () => ({ kind: "accept", additionalContexts: [{ role: "user", content: [{ type: "text", text: "DOWNSTREAM" }] }] }));
  }
  throw new Error("unknown adapter " + which);
}

main().then((r) => console.log(JSON.stringify(r ?? null)), (e) => { console.error(e); process.exit(1); });
