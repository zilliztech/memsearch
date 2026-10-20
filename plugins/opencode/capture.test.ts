import test from "node:test";
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import type { Plugin } from "@opencode/plugin";
import { CaptureCoordinator, nativeText, helperRunner } from "./capture.ts";

const tick = () => new Promise<void>(resolve => setImmediate(resolve));

test("setup baselines without inference and shutdown does not start recovery", async () => {
  const calls: { initialize: boolean; maintenance: boolean }[] = [];
  let servicesReady = false;
  const coordinator = new CaptureCoordinator(async batch => {
    assert.ok(batch.initialize || servicesReady, "inference must wait for host services");
    calls.push(batch);
  });
  await coordinator.initialize();
  await tick();
  assert.deepEqual(calls, [{ initialize: true, maintenance: false }]);
  servicesReady = true;
  await coordinator.recover();
  assert.deepEqual(calls[1], { initialize: false, maintenance: false });
  servicesReady = false;
  await coordinator.close();
  assert.equal(calls.length, 2);
});

test("event notifications coalesce without losing a write after an active scan", async () => {
  let release!: () => void;
  const calls: { initialize: boolean; maintenance: boolean }[] = [];
  const coordinator = new CaptureCoordinator(async batch => {
    calls.push(batch);
    if (calls.length === 1) await new Promise<void>(resolve => { release = resolve; });
  });
  const initial = coordinator.request();
  await Promise.resolve();
  coordinator.request(true); coordinator.request(true);
  release(); await initial;
  assert.deepEqual(calls.filter(call => !call.maintenance), [{ initialize: true, maintenance: false }, { initialize: false, maintenance: false }]);
  assert.equal(await coordinator.recover(), "");
  assert.equal(calls.filter(call => !call.maintenance).length, 3);
  await coordinator.close(0);
});

test("awaited recovery reconciles every finalization microtask boundary", async () => {
  for (let gap = 0; gap <= 6; gap++) {
    let count = 0;
    const coordinator = new CaptureCoordinator(async () => { count++; });
    await coordinator.recover(); // Warm past initialization, which adds a batch.
    count = 0;
    const first = coordinator.request();
    for (let i = 0; i < gap; i++) await Promise.resolve();
    const recovery = coordinator.recover();
    await Promise.all([first, recovery]);
    assert.equal(count, gap === 0 ? 1 : 2, `microtask gap ${gap}`);
    await coordinator.close(0);
  }
});

test("optional maintenance cannot block prompt or recall recovery and is cancelled on close", { timeout: 2000 }, async () => {
  let started!: () => void;
  const ready = new Promise<void>(resolve => { started = resolve; });
  let cancelled = false;
  let captures = 0;
  let maintenance = 0;
  const coordinator = new CaptureCoordinator(async (batch, signal) => {
    if (!batch.maintenance) { captures++; return; }
    maintenance++;
    started();
    await new Promise<void>((_, reject) => signal.addEventListener("abort", () => {
      cancelled = true;
      reject(new Error("cancelled"));
    }, { once: true }));
  });
  try {
    await coordinator.request(true);
    await ready;
    for (let i = 0; i < 3; i++) assert.equal(await coordinator.recover(), "");
    assert.equal(captures, 5); // Baseline + initial capture + three barriers.
    assert.equal(maintenance, 1);
    assert.equal(cancelled, false);
  } finally { await coordinator.close(); }
  assert.equal(cancelled, true);
});

test("recovery failure is visible and retried on next recall", async () => {
  let fail = true;
  const coordinator = new CaptureCoordinator(async () => { if (fail) throw new Error("fixture"); });
  assert.match(await coordinator.recover(), /pending/);
  assert.equal(coordinator.ready, false);
  fail = false;
  assert.equal(await coordinator.recover(), "");
  assert.equal(coordinator.ready, true);
  await coordinator.close();
});

test("shutdown is bounded and cancels active work instead of waiting for inference", async () => {
  let cancelled = false;
  const coordinator = new CaptureCoordinator(async (_, signal) => {
    await new Promise<void>((_, reject) => signal.addEventListener("abort", () => { cancelled = true; reject(new Error("cancelled")); }));
  });
  void coordinator.request();
  await coordinator.close(10);
  assert.equal(cancelled, true);
  await coordinator.request(); // Closed coordinator cannot start another helper.
});

test("native generation is stateless and follows task/title/default model precedence", async () => {
  let titleCalls = 0;
  const requests: any[] = [];
  const ctx = { agent: { get: async () => { titleCalls++; return { data: { model: { providerID: "openai", id: "gpt-4o-mini" } } }; } },
    generate: { text: async (request: unknown) => { requests.push(request); return { text: "- summary" }; } },
  } as unknown as Plugin.Context;
  const signal = new AbortController().signal;
  await nativeText(ctx, { prompt: "bounded transcript", model: "custom/model/name#fast", task: "summarize" }, signal);
  assert.deepEqual(requests[0].model, { providerID: "custom", id: "model/name", variant: "fast" });
  await nativeText(ctx, { prompt: "bounded transcript", model: "", task: "summarize" }, signal);
  assert.equal(requests[1].model.id, "gpt-4o-mini");
  await nativeText(ctx, { prompt: "maintenance", model: "", task: "project_review" }, signal);
  assert.equal(requests[2].model, undefined);
  assert.equal(titleCalls, 1);
  assert.equal(requests[0].sessionID, undefined);
});

test("title lookup failure never silently invokes the main model", async () => {
  let generated = false;
  const ctx = {
    agent: { get: async () => { throw new Error("title agent lookup failed"); } },
    generate: { text: async () => { generated = true; return { text: "wrong route" }; } },
  } as unknown as Plugin.Context;
  await assert.rejects(nativeText(ctx, { prompt: "fixture", model: "", task: "summarize" }, new AbortController().signal), /title agent lookup failed/);
  assert.equal(generated, false);
});

test("a successfully resolved title agent without a model uses the host default", async () => {
  const ctx = {
    agent: { get: async () => ({ data: {} }) },
    generate: { text: async (request: any) => { assert.equal(request.model, undefined); return { text: "- default" }; } },
  } as unknown as Plugin.Context;
  assert.equal(await nativeText(ctx, { prompt: "fixture", model: "", task: "summarize" }, new AbortController().signal), "- default");
});
test("native deadline and cancellation reject late provider results", async () => {
  let finish!: (result: { text: string }) => void;
  const ctx = { generate: { text: () => new Promise(resolve => { finish = resolve; }) } } as unknown as Plugin.Context;
  const request = { prompt: "prompt", model: "openai/example", task: "summarize" };
  await assert.rejects(nativeText(ctx, request, new AbortController().signal, 10), /deadline/);
  finish({ text: "too late" });
  const abort = new AbortController();
  const pending = nativeText(ctx, request, abort.signal);
  abort.abort();
  await assert.rejects(pending, /cancelled/);
  finish({ text: "too late" });
});

test("finite helper exchanges native requests over stdin and completes", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-helper-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "scripts"));
  writeFileSync(join(root, "scripts/capture.py"), 'import json,sys\nprint(json.dumps({"type":"generate","prompt":"fixture","task":"summarize","model":"openai/example"}),flush=True)\nreply=json.loads(sys.stdin.readline())\nopen("reply.json","w").write(json.dumps(reply))\nprint(json.dumps({"type":"done"}),flush=True)\n');
  const ctx = { generate: { text: async () => ({ text: "- finite result" }) } } as unknown as Plugin.Context;
  const execute = helperRunner(ctx, root, { root, projectID: "p" }, "unused.db", "test", ["unused"]);
  await execute({ initialize: false, maintenance: false }, new AbortController().signal);
  assert.deepEqual(JSON.parse(readFileSync(join(root, "reply.json"), "utf8")), { text: "- finite result" });
});

test("helper cancellation discards a late inference reply", async t => {
  const root = mkdtempSync(join(tmpdir(), "memsearch-v2-cancel-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  mkdirSync(join(root, "scripts"));
  writeFileSync(join(root, "scripts/capture.py"), 'import json,sys\nprint(json.dumps({"type":"generate","prompt":"fixture","task":"summarize","model":"openai/example"}),flush=True)\nsys.stdin.readline()\n');
  let started!: () => void;
  const ready = new Promise<void>(resolve => { started = resolve; });
  let finish!: (result: { text: string }) => void;
  const ctx = { generate: { text: () => { started(); return new Promise(resolve => { finish = resolve; }); } } } as unknown as Plugin.Context;
  const abort = new AbortController();
  const execute = helperRunner(ctx, root, { root, projectID: "p" }, "unused", "test", ["unused"]);
  const work = execute({ initialize: false, maintenance: false }, abort.signal);
  const rejected = assert.rejects(work, /pending/);
  await ready; abort.abort(); await rejected;
  finish({ text: "late" }); await tick();
});
