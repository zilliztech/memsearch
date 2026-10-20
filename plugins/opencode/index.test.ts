import test from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import type { Plugin } from "@opencode/plugin";
import { Schema } from "effect";
import { getRecentMemories, mergeSystemMemoryContext, MEMSEARCH_SYSTEM_MARKER } from "./context.ts";
import { loadSkills, registerSkills } from "./skills.ts";
import { registerTools, searchInput, transcriptInput } from "./tools.ts";
import { databasePath, hostScope, sessionScope } from "./scope.ts";
import { run } from "./runtime.ts";

const pluginDir = dirname(fileURLToPath(import.meta.url));

test("entry exports one V2 plugin object and rejects incompatible hosts", async () => {
  const mod = await import("./index.ts");
  assert.deepEqual(Object.keys(mod), ["default"]);
  assert.equal(mod.default.id, "memsearch");
  assert.equal(typeof mod.default.setup, "function");
  for (const version of ["1.19.3", "2.0.31", "3.0.0"]) {
    await assert.rejects(() => Promise.resolve(mod.default.setup({ app: { version } } as Plugin.Context)), /0.3.17/);
  }
});

test("SystemPart merging preserves metadata and later parts without mutating host input", () => {
  const first = { type: "text" as const, text: "Base instructions", metadata: { source: "host" } };
  const last = { type: "text" as const, text: "Another part" };
  const initial = [first, last];
  const merged = mergeSystemMemoryContext(initial, MEMSEARCH_SYSTEM_MARKER + " old");
  const replaced = mergeSystemMemoryContext(merged, MEMSEARCH_SYSTEM_MARKER + " new");
  assert.equal(replaced.length, 2);
  assert.deepEqual(replaced[0].metadata, first.metadata);
  assert.equal(replaced[1], last);
  assert.match(replaced[0].text, /Base instructions/);
  assert.doesNotMatch(replaced[0].text, /old/);
  assert.equal(replaced[0].text.split(MEMSEARCH_SYSTEM_MARKER).length, 2);
  assert.equal(first.text, "Base instructions");
  assert.deepEqual(mergeSystemMemoryContext(undefined, "context"), [{ type: "text", text: "context" }]);
});

test("journal preview excludes scratch files and empty headings", t => {
  const dir = mkdtempSync(join(tmpdir(), "memsearch-v2-context-"));
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  writeFileSync(join(dir, "2026-10-20.md"), "# Day\n## Session 09:00\n- Durable fact\n## Session 10:00\n");
  writeFileSync(join(dir, "zzz-scratch.md"), "## Scratch\n- PRIVATE SCRATCH");
  const text = getRecentMemories(dir);
  assert.match(text, /Durable fact/);
  assert.doesNotMatch(text, /SCRATCH|10:00/);
});

test("three packaged Skills have real reference paths and replace duplicate discovery", async () => {
  const skills = loadSkills(pluginDir);
  assert.deepEqual(skills.map(s => s.name), ["memory-recall", "memory-config", "memory-to-skill"]);
  for (const skill of skills) assert.ok(readFileSync(skill.path, "utf8").includes(skill.content));
  assert.doesNotMatch(skills[0].content, /__INSTALL_DIR__|\$ARGUMENTS|!`/);
  const registered: any[] = [{ id: "old", name: "memory-recall" }, { id: "other", name: "unrelated" }];
  const ctx = { skill: { transform: async (fn: any) => fn({
    list: () => registered, remove: (id: string) => registered.splice(registered.findIndex(s => s.id === id), 1), add: (s: unknown) => registered.push(s),
  }) } } as unknown as Plugin.Context;
  await registerSkills(ctx, pluginDir);
  assert.equal(registered.length, 4);
  assert.equal(registered.filter(s => s.name === "memory-recall").length, 1);
  assert.ok(registered.find(s => s.id === "other"));
});

test("tool schemas reject unbounded input", () => {
  const search = Schema.decodeUnknownSync(searchInput);
  const transcript = Schema.decodeUnknownSync(transcriptInput);
  assert.equal(search({ query: "fact", top_k: 5 }).top_k, 5);
  for (const top_k of [0, 21, 1.5]) assert.throws(() => search({ query: "fact", top_k }));
  assert.throws(() => search({ query: "" }));
  assert.throws(() => search({ query: "x".repeat(4001) }));
  assert.throws(() => transcript({ session_id: "s", context: 11 }));
  assert.throws(() => transcript({ session_id: "s", limit: 51 }));
});

test("tools recover before recall, use literal argv/default collection and validate requesting ownership", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-tools-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const project = join(root, "project's space"); mkdirSync(project);
  const database = join(root, "source # ?.db");
  const db = new DatabaseSync(database);
  db.exec("CREATE TABLE session_v2(id TEXT, project_id TEXT, directory TEXT, workspace_id TEXT, parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT); CREATE TABLE session_message(id TEXT, session_id TEXT, type TEXT, seq INTEGER, data TEXT)");
  db.prepare("INSERT INTO session_v2 VALUES(?,?,?,?,NULL,NULL,NULL)").run("session", "p", project, "ws"); db.close();
  const cli = join(root, "memsearch");
  const log = join(project, "argv.json");
  const repo = join(pluginDir, "../..");
  const source = join(project, "short.md");
  writeFileSync(source, "## Fixture\n<!-- session:session turn:short db:fixture.db -->\n- A short memory.\n");
  writeFileSync(cli, `#!${join(repo, ".venv/bin/python")}
import json,os,sys
sys.path.insert(0, ${JSON.stringify(join(repo, "src"))})
from memsearch import cli as core, core as backend, store
from memsearch.config import MemSearchConfig
assert os.path.exists("recovered")
open("argv.json","w").write(json.dumps(sys.argv[1:]))
chunk = {"chunk_hash": "short-hash", "content": "- A short memory.", "source": ${JSON.stringify(source)}, "heading": "Fixture", "heading_level": 2, "start_line": 3, "end_line": 3}
class Search:
    def __init__(self, **kwargs): pass
    async def search(self, *args, **kwargs): return [chunk]
    def close(self): pass
class Store:
    def __init__(self, **kwargs): pass
    def query(self, filter_expr):
        assert filter_expr == 'chunk_hash == "short-hash"'
        return [chunk]
    def close(self): pass
core._safe_resolve_config = lambda *args, **kwargs: MemSearchConfig()
backend.MemSearch = Search
store.MilvusStore = Store
core.cli()
`); chmodSync(cli, 0o755);
  const tools: any[] = [];
  let sessionRoot = project;
  const ctx = { tool: { transform: async (fn: any) => fn({ add: (tool: unknown) => tools.push(tool) }) },
    session: { get: async ({ sessionID }: { sessionID: string }) => { assert.equal(sessionID, "session"); return { projectID: "global", location: { directory: sessionRoot } }; } },
  } as unknown as Plugin.Context;
  let recovery = 0;
  await registerTools(ctx, { root: project, projectID: "p", workspaceID: "ws" }, "fallback_collection", [cli], { recover: async () => { recovery++; writeFileSync(join(project, "recovered"), "yes"); return ""; } }, pluginDir, database);
  assert.deepEqual(tools.map(t => t.name), ["memory_search", "memory_get", "memory_transcript"]);
  const context = { sessionID: "session", signal: new AbortController().signal };
  const query = 'literal $(touch SHOULD_NOT_EXIST) " quotes';
  const searched = await tools[0].execute({ query }, context);
  assert.equal(searched.content, searched.output);
  const resultChunks = JSON.parse(Schema.decodeUnknownSync(tools[0].output)(searched.output) as string);
  assert.equal(resultChunks[0].content, "- A short memory.");
  assert.equal(resultChunks[0].chunk_hash, "short-hash");
  const argv = JSON.parse(readFileSync(log, "utf8"));
  assert.deepEqual(argv.slice(0, 7), ["search", query, "--top-k", "5", "--json-output", "--default-collection", "fallback_collection"]);
  const expanded = await tools[1].execute({ chunk_hash: resultChunks[0].chunk_hash }, context);
  assert.equal(Schema.decodeUnknownSync(tools[1].output)(expanded.output), expanded.content);
  assert.match(expanded.content, /A short memory/);
  assert.match(expanded.content, /session:session turn:short db:fixture.db/);
  assert.deepEqual(JSON.parse(readFileSync(log, "utf8")), ["expand", "short-hash", "--default-collection", "fallback_collection"]);
  assert.equal(recovery, 2);
  const result = await tools[2].execute({ session_id: "missing", db_path: database }, context);
  assert.match(result.content, /user-owned OpenCode migration/);
  sessionRoot = root;
  await assert.rejects(() => tools[0].execute({ query: "fact" }, context), /outside/);
  assert.equal(recovery, 2);
  sessionRoot = project;
  const changed = new DatabaseSync(database); changed.exec("UPDATE session_v2 SET workspace_id='other'"); changed.close();
  await assert.rejects(() => tools[0].execute({ query: "fact" }, context));
  assert.equal(recovery, 2);
});

test("command failure does not leak provider stderr into context", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-error-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  await assert.rejects(() => run(["python3", "-c", 'import sys; sys.stderr.write("PRIVATE_PROVIDER_DATA"); sys.exit(1)'], ["search"], root), error => {
    assert.match(String(error), /search failed/); assert.doesNotMatch(String(error), /PRIVATE/); return true;
  });
});

test("database path follows pinned host channel and explicit override rules", () => {
  assert.equal(databasePath("latest", { XDG_DATA_HOME: "/tmp/data" }), "/tmp/data/opencode/opencode.db");
  assert.equal(databasePath("feature/a", { XDG_DATA_HOME: "/tmp/data" }), "/tmp/data/opencode/opencode-feature-a.db");
  assert.equal(databasePath("feature", { XDG_DATA_HOME: "/tmp/data", OPENCODE_DB: "custom.db" }), "/tmp/data/opencode/custom.db");
  assert.equal(databasePath("latest", { OPENCODE_DB: "/tmp/absolute.db" }), "/tmp/absolute.db");
});

test("nongit root uses exact load directory without a shared global root", t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-root-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const scope = hostScope({ location: { directory: root, project: { id: "p", directory: "/", canonical: "/" } } } as any);
  assert.equal(scope.root, root);
  assert.equal(hostScope({ location: { directory: root, project: { id: "p", directory: tmpdir(), canonical: "/" } } } as any).root, root);
});

test("actual migrated requester identity can access the same directory but not another workspace", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-identity-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const fixture = JSON.parse(readFileSync(join(pluginDir, "../../tests/fixtures/opencode-v2-migrated.json"), "utf8"));
  const path = join(root, "host.db");
  const db = new DatabaseSync(path);
  db.exec("CREATE TABLE session_v2(id TEXT, project_id TEXT, directory TEXT, workspace_id TEXT, parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT); CREATE TABLE session_message(id TEXT, session_id TEXT, type TEXT, seq INTEGER, data TEXT)");
  db.prepare("INSERT INTO session_v2 VALUES(?,?,?,NULL,NULL,NULL,NULL)").run(fixture.session_id, fixture.stored_project_id, root);
  const ctx = { session: { get: async () => ({ projectID: fixture.stored_project_id, location: { directory: root } }) } } as any;
  const scope = { root, projectID: fixture.requester_project_id };
  assert.deepEqual(await sessionScope(ctx, scope, fixture.session_id, path, pluginDir), scope);
  db.exec("UPDATE session_v2 SET workspace_id='different'");
  await assert.rejects(() => sessionScope(ctx, scope, fixture.session_id, path, pluginDir));
  db.close();
});

test("V2 setup, completion event, finite capture, cleanup and fresh context work together without a provider", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-lifecycle-"));
  const project = join(root, "project"); const bin = join(root, "bin");
  mkdirSync(project); mkdirSync(bin);
  const database = join(root, "host.db");
  const db = new DatabaseSync(database);
  db.exec("CREATE TABLE session_v2(id TEXT, project_id TEXT, directory TEXT, workspace_id TEXT, parent_id TEXT, fork_session_id TEXT, fork_boundary TEXT); CREATE TABLE session_message(id TEXT, session_id TEXT, type TEXT, seq INTEGER, data TEXT)");
  db.prepare("INSERT INTO session_v2 VALUES(?,?,?,NULL,NULL,NULL,NULL)").run("session", "p", project);
  db.close();
  writeFileSync(join(bin, "memsearch"), '#!/usr/bin/env python3\nimport sys\nif sys.argv[1] == "skills": print("candidate hint")\nelse: print("fixture CLI output")\n');
  chmodSync(join(bin, "memsearch"), 0o755);
  const keys = ["HOME", "PATH", "XDG_DATA_HOME", "OPENCODE_DB", "MEMSEARCH_NO_WATCH", "MEMSEARCH_DIR"] as const;
  const previous = Object.fromEntries(keys.map(key => [key, process.env[key]]));
  const repo = join(pluginDir, "../..");
  Object.assign(process.env, { HOME: root, PATH: `${bin}:${join(repo, ".venv/bin")}:${process.env.PATH}`, XDG_DATA_HOME: root, OPENCODE_DB: database });
  delete process.env.MEMSEARCH_NO_WATCH; delete process.env.MEMSEARCH_DIR;
  t.after(() => {
    for (const key of keys) { if (previous[key] === undefined) delete process.env[key]; else process.env[key] = previous[key]; }
    rmSync(root, { recursive: true, force: true });
  });
  const hooks = new Map<string, (input: any) => Promise<void>>();
  const toolList: any[] = []; const skillList: any[] = [];
  let emit!: (event: any) => void;
  let nativeCalls = 0;
  let queuedEvent: any;
  let disposed = 0;
  const registration = { dispose: async () => { disposed++; } };
  const ctx = {
    app: { version: "2.0.32", channel: "latest" },
    location: { directory: project, project: { id: "p", directory: project, canonical: project } },
    session: {
      get: async () => ({ projectID: "p", location: { directory: project } }),
      hook: async (name: string, cb: any) => { hooks.set(name, cb); return registration; },
    },
    event: { subscribe: async function* ({ signal }: { signal: AbortSignal }) {
      if (queuedEvent) { const event = queuedEvent; queuedEvent = undefined; yield event; }
      while (!signal.aborted) {
        const event = await new Promise<any>(resolve => {
          const onAbort = () => resolve(undefined);
          signal.addEventListener("abort", onAbort, { once: true });
          emit = value => { signal.removeEventListener("abort", onAbort); resolve(value); };
        });
        if (event) yield event;
      }
    } },
    tool: { transform: async (cb: any) => { cb({ add: (value: any) => toolList.push(value) }); return registration; } },
    skill: { transform: async (cb: any) => { cb({ list: () => [], add: (value: any) => skillList.push(value) }); return registration; } },
    agent: { get: async () => ({ data: { model: { providerID: "openai", id: "gpt-4o-mini" } } }) },
    generate: { text: async ({ prompt }: { prompt: string }) => {
      nativeCalls++;
      assert.equal(hooks.size, 2, "native inference must wait until setup registrations are ready");
      assert.match(prompt, /fixture user/);
      return { text: "- Lifecycle fixture captured." };
    } },
  } as unknown as Plugin.Context;
  const plugin = (await import("./index.ts")).default;
  const cleanup = await plugin.setup(ctx);
  assert.equal(typeof cleanup, "function");
  try {
    assert.equal(toolList.length, 3); assert.equal(skillList.length, 3);
    const writer = new DatabaseSync(database);
    const insert = writer.prepare("INSERT INTO session_message VALUES(?,'session',?,?,?)");
    insert.run("u", "user", 2, JSON.stringify({ text: "fixture user" }));
    insert.run("a", "assistant", 9, JSON.stringify({ content: [{ type: "text", text: "fixture answer" }], finish: "stop", time: { created: 1, streamed: 9, completed: 10 } }));
    insert.run("i", "idle", 15, JSON.stringify({ outcome: "succeeded" })); writer.close();
    emit({ type: "session.execution.succeeded", data: { sessionID: "session" } });
    // This barrier also covers an event that reaches the plugin before its DB write.
    await hooks.get("prompt")!({ sessionID: "session" });
    const input = { sessionID: "session", system: [{ type: "text", text: "host base" }] };
    await hooks.get("context")!(input);
    assert.match(input.system[0].text, /Lifecycle fixture captured/);
    assert.match(input.system[0].text, /candidate hint/);
    assert.equal(nativeCalls, 1);
  } finally { await cleanup?.(); }
  assert.equal(disposed, 4);
  // Durable work plus an execution event already queued when setup begins.
  // The host cannot serve generation until its awaited setup has registered.
  const writer = new DatabaseSync(database);
  const insert = writer.prepare("INSERT INTO session_message VALUES(?,'session',?,?,?)");
  insert.run("u2", "user", 22, JSON.stringify({ text: "fixture user after shutdown" }));
  insert.run("a2", "assistant", 29, JSON.stringify({ content: [{ type: "text", text: "fixture answer" }], finish: "stop", time: { created: 20, streamed: 29, completed: 30 } }));
  insert.run("i2", "idle", 35, JSON.stringify({ outcome: "succeeded" })); writer.close();
  hooks.clear();
  queuedEvent = { type: "session.execution.succeeded", data: { sessionID: "session" } };
  const nextCleanup = await plugin.setup(ctx);
  try {
    const input = { sessionID: "session", system: [] };
    await hooks.get("context")!(input);
    assert.match(JSON.stringify(input.system), /Lifecycle fixture captured/);
    assert.equal(nativeCalls, 2);
    const journal = getRecentMemories(join(project, ".memsearch/memory"));
    assert.doesNotMatch(journal, /summary unavailable/);
    assert.equal(journal.split("Lifecycle fixture captured.").length - 1, 2);
  } finally { await nextCleanup?.(); }
});
