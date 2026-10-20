import type { Plugin } from "@opencode/plugin";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { join } from "node:path";
import type { Command } from "./runtime.ts";
import { embeddingArgs } from "./runtime.ts";
import { scopeArgs, type Scope } from "./scope.ts";

export interface Batch { initialize: boolean; maintenance: boolean }
export type BatchRunner = (batch: Batch, signal: AbortSignal) => Promise<void>;

/** Serialize local triggers; the helper's file lock also serializes host instances. */
export class CaptureCoordinator {
  private active?: Promise<void>;
  private controller?: AbortController;
  private maintenanceController?: AbortController;
  private maintenanceActive?: Promise<void>;
  private requested = false;
  private captureRequested = false;
  private maintenance = false;
  private initialized = false;
  private closed = false;
  error = "";
  get ready() { return this.initialized; }
  private readonly execute: BatchRunner;
  constructor(execute: BatchRunner) { this.execute = execute; }

  request(maintenance = false): Promise<void> {
    return this.enqueue(true, maintenance);
  }

  /** Setup establishes cursors only; host agents/providers may still be loading. */
  initialize(): Promise<void> {
    if (this.initialized) return Promise.resolve();
    if (this.active) return this.active;
    return this.enqueue(false, false);
  }

  private enqueue(capture: boolean, maintenance: boolean): Promise<void> {
    if (this.closed) return Promise.resolve();
    this.requested = true;
    this.captureRequested ||= capture;
    this.maintenance ||= maintenance;
    if (!this.active) {
      // Install the promise before drain starts. Drain itself releases ownership
      // synchronously with its final queue check, not in a later Promise.finally.
      this.active = Promise.resolve().then(() => this.drain());
    }
    return this.active;
  }

  private async drain() {
    try {
      while (this.requested) {
        this.requested = false;
        const capture = this.captureRequested;
        this.captureRequested = false;
        this.controller = new AbortController();
        try {
          const initialize = !this.initialized;
          await this.execute({ initialize, maintenance: false }, this.controller.signal);
          this.initialized = true;
          if (initialize && capture && !this.closed) this.requested = true;
          this.error = "";
        } catch {
          this.error = "[memsearch] Capture/index recovery is pending. Existing memories remain available; check the V2 database, scope and CLI configuration.";
          this.requested = false;
        }
        if (this.closed) break;
      }
    } finally {
      this.active = undefined;
      this.startMaintenance();
    }
  }

  private startMaintenance() {
    if (this.closed || !this.ready || this.error || this.active || this.maintenanceActive || !this.maintenance) return;
    this.maintenance = false;
    const controller = this.maintenanceController = new AbortController();
    this.maintenanceActive = Promise.resolve().then(async () => {
      try {
        await this.execute({ initialize: false, maintenance: true }, controller.signal);
      } catch { /* Shared maintenance state records task errors; a later trigger retries. */ }
      finally {
        this.maintenanceActive = undefined;
        this.startMaintenance();
      }
    });
  }

  async recover(): Promise<string> {
    await this.request();
    return this.error;
  }

  async close(graceMs = 1200): Promise<void> {
    if (this.closed) return;
    // Only active work gets grace. Starting inference during teardown can turn
    // unavailable host services into a permanent failure note instead of replay.
    const work = this.active ?? Promise.resolve();
    this.closed = true;
    this.maintenance = false;
    this.maintenanceController?.abort();
    let timer: ReturnType<typeof setTimeout> | undefined;
    await Promise.race([work, new Promise<void>(resolve => { timer = setTimeout(resolve, graceMs); })]);
    clearTimeout(timer);
    this.controller?.abort();
  }
}

export function parseModel(value: string) {
  const [base, variant] = value.split("#", 2);
  const slash = base.indexOf("/");
  if (slash < 1 || slash === base.length - 1) throw new Error("Native model must be provider/model[#variant].");
  return { providerID: base.slice(0, slash), id: base.slice(slash + 1), ...(variant ? { variant } : {}) };
}

/** Explicit timeout/late-result guard: the pinned Promise SDK does not forward abort options. */
export async function nativeText(ctx: Pick<Plugin.Context, "agent" | "generate">, request: { prompt: string; model: string; task: string }, signal: AbortSignal, timeoutMs = 30_000): Promise<string> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  let abort: () => void = () => {};
  let finished = false;
  const cancelled = new Promise<never>((_, reject) => {
    abort = () => reject(new Error("Native generation cancelled"));
    signal.addEventListener("abort", abort, { once: true });
    if (signal.aborted) abort();
    timer = setTimeout(() => reject(new Error("Native generation deadline exceeded")), timeoutMs);
  });
  const generate = async () => {
    const model = request.model ? parseModel(request.model) : request.task === "summarize"
      ? (await ctx.agent.get({ agentID: "title" })).data.model : undefined;
    if (finished || signal.aborted) throw new Error("Native generation cancelled");
    return (await ctx.generate.text({ prompt: request.prompt, ...(model ? { model } : {}) })).text;
  };
  try { return await Promise.race([generate(), cancelled]); }
  finally { finished = true; clearTimeout(timer); signal.removeEventListener("abort", abort); }
}

export function helperRunner(ctx: Plugin.Context, pluginDir: string, scope: Scope, db: string, collection: string, command: Command): BatchRunner {
  return (batch, signal) => new Promise((resolve, reject) => {
    const child = spawn("python3", [join(pluginDir, "scripts/capture.py"), ...scopeArgs(scope), "--db", db,
      "--collection", collection, "--command", JSON.stringify(command),
      ...(embeddingArgs(scope.root).length ? ["--default-onnx"] : []),
      ...(batch.initialize ? ["--initialize"] : []), ...(batch.maintenance ? ["--maintenance"] : []),
    ], { cwd: scope.root, stdio: ["pipe", "pipe", "pipe"], env: { ...process.env, MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DIR: join(scope.root, ".memsearch") } });
    let stopped = false;
    let done = false;
    let killTimer: ReturnType<typeof setTimeout> | undefined;
    const stop = () => {
      stopped = true;
      child.kill("SIGTERM");
      killTimer = setTimeout(() => child.kill("SIGKILL"), 300);
      killTimer.unref();
    };
    signal.addEventListener("abort", stop, { once: true });
    // Keep the whole finite batch bounded even when a subprocess/lock stalls.
    const deadline = setTimeout(stop, 180_000);
    child.stderr.resume();
    child.stdin.on("error", () => {}); // An unload may close stdin while inference is finishing.
    const lines = createInterface({ input: child.stdout });
    lines.on("line", async line => {
      try {
        const request = JSON.parse(line);
        if (request.type === "done") done = true;
        if (request.type !== "generate" || stopped) return;
        let response;
        try { response = { text: await nativeText(ctx, request, signal, request.task === "summarize" ? 30_000 : 120_000) }; }
        catch { response = signal.aborted ? { cancelled: true } : { error: "Native summary unavailable" }; }
        if (!stopped && !signal.aborted && !child.stdin.destroyed) child.stdin.write(JSON.stringify(response) + "\n");
      } catch { stop(); }
    });
    const finish = (error?: Error) => {
      stopped = true;
      clearTimeout(deadline); clearTimeout(killTimer);
      signal.removeEventListener("abort", stop); lines.close();
      if (error) reject(error); else resolve();
    };
    child.on("error", () => finish(new Error("Capture helper could not start")));
    child.on("close", code => finish(code === 0 && done && !signal.aborted ? undefined : new Error("Capture remains pending")));
    if (signal.aborted) stop();
  });
}
