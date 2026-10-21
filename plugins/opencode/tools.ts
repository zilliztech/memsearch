import type { Plugin } from "@opencode/plugin";
import { Schema } from "effect";
import { execFile } from "node:child_process";
import { join } from "node:path";
import { type Scope, scopeArgs, sessionScope } from "./scope.ts";
import { type Command, embeddingArgs, run } from "./runtime.ts";
import type { CaptureCoordinator } from "./capture.ts";

const text = (max: number) => Schema.String.check(Schema.isMinLength(1), Schema.isMaxLength(max));
const integer = (min: number, max: number) => Schema.Int.check(Schema.isBetween({ minimum: min, maximum: max }));
export const searchInput = Schema.Struct({ query: text(4000), top_k: Schema.optionalKey(integer(1, 20)) });
export const getInput = Schema.Struct({ chunk_hash: text(256) });
export const transcriptInput = Schema.Struct({
  session_id: text(256), turn_id: Schema.optionalKey(text(256)), db_path: Schema.optionalKey(text(4096)),
  limit: Schema.optionalKey(integer(1, 50)), context: Schema.optionalKey(integer(0, 10)),
});

export async function registerTools(ctx: Plugin.Context, scope: Scope, collection: string, command: Command, capture: Pick<CaptureCoordinator, "recover">, pluginDir: string, db: string) {
  const query = (args: string[], sessionID: string, signal: AbortSignal) =>
    run(["python3"], [join(pluginDir, "scripts/capture.py"), ...scopeArgs(scope), "--db", db,
      "--collection", collection, "--command", JSON.stringify(command),
      "--query", JSON.stringify(args), "--session-id", sessionID], scope.root, signal)
      .catch(() => { throw new Error("MemSearch recall failed; check CLI/configuration and .memsearch/.index-state.json."); });
  return ctx.tool.transform(editor => {
    editor.add({
      name: "memory_search", description: "Search past conversation memories. Returns text containing a JSON array of result objects with chunk_hash, content and source, optionally prefixed by a recovery warning. Inspect the returned text before selecting a chunk_hash for memory_get.", input: searchInput, output: Schema.String,
      async execute(args, context) {
        const current = await sessionScope(ctx, scope, context.sessionID, db, pluginDir);
        const pending = await capture.recover();
        const output = await query(["search", args.query, "--top-k", String(args.top_k ?? 5), "--json-output", "--default-collection", collection, ...embeddingArgs(current.root)], context.sessionID, context.signal);
        const text = [pending, output || "[]"].filter(Boolean).join("\n\n");
        return { content: text, output: text };
      },
    });
    editor.add({
      name: "memory_get", description: "Expand a memory_search chunk hash to its full Markdown section, including session/turn/db transcript anchors. Returns text.", input: getInput, output: Schema.String,
      async execute(args, context) {
        await sessionScope(ctx, scope, context.sessionID, db, pluginDir);
        const pending = await capture.recover();
        const output = await query(["expand", args.chunk_hash, "--default-collection", collection], context.sessionID, context.signal);
        const text = [pending, output].filter(Boolean).join("\n\n");
        return { content: text, output: text };
      },
    });
    editor.add({
      name: "memory_transcript", description: "Read original OpenCode V2 user/assistant dialogue. Returns text. Pass session_id, turn_id and db_path from the anchor. Access is limited to this checkout/workspace; host migration belongs to the user.", input: transcriptInput, output: Schema.String,
      async execute(args, context) {
        const current = await sessionScope(ctx, scope, context.sessionID, db, pluginDir);
        const output = await new Promise<string>(resolve => {
          execFile("python3", [join(pluginDir, "scripts/parse-transcript.py"), args.session_id, ...scopeArgs(current),
            "--db", args.db_path ?? db, "--limit", String(args.limit ?? 20), "--context", String(args.context ?? 3),
            ...(args.turn_id ? ["--turn", args.turn_id] : []),
          ], { cwd: current.root, signal: context.signal, timeout: 15_000, maxBuffer: 2 * 1024 * 1024, encoding: "utf8" },
          (error, stdout, stderr) => resolve(error ? stderr.trim().slice(0, 1500) || "Transcript unavailable: helper failed or was cancelled." : stdout.trim()));
        });
        return { content: output, output };
      },
    });
  });
}
