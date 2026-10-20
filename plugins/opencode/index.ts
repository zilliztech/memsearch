/** OpenCode V2 memory capture and recall plugin. */
import { Plugin } from "@opencode/plugin";
import { dirname, join } from "node:path";
import { realpathSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { CaptureCoordinator, helperRunner } from "./capture.ts";
import { getRecentMemories, MEMSEARCH_SYSTEM_MARKER, mergeSystemMemoryContext } from "./context.ts";
import { deriveCollectionNameFromScript } from "./derive-collection.ts";
import { detectCommand, run } from "./runtime.ts";
import { databasePath, hostScope, sessionScope } from "./scope.ts";
import { registerSkills } from "./skills.ts";
import { registerTools } from "./tools.ts";

const pluginDir = dirname(realpathSync(fileURLToPath(import.meta.url)));

export default Plugin.define({
  id: "memsearch",
  async setup(ctx) {
    const version = /^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$/.exec(ctx.app.version);
    if (!version || Number(version[1]) !== 2 || Number(version[2]) === 0 && Number(version[3]) < 32) {
      throw new Error("MemSearch requires OpenCode V2 >=2.0.32 <3. V1 users must pin @zilliz/memsearch-opencode@0.3.17; host migration is user-owned.");
    }
    if (process.env.MEMSEARCH_NO_WATCH) return;
    const scope = hostScope(ctx);
    const db = databasePath(ctx.app.channel);
    const command = detectCommand();
    const collection = deriveCollectionNameFromScript(join(pluginDir, "scripts/derive-collection.sh"), scope.root);
    await run(command, ["config", "get", "milvus.collection", "--default-collection", collection], scope.root, undefined, 15_000);
    const capture = new CaptureCoordinator(helperRunner(ctx, pluginDir, scope, db, collection, command));
    const events = new AbortController();
    const registrations: { dispose(): Promise<void> }[] = [];
    try {
      // Establish the first-install baseline before accepting prompts or recall.
      await capture.initialize();
      if (!capture.ready) throw new Error("MemSearch could not establish its V2 capture baseline. Check host database/schema and CLI configuration before enabling the plugin.");
      registrations.push(await registerSkills(ctx, pluginDir));
      registrations.push(await registerTools(ctx, scope, collection, command, capture, pluginDir, db));
      registrations.push(await ctx.session.hook("prompt", async input => {
        await sessionScope(ctx, scope, input.sessionID, db, pluginDir);
        await capture.recover();
      }));
      registrations.push(await ctx.session.hook("context", async input => {
        await sessionScope(ctx, scope, input.sessionID, db, pluginDir);
        const pending = await capture.recover();
        const hint = await run(command, ["skills", "status", "--hint"], scope.root, undefined, 5000).catch(() => "");
        const memory = getRecentMemories(join(scope.root, ".memsearch/memory"));
        input.system = mergeSystemMemoryContext(input.system, [MEMSEARCH_SYSTEM_MARKER,
          "Use memory_search → memory_get → memory_transcript for relevant history. Skills: memory-recall, memory-config, memory-to-skill.",
          memory, hint, pending].filter(Boolean).join("\n\n"));
      }));
    } catch (error) {
      events.abort();
      await capture.close(0);
      await Promise.all(registrations.map(item => item.dispose()));
      throw error;
    }
    // Subscribe only after baseline and registrations: a setup-time event must
    // never merge inference into the initialization promise awaited by the host.
    // Prompt/recall recovery and the timer scan cover events missed during setup.
    const subscription = (async () => {
      try {
        for await (const event of ctx.event.subscribe({ signal: events.signal })) {
          if (["session.execution.succeeded", "session.execution.failed", "session.execution.interrupted"].includes(event.type) && "sessionID" in event.data) {
            try {
              await sessionScope(ctx, scope, String(event.data.sessionID), db, pluginDir);
              void capture.request(true);
            } catch { /* Foreign location/session; never redirect capture there. */ }
          }
        }
      } catch { /* The recovery scan covers dropped streams as well as shutdown. */ }
    })();
    const timer = setInterval(() => { void capture.request(true); }, 15_000);
    timer.unref();
    return async () => {
      clearInterval(timer); events.abort();
      // The host allows three seconds. Preserve pending work and recover before next recall.
      await capture.close();
      await Promise.all(registrations.map(item => item.dispose()));
      void subscription;
    };
  },
});
