import test from "node:test";
import assert from "node:assert/strict";
import {
  mkdirSync,
  existsSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
  symlinkSync,
  chmodSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { execFileSync } from "node:child_process";

import { getMemsearchDir, getCollectionScopeDir, createTranscriptAccess } from "./index.ts";
import plugin from "./index.ts";

function withEnv(key: string, value: string | undefined, fn: () => void): void {
  const prev = process.env[key];
  if (value === undefined) {
    delete process.env[key];
  } else {
    process.env[key] = value;
  }
  try {
    fn();
  } finally {
    if (prev === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = prev;
    }
  }
}

async function withEnvAsync(
  values: Record<string, string | undefined>,
  fn: () => Promise<void>
): Promise<void> {
  const previous = new Map<string, string | undefined>();
  for (const [key, value] of Object.entries(values)) {
    previous.set(key, process.env[key]);
    if (value === undefined) {
      delete process.env[key];
    } else {
      process.env[key] = value;
    }
  }
  try {
    await fn();
  } finally {
    for (const [key, value] of previous) {
      if (value === undefined) {
        delete process.env[key];
      } else {
        process.env[key] = value;
      }
    }
  }
}

function registerPluginHooks(pluginConfig: Record<string, unknown> = {}): Map<string, (...args: any[]) => any> {
  const hooks = new Map<string, (...args: any[]) => any>();
  plugin.register({
    logger: {},
    pluginConfig,
    runtime: {
      system: {
        async runCommandWithTimeout(argv: string[]) {
          if (argv[0] === "which") {
            return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
          }
          if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
            return { stdout: "ms_hook_test\n", stderr: "", code: 0 };
          }
          return { stdout: "", stderr: "", code: 0 };
        },
      },
    },
    registerTool() {},
    registerCli() {},
    on(name: string, handler: (...args: any[]) => any) {
      hooks.set(name, handler);
    },
  });
  return hooks;
}

test("getMemsearchDir: defaults to <projectDir>/.memsearch", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.equal(getMemsearchDir(dir), join(dir, ".memsearch"));
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("agent_end uses hook context before any tool factory and emits a usable named-profile anchor", async () => {
  const home = mkdtempSync(join(tmpdir(), "memsearch-provenance-"));
  const workspace = join(home, "isolated-workspace");
  const state = join(home, ".openclaw-review");
  const sessionId = "746-context-session";
  const transcript = join(state, "agents", "main", "sessions", `${sessionId}.jsonl`);
  const messages = [
    { role: "user", content: "Remember the synthetic review project fact: the calibration mascot is silver heron 746." },
    { role: "assistant", content: "The synthetic calibration mascot is silver heron 746." },
  ];
  mkdirSync(join(state, "agents", "main", "sessions"), { recursive: true });
  writeFileSync(transcript, messages.map(message => JSON.stringify({ type: "message", message })).join("\n"));
  try {
    await withEnvAsync({ HOME: home, OPENCLAW_PROFILE: "review", OPENCLAW_STATE_DIR: state,
      MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined }, async () => {
      const hooks = new Map<string, (...args: any[]) => any>();
      const factories = new Map<string, (ctx: any) => any>();
      plugin.register({
        logger: {}, pluginConfig: {},
        runtime: { system: { async runCommandWithTimeout(argv: string[]) {
          if (argv[1]?.endsWith("parse-transcript.sh")) {
            return { stdout: execFileSync(argv[0], argv.slice(1), { encoding: "utf8" }), stderr: "", code: 0 };
          }
          const cmd = argv.join(" ");
          const stdout = argv[0] === "which" ? "/test/memsearch" :
            cmd.includes("derive-collection") ? "ms_provenance" :
            cmd.includes("config get") && cmd.includes("summarize.provider") ? "test" :
            cmd.includes("summarize --plugin") ? "- Calibration mascot: silver heron 746." : "";
          return { stdout, stderr: "", code: 0 };
        } } },
        registerTool(factory: (ctx: any) => any, meta: { name: string }) { factories.set(meta.name, factory); },
        registerCli() {}, on(name: string, fn: (...args: any[]) => any) { hooks.set(name, fn); },
      });
      const ctx = { agentId: "main", workspaceDir: workspace, sessionId, sessionKey: "agent:main:review" };
      // This is the actual host hook signature: session provenance is not in the event.
      await hooks.get("agent_end")!({ success: true, messages }, ctx);
      const file = join(workspace, ".memsearch", "memory", `${new Date().toISOString().slice(0, 10)}.md`);
      assert.ok(existsSync(file), "capture must use hook workspace without a tool invocation");
      const memory = readFileSync(file, "utf8");
      const anchor = memory.match(/<!-- session:(\S+) transcript:(\S+) -->/);
      assert.ok(anchor, "capture must generate provenance automatically");
      assert.equal(anchor[1], sessionId);
      assert.equal(anchor[2], transcript);
      const tool = factories.get("memory_transcript")!({ ...ctx, sessionId: "fresh-session" });
      const result = await tool.execute("recall", { transcript_path: anchor[2] });
      assert.match(result.content[0].text, /\[User\]:.*silver heron 746/);
      assert.match(result.content[0].text, /\[Assistant\]:.*silver heron 746/);
      const recalled = await hooks.get("before_prompt_build")!({}, ctx);
      assert.match(recalled.prependContext, /silver heron 746/);
    });
  } finally { rmSync(home, { recursive: true, force: true }); }
});

// Scope/identity tests inject a permissive policy; the optional SDK contract
// test exercises the actual published visibility implementation and SQLite.
const allowHistoryPolicy = {
  parseAgentSessionKey: (key: string) => /^agent:([^:]+):.+$/.exec(key) && { agentId: key.split(":")[1] },
  isIncognitoSessionKey: (key: string) => key.split(":").includes("incognito"),
  isSubagentSessionKey: (key: string) => key.includes(":subagent:"),
  isAcpSessionKey: (key: string) => key.includes(":acp:"),
  buildAgentMainSessionKey: ({ agentId }: any) => `agent:${agentId}:main`,
  resolveEffectiveSessionToolsVisibility: () => "all",
  createAgentToAgentPolicy: () => ({}),
  createSessionVisibilityRowChecker: () => ({ check: () => ({ allowed: true }) }),
};

test("SDK transcript scope, exact metadata and live guards cannot be replaced by a reference", async () => {
  const scope = { agentId: "review", sessionId: "old-session", sessionKey: "agent:review:capture", storePath: "/isolated profile/agents/review/sessions/sessions.json" };
  let failure = "", reads = 0;
  let entry: any = { sessionId: scope.sessionId };
  let config: any = { session: { store: scope.storePath } };
  const runtime = { agent: { session: {
    resolveStorePath: (configured: string) => configured,
    async getSessionEntryAsync(target: any) {
      assert.equal(target.sessionKey, scope.sessionKey);
      assert.equal(target.storePath, scope.storePath);
      assert.equal(target.readConsistency, "latest");
      return entry;
    },
  } } };
  const sdk = {
    async resolveSessionTranscriptIdentity(target: any) {
      assert.deepEqual(target, scope);
      if (failure === "denied") throw new Error("host denied transcript access");
      return { ...scope, sessionKey: failure === "key" ? "agent:review:replacement" : scope.sessionKey,
        sessionId: failure === "reset" ? "replacement-session" : scope.sessionId };
    },
    async readVisibleSessionTranscriptMessageEntries(target: any) {
      assert.deepEqual(target, scope); reads++;
      if (failure === "metadata-reset") entry = { sessionId: "replacement" };
      if (failure === "store-reset") config = { session: { store: "/different/store.json" } };
      return [
        { message: { role: "user", content: "earlier turn" } },
        { message: { role: "user", content: "synthetic SDK marker 746" } },
        { message: { role: "assistant", content: [{ type: "text", text: "synthetic SDK answer" }] } },
      ];
    },
  };
  const access = createTranscriptAccess(runtime, config, async () => sdk, async () => allowHistoryPolicy);
  const reference = await access.capture(scope);
  const caller = { agentId: scope.agentId, sessionId: "fresh-session", sessionKey: "agent:review:fresh",
    getRuntimeConfig: () => config };
  const output = await access.read(reference, caller);
  assert.match(output!, /\[User\]: synthetic SDK marker 746/);
  assert.match(output!, /\[Assistant\]: synthetic SDK answer/);
  assert.doesNotMatch(output!, /earlier turn/);
  for (failure of ["reset", "key", "denied"]) await assert.rejects(access.read(reference, caller), /identity changed|host denied/);
  failure = "";
  for (entry of [undefined, { sessionId: "other" }, { sessionId: scope.sessionId, visibility: "draft" },
    { sessionId: scope.sessionId, visibility: "unknown" }, { sessionId: scope.sessionId, incognito: true }]) {
    await assert.rejects(access.read(reference, caller), /Target session metadata/);
  }
  entry = { sessionId: scope.sessionId };
  for (const overrides of [
    { agentId: "other" }, { sessionKey: undefined }, { sessionKey: "main" },
    { sessionKey: "agent:other:fresh" }, { sessionKey: "agent:review:incognito:fresh" },
    { sessionKey: "agent:review:subagent:fresh" }, { sessionKey: "agent:review:acp:fresh" },
    { sandboxed: true }, { fsPolicy: { workspaceOnly: true } },
    { assertInvocationCurrent() { throw new Error("stale invocation"); } },
    { assertMemoryAudienceCurrent() { throw new Error("stale host guard"); } },
  ]) await assert.rejects(access.read(reference, { ...caller, ...overrides }));
  for (const [field, value] of [["store", "/another-profile/sessions.json"], ["sessionKey", "agent:other:capture"], ["sessionKey", "agent:review:incognito:capture"]]) {
    const foreign = new URL(reference); foreign.searchParams.set(field, value);
    await assert.rejects(access.read(foreign.href, caller));
  }
  await assert.rejects(access.read(reference.replace("//review/", "//other/"), caller), /outside the current/);
  await assert.rejects(access.read(reference.replace("/old-session?", "/forged-id?"), caller), /metadata/);
  const abort = new AbortController(); abort.abort(new Error("aborted before read"));
  await assert.rejects(access.read(reference, caller, abort.signal), /aborted before read/);
  assert.equal(reads, 1);
  config.gateway = { roles: { reviewer: {} } };
  await assert.rejects(access.read(reference, caller), /Role-controlled/);
  delete config.gateway;
  config.session.scope = "global";
  await assert.rejects(access.read(reference, caller), /auxiliary\/global/);
  delete config.session.scope;
  failure = "metadata-reset";
  await assert.rejects(access.read(reference, caller), /metadata/);
  entry = { sessionId: scope.sessionId }; failure = "store-reset";
  await assert.rejects(access.read(reference, caller), /outside the current/);
  config = { session: { store: scope.storePath } }; failure = "";
  await assert.rejects(access.read("/isolated profile/agents/review/sessions/old-session.jsonl", caller), /SDK-generated/);
  for (const reader of [undefined, {}, { ...sdk, resolveSessionTranscriptIdentity: undefined }]) {
    const incomplete = createTranscriptAccess(runtime, config, async () => reader, async () => allowHistoryPolicy);
    await assert.rejects(incomplete.read(reference, caller), /SDK/);
  }
  const broken = createTranscriptAccess(runtime, config, async () => { throw new Error("broken SDK dependency"); });
  await assert.rejects(broken.read(reference, caller), /broken SDK dependency/);
  await assert.rejects(access.read("openclaw-session://main/no-scope", caller), /Invalid.*reference/);
});

for (const pauseAt of ["summarize.enabled", "summarize --plugin"]) test(`interleaved agent_end hooks keep scope while awaiting ${pauseAt}`, async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-interleaved-"));
  const a = join(root, "a"), b = join(root, "b");
  const calls: { command: string; cwd: string }[] = [];
  let releaseA!: () => void, enteredA!: () => void;
  const blockedA = new Promise<void>(resolve => { releaseA = resolve; });
  const readyA = new Promise<void>(resolve => { enteredA = resolve; });
  try {
    await withEnvAsync({ HOME: root, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined, OPENCLAW_STATE_DIR: undefined, OPENCLAW_PROFILE: undefined }, async () => {
      const hooks = new Map<string, (...args: any[]) => any>();
      plugin.register({ logger: {}, pluginConfig: {}, runtime: { system: {
        async runCommandWithTimeout(argv: string[], opts: any = {}) {
          const command = argv.join(" ");
          calls.push({ command, cwd: opts.cwd });
          if (command.includes(pauseAt) && opts.cwd === a) { enteredA(); await blockedA; }
          const stdout = argv[0] === "which" ? "/test/memsearch" :
            command.includes("derive-collection") ? (argv[2] === a ? "ms_a" : "ms_b") :
            command.includes("config get") && command.includes("summarize.provider") ? "test" :
            command.includes("summarize --plugin") ? `- Summary for ${opts.cwd === a ? "A" : "B"}.` : "";
          return { stdout, stderr: "", code: 0 };
        },
      } }, registerTool() {}, registerCli() {}, on(name: string, fn: (...args: any[]) => any) { hooks.set(name, fn); } });
      const event = { success: true, messages: [
        { role: "user", content: "Remember this synthetic concurrency regression fact in its originating workspace." },
        { role: "assistant", content: "I will remember the synthetic fact in this workspace." },
      ] };
      const captureA = hooks.get("agent_end")!(event, { agentId: "a", workspaceDir: a });
      await readyA;
      await hooks.get("agent_end")!(event, { agentId: "b", workspaceDir: b });
      releaseA();
      await captureA;
      await new Promise(resolve => setImmediate(resolve));
      const day = `${new Date().toISOString().slice(0, 10)}.md`;
      assert.ok(existsSync(join(a, ".memsearch", "memory", day)), "A capture must survive B's context change");
      assert.match(readFileSync(join(a, ".memsearch", "memory", day), "utf8"), /Summary for A/);
      assert.match(readFileSync(join(b, ".memsearch", "memory", day), "utf8"), /Summary for B/);
      for (const [cwd, collection] of [[a, "ms_a"], [b, "ms_b"]]) {
        assert.ok(calls.some(call => call.cwd === cwd && call.command.includes(`index '${join(cwd, ".memsearch", "memory")}' --default-collection ${collection}`)));
        assert.ok(calls.some(call => call.cwd === cwd && call.command.includes("summarize --plugin")));
        assert.ok(calls.some(call => call.cwd === cwd && call.command.includes("summarize.provider")));
      }
    });
  } finally { releaseA?.(); rmSync(root, { recursive: true, force: true }); }
});

test("SDK output filters private blocks, limits large output and rechecks lifetime after reading", async () => {
  const scope = { agentId: "main", sessionId: "large-session", sessionKey: "agent:main:large", storePath: "/fixture/sessions.json" };
  let stale = false, invalidate = false, abortDuringRead = false;
  const controller = new AbortController();
  const ctx = { ...scope, assertInvocationCurrent() { if (stale) throw new Error("invocation expired"); } };
  const entries = Array.from({ length: 10000 }, () => ({ message: { role: "assistant", content: "old ".repeat(100) } }));
  entries.push({ message: { role: "user", content: "Last synthetic question" } });
  entries.push({ message: { role: "assistant", content: [
    { type: "thinking", thinking: "PRIVATE_THINKING" }, { type: "toolCall", arguments: "PRIVATE_TOOL_ARGS" },
    { type: "text", text: "Visible answer. ".repeat(4000) },
  ] } } as any);
  entries.push({ message: { role: "toolResult", content: "PRIVATE_TOOL_RESULT" } });
  const reader = {
    async resolveSessionTranscriptIdentity() { return scope; },
    async readVisibleSessionTranscriptMessageEntries() { if (invalidate) stale = true; if (abortDuringRead) controller.abort(new Error("aborted during read")); return entries; },
  };
  const access = createTranscriptAccess({ agent: { session: { resolveStorePath: () => scope.storePath, getSessionEntryAsync: async () => ({ sessionId: scope.sessionId }) } } }, {}, async () => reader, async () => allowHistoryPolicy);
  const ref = await access.capture(ctx);
  const output = await access.read(ref, ctx);
  assert.match(output!, /Last synthetic question/);
  assert.match(output!, /Transcript output truncated/);
  assert.ok(output!.length < 32100);
  assert.doesNotMatch(output!, /PRIVATE_|old old/);
  invalidate = true;
  await assert.rejects(access.read(ref, ctx), /invocation expired/);
  stale = false; invalidate = false; abortDuringRead = true;
  await assert.rejects(access.read(ref, ctx, controller.signal), /aborted during read/);
});

test("legacy reader rejects traversal, foreign profiles and escaping symlinks", async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-legacy-scope-"));
  try {
    const sessions = join(root, "selected", "agents", "main", "sessions");
    mkdirSync(sessions, { recursive: true });
    const foreign = join(root, "foreign.jsonl"); writeFileSync(foreign, "{}");
    symlinkSync(foreign, join(sessions, "escape.jsonl"));
    const access = createTranscriptAccess({ state: { resolveStateDir: () => join(root, "selected") } }, {}, async () => undefined);
    const ctx = { agentId: "main", sessionId: "current" };
    for (const path of [foreign, join(sessions, "escape.jsonl"), `${sessions}/../other.jsonl`, "sqlite:main:id", "relative.jsonl"]) {
      await assert.rejects(access.read(path, ctx), /outside the current/);
    }
    assert.equal(await access.read(join(sessions, "old.jsonl"), ctx), undefined);
    assert.equal(await access.capture({ ...ctx, sessionId: "missing" }), "");
    await assert.rejects(access.capture({ ...ctx, sessionId: "../escape" }), /Invalid.*identity/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("getMemsearchDir: MEMSEARCH_DIR overrides projectDir", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  const shared = mkdtempSync(join(tmpdir(), "memsearch-openclaw-shared-"));
  try {
    withEnv("MEMSEARCH_DIR", shared, () => {
      assert.equal(getMemsearchDir(dir), shared);
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
    rmSync(shared, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: defaults to projectDir", () => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.equal(getCollectionScopeDir(dir), dir);
    });
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: two projects with same MEMSEARCH_DIR share scope", () => {
  const a = mkdtempSync(join(tmpdir(), "memsearch-openclaw-a-"));
  const b = mkdtempSync(join(tmpdir(), "memsearch-openclaw-b-"));
  const shared = mkdtempSync(join(tmpdir(), "memsearch-openclaw-shared-"));
  try {
    withEnv("MEMSEARCH_DIR", shared, () => {
      assert.equal(getCollectionScopeDir(a), getCollectionScopeDir(b));
      assert.equal(getCollectionScopeDir(a), shared);
    });
  } finally {
    rmSync(a, { recursive: true, force: true });
    rmSync(b, { recursive: true, force: true });
    rmSync(shared, { recursive: true, force: true });
  }
});

test("getCollectionScopeDir: two projects without MEMSEARCH_DIR have isolated scope", () => {
  const a = mkdtempSync(join(tmpdir(), "memsearch-openclaw-a-"));
  const b = mkdtempSync(join(tmpdir(), "memsearch-openclaw-b-"));
  try {
    withEnv("MEMSEARCH_DIR", undefined, () => {
      assert.notEqual(getCollectionScopeDir(a), getCollectionScopeDir(b));
    });
  } finally {
    rmSync(a, { recursive: true, force: true });
    rmSync(b, { recursive: true, force: true });
  }
});

test("plugin tool and CLI registration contracts", async (t) => {
  const home = mkdtempSync(join(tmpdir(), "memsearch-openclaw-tool-contracts-"));
  const previousEnv = {
    HOME: process.env.HOME,
    MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
    MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
  };
  const factories = new Map<string, (ctx: unknown) => any>();
  const cliCommands: string[] = [];

  try {
    await withEnvAsync(
      { HOME: home, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: "1" },
      async () => {
        plugin.register({
          logger: {},
          pluginConfig: {},
          runtime: {
            system: {
              async runCommandWithTimeout(argv: string[]) {
                if (argv[0] === "which") {
                  return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
                }
                if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
                  return { stdout: "ms_tool_contract_test\n", stderr: "", code: 0 };
                }
                return { stdout: "", stderr: "", code: 0 };
              },
            },
          },
          registerTool(factory: (ctx: unknown) => any, metadata: { name: string }) {
            factories.set(metadata.name, factory);
          },
          registerCli(_registrar: unknown, metadata: { commands?: string[] }) {
            cliCommands.push(...(metadata.commands ?? []));
          },
          on() {},
        });

        const manifest = JSON.parse(
          readFileSync(new URL("./openclaw.plugin.json", import.meta.url), "utf-8")
        );
        const registeredNames = [...factories.keys()].sort();
        const runtimeNames = [...factories.values()]
          .map((factory) => factory({ agentId: "test", workspaceDir: home }).name)
          .sort();

        await new Promise<void>((resolve) => setImmediate(resolve));
        await t.test("manifest tool contracts exactly match runtime registrations", () => {
          const declaredNames = [...(manifest.contracts?.tools ?? [])].sort();
          assert.deepEqual(declaredNames, [
            "memory_get",
            "memory_search",
            "memory_transcript",
          ]);
          assert.deepEqual(registeredNames, declaredNames);
          assert.deepEqual(runtimeNames, declaredNames);
        });
        await t.test("CLI registration declares the legacy command metadata", () => {
          assert.deepEqual(cliCommands, ["memsearch"]);
        });
      }
    );
    assert.deepEqual(
      {
        HOME: process.env.HOME,
        MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
        MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
      },
      previousEnv
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("memory search passes the derived collection as a project-scoped default", async () => {
  const projectDir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-entry-"));
  const previousNoWatch = process.env.MEMSEARCH_NO_WATCH;
  const tools = new Map<string, (ctx: unknown) => any>();
  const calls: Array<{ argv: string[]; opts: Record<string, unknown> }> = [];
  process.env.MEMSEARCH_NO_WATCH = "1";
  try {
    plugin.register({
      logger: {},
      pluginConfig: {},
      runtime: {
        system: {
          async runCommandWithTimeout(argv: string[], opts: Record<string, unknown> = {}) {
            calls.push({ argv, opts });
            if (argv[0] === "which") return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
            if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
              return { stdout: "ms_test_project\n", stderr: "", code: 0 };
            }
            return { stdout: "[]\n", stderr: "", code: 0 };
          },
        },
      },
      registerTool(factory: (ctx: unknown) => any, metadata: { name: string }) {
        tools.set(metadata.name, factory);
      },
      registerCli() {},
      on() {},
    });

    const memorySearch = tools.get("memory_search")?.({ agentId: "test", workspaceDir: projectDir });
    assert.ok(memorySearch);
    await memorySearch.execute("call-1", { query: "release decision" });

    const search = calls.find(({ argv }) => argv[0] === "bash" && argv[2]?.includes(" search "));
    assert.ok(search);
    assert.match(search.argv[2], /--default-collection ms_test_project/);
    assert.doesNotMatch(search.argv[2], / --collection /);
    assert.equal(search.opts.cwd, projectDir);
  } finally {
    if (previousNoWatch === undefined) delete process.env.MEMSEARCH_NO_WATCH;
    else process.env.MEMSEARCH_NO_WATCH = previousNoWatch;
    rmSync(projectDir, { recursive: true, force: true });
  }
});

test("tool, CLI search, and status expose nonzero memsearch exits", async () => {
  const projectDir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-errors-"));
  const previousHome = process.env.HOME;
  const previousNoWatch = process.env.MEMSEARCH_NO_WATCH;
  const tools = new Map<string, (ctx: unknown) => any>();
  const actions = new Map<string, (...args: any[]) => Promise<void>>();
  const output: string[] = [];
  const originalLog = console.log;
  process.env.HOME = projectDir;
  process.env.MEMSEARCH_NO_WATCH = "1";

  function command(name: string): any {
    return {
      command,
      description() { return this; },
      option() { return this; },
      action(fn: (...args: any[]) => Promise<void>) {
        actions.set(name, fn);
        return this;
      },
    };
  }

  try {
    console.log = (...args: unknown[]) => output.push(args.join(" "));
    plugin.register({
      logger: {},
      pluginConfig: {},
      runtime: {
        system: {
          async runCommandWithTimeout(argv: string[]) {
            const rendered = argv.join(" ");
            if (argv[0] === "which") return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
            if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
              return { stdout: "ms_error_test\n", stderr: "", code: 0 };
            }
            if (rendered.includes("config get")) return { stdout: "", stderr: "", code: 0 };
            if (rendered.includes(" search ")) {
              return { stdout: "", stderr: "Collection missing\n", code: 1 };
            }
            if (rendered.includes(" stats ")) {
              return { stdout: "", stderr: "Permission denied\n", code: 1 };
            }
            return { stdout: "", stderr: "", code: 0 };
          },
        },
      },
      registerTool(factory: (ctx: unknown) => any, metadata: { name: string }) {
        tools.set(metadata.name, factory);
      },
      registerCli(callback: (ctx: any) => void) {
        callback({ program: { command } });
      },
      on() {},
    });

    const memorySearch = tools.get("memory_search")?.({ agentId: "test", workspaceDir: projectDir });
    const toolResult = await memorySearch.execute("call-1", { query: "release" });
    assert.match(toolResult.content[0].text, /Search failed \(exit 1\): Collection missing/);

    const cliSearch = actions.get("search <query>");
    assert.ok(cliSearch);
    await assert.rejects(() => cliSearch("release", {}), /Search failed \(exit 1\): Collection missing/);

    const status = actions.get("status");
    assert.ok(status);
    await status();
    assert.ok(output.includes("Stats failed (exit 1): Permission denied"));
  } finally {
    console.log = originalLog;
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    if (previousNoWatch === undefined) delete process.env.MEMSEARCH_NO_WATCH;
    else process.env.MEMSEARCH_NO_WATCH = previousNoWatch;
    rmSync(projectDir, { recursive: true, force: true });
  }
});

test("status reports the resolved collection instead of the derived fallback", async () => {
  const projectDir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-status-"));
  const previousHome = process.env.HOME;
  const previousNoWatch = process.env.MEMSEARCH_NO_WATCH;
  const actions = new Map<string, (...args: any[]) => Promise<void>>();
  const calls: string[] = [];
  const output: string[] = [];
  const originalLog = console.log;
  process.env.HOME = projectDir;
  process.env.MEMSEARCH_NO_WATCH = "1";

  function command(name: string): any {
    return {
      command,
      description() { return this; },
      option() { return this; },
      action(fn: (...args: any[]) => Promise<void>) {
        actions.set(name, fn);
        return this;
      },
    };
  }

  try {
    console.log = (...args: unknown[]) => output.push(args.join(" "));
    plugin.register({
      logger: {},
      pluginConfig: {},
      runtime: {
        system: {
          async runCommandWithTimeout(argv: string[]) {
            const rendered = argv.join(" ");
            calls.push(rendered);
            if (argv[0] === "which") return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
            if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
              return { stdout: "ms_derived_project\n", stderr: "", code: 0 };
            }
            if (rendered.includes("config get milvus.collection")) {
              return { stdout: "project_collection\n", stderr: "", code: 0 };
            }
            return { stdout: "", stderr: "", code: 0 };
          },
        },
      },
      registerTool() {},
      registerCli(callback: (ctx: any) => void) {
        callback({ program: { command } });
      },
      on() {},
    });

    const status = actions.get("status");
    assert.ok(status);
    await status();

    assert.ok(calls.some((call) => call.includes(
      "config get milvus.collection --default-collection 'ms_derived_project'"
    )));
    assert.ok(output.includes("Collection:  project_collection"));
  } finally {
    console.log = originalLog;
    if (previousHome === undefined) delete process.env.HOME;
    else process.env.HOME = previousHome;
    if (previousNoWatch === undefined) delete process.env.MEMSEARCH_NO_WATCH;
    else process.env.MEMSEARCH_NO_WATCH = previousNoWatch;
    rmSync(projectDir, { recursive: true, force: true });
  }
});

test("an old core fails clearly before a memory search is attempted", async () => {
  const projectDir = mkdtempSync(join(tmpdir(), "memsearch-openclaw-old-core-"));
  const previousNoWatch = process.env.MEMSEARCH_NO_WATCH;
  const tools = new Map<string, (ctx: unknown) => any>();
  const calls: string[] = [];
  process.env.MEMSEARCH_NO_WATCH = "1";
  try {
    plugin.register({
      logger: {},
      pluginConfig: {},
      runtime: {
        system: {
          async runCommandWithTimeout(argv: string[]) {
            const rendered = argv.join(" ");
            calls.push(rendered);
            if (argv[0] === "which") return { stdout: "/tmp/memsearch\n", stderr: "", code: 0 };
            if (argv[0] === "bash" && argv[1]?.endsWith("derive-collection.sh")) {
              return { stdout: "ms_old_core_test\n", stderr: "", code: 0 };
            }
            if (rendered.includes("--default-collection")) {
              return {
                stdout: "",
                stderr: "Error: No such option: --default-collection\n",
                code: 2,
              };
            }
            return { stdout: "", stderr: "", code: 0 };
          },
        },
      },
      registerTool(factory: (ctx: unknown) => any, metadata: { name: string }) {
        tools.set(metadata.name, factory);
      },
      registerCli() {},
      on() {},
    });

    const memorySearch = tools.get("memory_search")?.({ agentId: "old", workspaceDir: projectDir });
    const result = await memorySearch.execute("call-1", { query: "release decision" });
    assert.match(result.content[0].text, /--default-collection support is required/);
    assert.ok(!calls.some((call) => call.includes(" search ")));
  } finally {
    if (previousNoWatch === undefined) delete process.env.MEMSEARCH_NO_WATCH;
    else process.env.MEMSEARCH_NO_WATCH = previousNoWatch;
    rmSync(projectDir, { recursive: true, force: true });
  }
});

test("default registration uses the supported prompt hook and injects memory context", async () => {
  const home = mkdtempSync(join(tmpdir(), "memsearch-openclaw-hooks-"));
  const previousEnv = {
    HOME: process.env.HOME,
    MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
    MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
  };
  const memoryDir = join(home, ".openclaw", "workspace", ".memsearch", "memory");
  mkdirSync(memoryDir, { recursive: true });
  writeFileSync(
    join(memoryDir, "2026-09-12.md"),
    "# 2026-09-12\n\n## Session 14:00\n\n### 14:01\n- Compatibility memory fixture.\n",
    "utf-8"
  );

  try {
    await withEnvAsync(
      { HOME: home, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined },
      async () => {
        const hooks = registerPluginHooks();
        const retiredHook = "before_" + "agent_start";
        assert.deepEqual(
          [...hooks.keys()].sort(),
          ["agent_end", "before_prompt_build", "session_start"]
        );
        assert.equal(hooks.has(retiredHook), false);

        const result = await hooks.get("before_prompt_build")?.();
        assert.match(result.prependContext, /Recent memories/);
        assert.match(result.prependContext, /Compatibility memory fixture/);
        await new Promise<void>((resolve) => setImmediate(resolve));
      }
    );
    assert.deepEqual(
      {
        HOME: process.env.HOME,
        MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
        MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
      },
      previousEnv
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("autoRecall false omits the prompt hook", async () => {
  const home = mkdtempSync(join(tmpdir(), "memsearch-openclaw-no-recall-"));
  const previousEnv = {
    HOME: process.env.HOME,
    MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
    MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
  };
  try {
    await withEnvAsync(
      { HOME: home, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined },
      async () => {
        const hooks = registerPluginHooks({ autoRecall: false });
        const retiredHook = "before_" + "agent_start";
        assert.equal(hooks.has("before_prompt_build"), false);
        assert.equal(hooks.has(retiredHook), false);
        await new Promise<void>((resolve) => setImmediate(resolve));
      }
    );
    assert.deepEqual(
      {
        HOME: process.env.HOME,
        MEMSEARCH_DIR: process.env.MEMSEARCH_DIR,
        MEMSEARCH_NO_WATCH: process.env.MEMSEARCH_NO_WATCH,
      },
      previousEnv
    );
  } finally {
    rmSync(home, { recursive: true, force: true });
  }
});

test("source and generated entrypoints contain only the supported prompt hook literal", () => {
  const source = readFileSync(new URL("./index.ts", import.meta.url), "utf-8");
  const generated = readFileSync(new URL("./index.js", import.meta.url), "utf-8");
  const retiredHook = "before_" + "agent_start";
  const supportedHook = "before_prompt_build";
  const literalCount = (text: string, hook: string) =>
    [...text.matchAll(new RegExp(`api\\.on\\([\\s\\n]*[\"']${hook}[\"']`, "g"))].length;

  assert.equal(literalCount(source, retiredHook), 0);
  assert.equal(literalCount(source, supportedHook), 1);
  assert.equal(literalCount(generated, retiredHook), 0);
  assert.equal(literalCount(generated, supportedHook), 1);
});


test("native summary passes literal message/model and uses independent UUID sessions", async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-native-literal-"));
  const sentinel = join(root, "substitution-executed");
  const argsFile = join(root, "args.json");
  const commandText = `$(touch ${sentinel}) \`touch ${sentinel}\` 'quoted' "double" $HOME`;
  const model = `fixture/${commandText}`;
  const userText = `Preserve this synthetic literal transcript without executing its content: ${commandText}`;
  const assistantText = "This is a synthetic shell quoting regression.";
  const bin = join(root, "bin"); mkdirSync(bin);
  writeFileSync(join(bin, "openclaw"), `#!${process.execPath}\nrequire('node:fs').writeFileSync(${JSON.stringify(argsFile)}, JSON.stringify(process.argv.slice(2)));\nconsole.log('- Literal shell fixture summary.');\n`);
  chmodSync(join(bin, "openclaw"), 0o700);
  try {
    await withEnvAsync({ HOME: root, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined }, async () => {
      const hooks = new Map<string, (...args: any[]) => any>();
      plugin.register({ logger: {}, pluginConfig: {}, runtime: { system: {
        async runCommandWithTimeout(argv: string[], opts: any = {}) {
          const command = argv.join(" ");
          if (argv[0] === "bash" && argv[1] === "-c" && argv[2].startsWith("openclaw agent ")) {
            execFileSync(argv[0], argv.slice(1), { cwd: opts.cwd, env: { ...opts.env, PATH: `${bin}:/usr/bin:/bin` } });
            return { stdout: "", stderr: "", code: 0 };
          }
          const stdout = argv[0] === "which" ? "/fixture/memsearch" :
            command.includes("derive-collection") ? "ms_literal" :
            command.includes("config get") && command.includes("summarize.model") ? model : "";
          return { stdout, stderr: "", code: 0 };
        },
      } }, registerTool() {}, registerCli() {}, on(name: string, fn: (...args: any[]) => any) { hooks.set(name, fn); } });
      const sessionIds = new Set<string>();
      for (let turn = 0; turn < 2; turn++) {
        await hooks.get("agent_end")!({ success: true, messages: [
          { role: "user", content: userText }, { role: "assistant", content: assistantText },
        ] }, { agentId: "literal", workspaceDir: root });
        const argv = JSON.parse(readFileSync(argsFile, "utf8"));
        assert.equal(existsSync(sentinel), false, "transcript/model command substitution must not execute");
        assert.equal(argv[argv.indexOf("--model") + 1], model);
        assert.ok(argv[argv.indexOf("-m") + 1].endsWith(`Transcript:\n[User]: ${userText}\n\n[Assistant]: ${assistantText}`));
        const session = argv[argv.indexOf("--session-id") + 1];
        assert.match(session, /^[a-f0-9-]{36}$/);
        sessionIds.add(session);
      }
      assert.equal(sessionIds.size, 2);
      await new Promise(resolve => setImmediate(resolve));
    });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("capture freezes identity and configured store before SDK loading yields", async () => {
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  let config = { session: { store: "/profile-a/sessions.json" } };
  const ctx = { agentId: "main", sessionId: "capture-a", sessionKey: "agent:main:a", getRuntimeConfig: () => config };
  const expected = { agentId: "main", sessionId: "capture-a", sessionKey: "agent:main:a", storePath: config.session.store };
  const access = createTranscriptAccess({ agent: { session: { resolveStorePath: (store: string) => store } } }, {}, async () => {
    await pending;
    return { async resolveSessionTranscriptIdentity(scope: any) { assert.deepEqual(scope, expected); return scope; } };
  });
  const capture = access.capture(ctx);
  config = { session: { store: "/profile-b/sessions.json" } };
  ctx.sessionId = "capture-b"; ctx.sessionKey = "agent:main:b";
  release();
  const reference = new URL(await capture);
  assert.equal(reference.pathname, "/capture-a");
  assert.equal(reference.searchParams.get("sessionKey"), expected.sessionKey);
  assert.equal(reference.searchParams.has("key"), false);
  assert.equal(reference.searchParams.get("store"), expected.storePath);
});

test("session_start keeps A memory, config cwd and collection when B starts during derivation", async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-start-scope-"));
  const a = join(root, "a"), b = join(root, "b");
  const calls: { command: string; cwd: string }[] = [];
  let release!: () => void, entered!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  const ready = new Promise<void>(resolve => { entered = resolve; });
  for (const cwd of [a, b]) mkdirSync(join(cwd, ".memsearch/memory"), { recursive: true });
  try {
    await withEnvAsync({ HOME: root, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: "1" }, async () => {
      const hooks = new Map<string, (...args: any[]) => any>();
      plugin.register({ logger: {}, pluginConfig: {}, runtime: { system: {
        async runCommandWithTimeout(argv: string[], opts: any = {}) {
          const command = argv.join(" "); calls.push({ command, cwd: opts.cwd });
          if (argv[1]?.endsWith("derive-collection.sh") && argv[2] === a) { entered(); await pending; }
          const stdout = argv[0] === "which" ? "/fixture/memsearch" :
            command.includes("derive-collection") ? (argv[2] === a ? "ms_a" : "ms_b") : "";
          return { stdout, stderr: "", code: 0 };
        },
      } }, registerTool() {}, registerCli() {}, on(name: string, fn: (...args: any[]) => any) { hooks.set(name, fn); } });
      const startedA = hooks.get("session_start")!({}, { agentId: "a", workspaceDir: a });
      await ready;
      await hooks.get("session_start")!({}, { agentId: "b", workspaceDir: b });
      release(); await startedA;
      for (const [cwd, collection] of [[a, "ms_a"], [b, "ms_b"]]) {
        assert.ok(calls.some(call => call.cwd === cwd && call.command.includes(`index '${join(cwd, ".memsearch/memory")}' --default-collection ${collection}`)), JSON.stringify(calls.filter(call => call.command.includes(" index "))));
        assert.ok(calls.some(call => call.cwd === cwd && call.command.includes("config set embedding.provider onnx")), `config must use ${cwd}`);
      }
      await new Promise(resolve => setImmediate(resolve));
    });
  } finally { release?.(); rmSync(root, { recursive: true, force: true }); }
});

for (const toolName of ["memory_search", "memory_get"]) test(`${toolName} factory retains A cwd across a B factory and async execution`, async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-tool-scope-"));
  const a = join(root, "a"), b = join(root, "b");
  const calls: { command: string; cwd: string }[] = [];
  try {
    await withEnvAsync({ HOME: root, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: "1" }, async () => {
      const tools = new Map<string, (ctx: any) => any>();
      plugin.register({ logger: {}, pluginConfig: {}, runtime: { system: {
        async runCommandWithTimeout(argv: string[], opts: any = {}) {
          const command = argv.join(" "); calls.push({ command, cwd: opts.cwd });
          const stdout = argv[0] === "which" ? "/fixture/memsearch" :
            command.includes("derive-collection") ? (argv[2] === a ? "ms_a" : "ms_b") : "";
          return { stdout, stderr: "", code: 0 };
        },
      } }, registerTool(factory: (ctx: any) => any, meta: { name: string }) { tools.set(meta.name, factory); }, registerCli() {}, on() {} });
      const toolA = tools.get(toolName)!({ agentId: "a", workspaceDir: a });
      tools.get(toolName)!({ agentId: "b", workspaceDir: b });
      const pendingA = toolA.execute("a", { query: "synthetic", chunk_hash: "synthetic" });
      tools.get(toolName)!({ agentId: "b", workspaceDir: b });
      await pendingA;
      const operation = toolName === "memory_search" ? " search " : " expand ";
      const call = calls.find(call => call.command.includes(operation));
      assert.ok(call); assert.equal(call.cwd, a); assert.match(call.command, /--default-collection ms_a/);
      await new Promise(resolve => setImmediate(resolve));
    });
  } finally { rmSync(root, { recursive: true, force: true }); }
});

test("before_prompt_build keeps A skill hint cwd when a B factory runs during await", async () => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-hint-scope-"));
  const a = join(root, "a"), b = join(root, "b");
  const calls: { command: string; cwd: string }[] = [];
  try {
    await withEnvAsync({ HOME: root, MEMSEARCH_DIR: undefined, MEMSEARCH_NO_WATCH: undefined }, async () => {
      const hooks = new Map<string, (...args: any[]) => any>();
      const tools = new Map<string, (ctx: any) => any>();
      plugin.register({ logger: {}, pluginConfig: {}, runtime: { system: {
        async runCommandWithTimeout(argv: string[], opts: any = {}) {
          const command = argv.join(" "); calls.push({ command, cwd: opts.cwd });
          const stdout = argv[0] === "which" ? "/fixture/memsearch" :
            command.includes("derive-collection") ? "ms_hint" : command.includes("skills status --hint") ? `Hint for ${opts.cwd}` : "";
          return { stdout, stderr: "", code: 0 };
        },
      } }, registerTool(factory: (ctx: any) => any, meta: { name: string }) { tools.set(meta.name, factory); },
        registerCli() {}, on(name: string, fn: (...args: any[]) => any) { hooks.set(name, fn); } });
      const pendingA = hooks.get("before_prompt_build")!({}, { agentId: "a", workspaceDir: a });
      tools.get("memory_search")!({ agentId: "b", workspaceDir: b });
      const result = await pendingA;
      assert.equal(result.prependContext, `Hint for ${a}`);
      const call = calls.find(call => call.command.includes("skills status --hint"));
      assert.ok(call); assert.equal(call.cwd, a);
      assert.ok(call.command.includes(`MEMSEARCH_DIR='${join(a, ".memsearch")}'`));
      await new Promise(resolve => setImmediate(resolve));
    });
  } finally { rmSync(root, { recursive: true, force: true }); }
});
