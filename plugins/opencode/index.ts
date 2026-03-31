/**
 * memsearch OpenCode plugin — semantic memory search across sessions.
 *
 * Registers:
 * - memory_search tool: semantic search over past memories
 * - memory_get tool: expand a chunk to full context
 * - memory_transcript tool: parse original conversation from OpenCode SQLite
 * - experimental.chat.system.transform hook: inject recent memories as context
 *
 * Auto-capture is handled by a background Python daemon (capture-daemon.py)
 * that polls the OpenCode SQLite database for completed turns.
 */

import type { Plugin } from "@opencode-ai/plugin";
import { tool } from "@opencode-ai/plugin";
import { execSync, exec, spawnSync } from "node:child_process";
import {
  readFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
} from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Detect the memsearch CLI command.
 * Checks: PATH -> ~/.local/bin/uvx -> uvx in PATH.
 */
function detectMemsearchCmd(): string {
  const home = process.env.HOME || "";

  try {
    const r = spawnSync("which", ["memsearch"], { stdio: "pipe" });
    if (r.status === 0) return "memsearch";
  } catch { /* ignore */ }

  const uvxPath = join(home, ".local", "bin", "uvx");
  if (existsSync(uvxPath)) {
    return `${uvxPath} --from 'memsearch[onnx]' memsearch`;
  }

  try {
    const r = spawnSync("which", ["uvx"], { stdio: "pipe" });
    if (r.status === 0) return "uvx --from 'memsearch[onnx]' memsearch";
  } catch { /* ignore */ }

  return "memsearch";
}

/** Derive a per-project Milvus collection name via the shared script. */
function deriveCollectionName(projectDir: string): string {
  const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
  try {
    return execSync(`bash "${script}" "${projectDir}"`, {
      encoding: "utf-8",
      timeout: 5000,
    }).trim();
  } catch {
    return "ms_opencode_default";
  }
}

/**
 * Read the tail of the N most recent daily .md files for cold-start context.
 */
function getRecentMemories(
  memDir: string,
  count = 2,
  tailLines = 15
): string {
  if (!existsSync(memDir)) return "";

  const files = readdirSync(memDir)
    .filter((f) => f.endsWith(".md"))
    .sort()
    .slice(-count);

  if (files.length === 0) return "";

  const bullets: string[] = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = content.split("\n").slice(-tailLines);
      const fileBullets = lines.filter((l) => l.startsWith("- ") || l.startsWith("[Human]") || l.startsWith("[Assistant]"));
      if (fileBullets.length > 0) {
        bullets.push(`[${file}]`, ...fileBullets);
      }
    } catch { /* skip */ }
  }

  if (bullets.length === 0) {
    return `You have ${files.length} past memory file(s). Use the memory_search tool when the user's question could benefit from historical context.`;
  }

  return `Recent memories (use memory_search for full search):\n${bullets.join("\n")}`;
}

/** Shell-escape a string for safe use inside single quotes. */
function shellEscape(s: string): string {
  return s.replace(/'/g, "'\\''");
}

/**
 * Start the capture daemon as a background process.
 * The daemon polls OpenCode's SQLite for completed turns and writes to daily .md files.
 */
function startCaptureDaemon(
  projectDir: string,
  collectionName: string,
  memsearchCmd: string
): void {
  const pidFile = join(projectDir, ".memsearch", ".capture.pid");
  const daemonScript = join(PLUGIN_DIR, "scripts", "capture-daemon.py");

  // Check if daemon is already running
  if (existsSync(pidFile)) {
    try {
      const pid = parseInt(readFileSync(pidFile, "utf-8").trim(), 10);
      if (pid > 0) {
        // Check if process is still alive
        try {
          process.kill(pid, 0);
          return; // Already running
        } catch {
          // Process is dead, clean up stale PID file
        }
      }
    } catch { /* ignore */ }
  }

  // Start daemon in background
  exec(
    `python3 "${daemonScript}" "${projectDir}" "${collectionName}" ` +
      `--memsearch-cmd "${shellEscape(memsearchCmd)}" --poll-interval 10 &`,
    {
      timeout: 5000,
      env: { ...process.env, MEMSEARCH_NO_WATCH: "1" },
    },
    () => { /* ignore */ }
  );
}

/**
 * Stop the capture daemon.
 */
function stopCaptureDaemon(projectDir: string): void {
  const pidFile = join(projectDir, ".memsearch", ".capture.pid");
  if (existsSync(pidFile)) {
    try {
      const pid = parseInt(readFileSync(pidFile, "utf-8").trim(), 10);
      if (pid > 0) {
        try { process.kill(pid, "SIGTERM"); } catch { /* ignore */ }
      }
    } catch { /* ignore */ }
  }
}

// ---------------------------------------------------------------------------
// Plugin entry
// ---------------------------------------------------------------------------

const MemsearchPlugin: Plugin = async ({ project, directory, worktree }) => {
  // worktree can be "/" for global projects — use directory instead
  const projectDir = (worktree && worktree !== "/") ? worktree : (directory || process.cwd());
  const memsearchCmd = detectMemsearchCmd();
  const collectionName = deriveCollectionName(projectDir);
  const memsearchDir = join(projectDir, ".memsearch");
  const memoryDir = join(memsearchDir, "memory");
  const home = process.env.HOME || "~";

  // Skip capture/recall in child processes to prevent recursion
  const isChildProcess = !!process.env.MEMSEARCH_NO_WATCH;
  const autoCapture = !isChildProcess;
  const autoRecall = !isChildProcess;

  // Ensure default config (onnx provider) at startup
  try {
    const configFile = join(home, ".memsearch", "config.toml");
    const localConfig = join(projectDir, ".memsearch.toml");
    if (!existsSync(configFile) && !existsSync(localConfig)) {
      try {
        execSync(`${memsearchCmd} config set embedding.provider onnx`, {
          timeout: 5000,
          stdio: "ignore",
        });
      } catch { /* ignore */ }
    }
  } catch { /* ignore */ }

  // Run initial index in background
  if (existsSync(memoryDir)) {
    exec(
      `${memsearchCmd} index '${shellEscape(memoryDir)}' ` +
        `--collection ${collectionName}`,
      { timeout: 120000 },
      () => { /* ignore */ }
    );
  }

  // Start capture daemon for auto-capture
  if (autoCapture) {
    startCaptureDaemon(projectDir, collectionName, memsearchCmd);
  }

  return {
    // ----- Tools -----
    tool: {
      memory_search: tool({
        description:
          "Search past conversation memories using memsearch semantic search. " +
          "Returns relevant chunks from past sessions, including dates, " +
          "topics discussed, and code referenced. Powered by Milvus hybrid " +
          "search (BM25 + dense vectors + RRF reranking).",
        args: {
          query: tool.schema.string().describe("Search query — describe what you want to find"),
          top_k: tool.schema.number().optional().describe("Number of results to return (default: 5)"),
        },
        async execute(args, context) {
          // Use context.directory for the actual session directory (may differ from init)
          const dir = context?.directory || projectDir;
          const col = dir !== projectDir ? deriveCollectionName(dir) : collectionName;
          const memDir = join(dir, ".memsearch", "memory");
          // Ensure daemon is running for current directory
          if (autoCapture) startCaptureDaemon(dir, col, memsearchCmd);
          const topK = args.top_k || 5;
          try {
            const result = spawnSync(
              "bash",
              [
                "-c",
                `${memsearchCmd} search '${shellEscape(args.query)}' ` +
                  `--top-k ${topK} --json-output --collection ${col}`,
              ],
              { encoding: "utf-8", timeout: 30000 }
            );
            return result.stdout || result.stderr || "No results found.";
          } catch (e: any) {
            return `Search failed: ${e.message}`;
          }
        },
      }),

      memory_get: tool({
        description:
          "Expand a memory chunk to see the full markdown section with " +
          "surrounding context. Use after memory_search to get details " +
          "about a specific result.",
        args: {
          chunk_hash: tool.schema.string().describe("The chunk_hash from a search result to expand"),
        },
        async execute(args, context) {
          const dir = context?.directory || projectDir;
          const col = dir !== projectDir ? deriveCollectionName(dir) : collectionName;
          if (autoCapture) startCaptureDaemon(dir, col, memsearchCmd);
          try {
            const result = spawnSync(
              "bash",
              [
                "-c",
                `${memsearchCmd} expand '${shellEscape(args.chunk_hash)}' ` +
                  `--collection ${col}`,
              ],
              { encoding: "utf-8", timeout: 15000 }
            );
            return result.stdout || result.stderr || "No content found.";
          } catch (e: any) {
            return `Expand failed: ${e.message}`;
          }
        },
      }),

      memory_transcript: tool({
        description:
          "Retrieve the original conversation from a past OpenCode session. " +
          "Use after memory_get when the expanded result contains a session anchor " +
          "(<!-- session:ID db:PATH -->). Returns the formatted " +
          "dialogue with [Human] and [Assistant] labels.",
        args: {
          session_id: tool.schema.string().describe("The session ID from the anchor comment"),
          limit: tool.schema.number().optional().describe("Max number of messages to return (default: 20)"),
        },
        async execute(args, context) {
          const dir = context?.directory || projectDir;
          const col = dir !== projectDir ? deriveCollectionName(dir) : collectionName;
          if (autoCapture) startCaptureDaemon(dir, col, memsearchCmd);
          try {
            const scriptPath = join(PLUGIN_DIR, "scripts", "parse-transcript.py");
            const result = spawnSync(
              "python3",
              [scriptPath, args.session_id, ...(args.limit ? ["--limit", String(args.limit)] : [])],
              { encoding: "utf-8", timeout: 15000 }
            );
            return result.stdout?.trim() || result.stderr || "No transcript content found.";
          } catch (e: any) {
            return `Transcript parse failed: ${e.message}`;
          }
        },
      }),
    },

    // ----- Hook: system prompt transform — inject recent memories -----
    ...(autoRecall
      ? {
          "experimental.chat.system.transform": async (_input: any, output: any) => {
            try {
              const context = getRecentMemories(memoryDir);
              if (context) {
                output.system.push(
                  `[memsearch] Memory available. You have access to memory_search, memory_get, and memory_transcript tools for recalling past sessions.\n\n${context}`
                );
              }
            } catch { /* ignore */ }
          },
        }
      : {}),
  };
};

export default MemsearchPlugin;
