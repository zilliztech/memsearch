import test from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { getMemsearchDir, getCollectionScopeDir } from "./index.ts";
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
