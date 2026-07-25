/**
 * memsearch pi plugin — semantic memory search across sessions.
 *
 * Registers:
 * - memory_search tool: semantic search over past memories (L1)
 * - memory_get tool: expand a chunk to its full markdown section (L2)
 * - session_start hook: ensure default config + initial background index
 * - before_agent_start hook: inject recent memories as cold-start context
 *
 * Memory is shared with the Claude Code, Codex, OpenCode, and OpenClaw plugins:
 * the collection name is derived from the project path via the shared
 * derive-collection.sh, and memories live in <project>/.memsearch/memory/.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { Type } from "typebox";

import { getRecentMemories, MEMSEARCH_HINT, shellEscape } from "./context.ts";

const execFileAsync = promisify(execFile);

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function getMemsearchDir(projectDir: string): string {
  return join(projectDir, ".memsearch");
}

function getMemoryDir(projectDir: string): string {
  return join(getMemsearchDir(projectDir), "memory");
}

/**
 * Detect the memsearch CLI invocation.
 * Checks: PATH -> ~/.local/bin/uvx -> uvx in PATH.
 */
async function detectMemsearchCmd(): Promise<string> {
  const home = process.env.HOME || "";

  try {
    await execFileAsync("which", ["memsearch"]);
    return "memsearch";
  } catch {
    /* not on PATH */
  }

  const uvxPath = join(home, ".local", "bin", "uvx");
  if (existsSync(uvxPath)) {
    return `${uvxPath} --from 'memsearch[onnx]' memsearch`;
  }

  try {
    await execFileAsync("which", ["uvx"]);
    return "uvx --from 'memsearch[onnx]' memsearch";
  } catch {
    /* not on PATH */
  }

  return "memsearch";
}

/**
 * Derive the per-project Milvus collection name via the shared script.
 * Must stay byte-identical to the other plugins' copies so memories are shared.
 */
async function deriveCollectionName(projectDir: string): Promise<string> {
  const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
  try {
    const { stdout } = await execFileAsync("bash", [script, projectDir], {
      timeout: 5000,
    });
    return stdout.trim();
  } catch {
    return "ms_pi_default";
  }
}

// Both lookups spawn a process, so memoize them for the life of the session.
let memsearchCmdPromise: Promise<string> | null = null;
function getMemsearchCmd(): Promise<string> {
  memsearchCmdPromise ??= detectMemsearchCmd();
  return memsearchCmdPromise;
}

const collectionPromises = new Map<string, Promise<string>>();
function getCollectionName(projectDir: string): Promise<string> {
  let promise = collectionPromises.get(projectDir);
  if (!promise) {
    promise = deriveCollectionName(projectDir);
    collectionPromises.set(projectDir, promise);
  }
  return promise;
}

/** Run a memsearch subcommand and return its output. */
async function runMemsearch(argline: string, timeoutMs: number): Promise<string> {
  const cmd = await getMemsearchCmd();
  const { stdout, stderr } = await execFileAsync("bash", ["-c", `${cmd} ${argline}`], {
    timeout: timeoutMs,
    maxBuffer: 10 * 1024 * 1024,
  });
  return stdout || stderr || "";
}

function toolText(text: string) {
  return { content: [{ type: "text" as const, text }], details: {} };
}

// ---------------------------------------------------------------------------
// Extension entry
// ---------------------------------------------------------------------------

export default async function (pi: ExtensionAPI) {
  // ----- Tool: memory_search (L1) -----
  pi.registerTool({
    name: "memory_search",
    label: "Memory Search",
    description:
      "Search past conversation memories using memsearch semantic search. " +
      "Returns relevant chunks from past sessions, including dates, topics " +
      "discussed, and code referenced. Powered by Milvus hybrid search " +
      "(BM25 + dense vectors + RRF reranking).",
    promptSnippet: "Search memories from past sessions",
    promptGuidelines: [
      "Use memory_search when the user's question could benefit from historical context, " +
        "past decisions, or previous debugging notes.",
    ],
    parameters: Type.Object({
      query: Type.String({
        description: "Search query — describe what you want to find",
      }),
      top_k: Type.Optional(
        Type.Number({ description: "Number of results to return (default: 5)" })
      ),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const collection = await getCollectionName(ctx.cwd);
      const topK = params.top_k ?? 5;
      try {
        const out = await runMemsearch(
          `search '${shellEscape(params.query)}' --top-k ${topK} ` +
            `--json-output --collection ${collection}`,
          30000
        );
        return toolText(out.trim() || "No results found.");
      } catch (e: any) {
        return toolText(`Search failed: ${e.message}`);
      }
    },
  });

  // ----- Tool: memory_get (L2) -----
  pi.registerTool({
    name: "memory_get",
    label: "Memory Get",
    description:
      "Expand a memory chunk to see the full markdown section with surrounding " +
      "context. Use after memory_search to get details about a specific result.",
    promptSnippet: "Expand a memory_search result to its full section",
    promptGuidelines: [
      "Use memory_get after memory_search when a result looks relevant but is truncated.",
    ],
    parameters: Type.Object({
      chunk_hash: Type.String({
        description: "The chunk_hash from a memory_search result to expand",
      }),
    }),
    async execute(_toolCallId, params, _signal, _onUpdate, ctx) {
      const collection = await getCollectionName(ctx.cwd);
      try {
        const out = await runMemsearch(
          `expand '${shellEscape(params.chunk_hash)}' --collection ${collection}`,
          15000
        );
        return toolText(out.trim() || "No content found.");
      } catch (e: any) {
        return toolText(`Expand failed: ${e.message}`);
      }
    },
  });

  // ----- Hook: session_start — ensure config + initial index -----
  pi.on("session_start", async (_event, ctx) => {
    const projectDir = ctx.cwd;
    const memoryDir = getMemoryDir(projectDir);
    const home = process.env.HOME || "";

    try {
      const cmd = await getMemsearchCmd();
      const collection = await getCollectionName(projectDir);

      // Ensure default config (onnx provider, no API key needed)
      const globalConfig = join(home, ".memsearch", "config.toml");
      const localConfig = join(projectDir, ".memsearch.toml");
      if (!existsSync(globalConfig) && !existsSync(localConfig)) {
        try {
          await execFileAsync(
            "bash",
            ["-c", `${cmd} config set embedding.provider onnx`],
            { timeout: 5000 }
          );
        } catch {
          /* best-effort */
        }
      }

      // Initial index in the background (fire-and-forget)
      if (existsSync(memoryDir)) {
        execFileAsync(
          "bash",
          [
            "-c",
            `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`,
          ],
          { timeout: 120000 }
        ).catch(() => {
          /* index failures must not break the session */
        });
      }
    } catch {
      /* never block session startup */
    }
  });

  // ----- Hook: before_agent_start — inject recent memories -----
  pi.on("before_agent_start", async (event, ctx) => {
    try {
      const context = getRecentMemories(getMemoryDir(ctx.cwd));
      if (!context) return;

      const block =
        `${MEMSEARCH_HINT} You can call memory_search and memory_get ` +
        `to recall past sessions.\n\n${context}`;

      return { systemPrompt: `${event.systemPrompt}\n\n${block}` };
    } catch {
      /* injection is best-effort */
    }
  });
}
