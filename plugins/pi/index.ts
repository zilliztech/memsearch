/**
 * memsearch pi plugin — semantic memory search across sessions.
 *
 * Registers:
 * - memory_search tool: semantic search over past memories (L1)
 * - memory_get tool: expand a chunk to its full markdown section (L2)
 * - session_start hook: ensure default config + initial background index
 * - before_agent_start hook: inject recent memories as cold-start context
 * - agent_settled hook: auto-capture per-turn summary (extract, summarize, write)
 *
 * Memory is shared with the Claude Code, Codex, OpenCode, and OpenClaw plugins:
 * the collection name is derived from the project path via the shared
 * derive-collection.sh, and memories live in <project>/.memsearch/memory/.
 */

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { execFile, spawn } from "node:child_process";
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { promisify } from "node:util";
import { Type } from "typebox";

import {
  extractLastTurn,
  getRecentMemories,
  isNoiseLine,
  MEMSEARCH_HINT,
  shellEscape,
  tailTruncate,
} from "./context.ts";

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

function ensureDir(dir: string): void {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
}

/**
 * Capture and injection failures are swallowed so they can never break a
 * session, which makes them invisible when something is misconfigured.
 * Set MEMSEARCH_DEBUG=<path> to have those failures appended to a file.
 */
function debugLog(stage: string, err: unknown): void {
  const target = process.env.MEMSEARCH_DEBUG;
  if (!target) return;
  try {
    const message = err instanceof Error ? err.message : String(err);
    appendFileSync(target, `[${new Date().toISOString()}] ${stage}: ${message}\n`);
  } catch {
    /* debugging must not throw either */
  }
}

/**
 * Marks child processes we spawn so their own memsearch hooks stay inert.
 * Without this the `pi -p` summarization fallback would settle its own turn,
 * capture it, and spawn another summarizer — recursing without bound.
 */
const CHILD_ENV = { MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" };
const IS_CHILD_PROCESS = !!process.env.MEMSEARCH_NO_WATCH;

/**
 * Run a child process and resolve with its stdout.
 *
 * When `input` is omitted stdin is closed rather than left as an open pipe:
 * `pi -p` reads stdin and would otherwise wait for an EOF that never arrives.
 */
function runChild(
  command: string,
  args: string[],
  { input, timeoutMs }: { input?: string; timeoutMs: number }
): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      stdio: [input === undefined ? "ignore" : "pipe", "pipe", "pipe"],
      env: { ...process.env, ...CHILD_ENV },
    });

    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error(`timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    child.stdout.on("data", (chunk) => (stdout += chunk));
    child.stderr.on("data", (chunk) => (stderr += chunk));
    child.on("error", (err) => {
      clearTimeout(timer);
      reject(err);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) resolve(stdout);
      else reject(new Error(stderr.trim() || `exited with code ${code}`));
    });

    if (input !== undefined) {
      child.stdin.write(input);
      child.stdin.end();
    }
  });
}

/**
 * Re-invoke pi using the running process's own node binary and entry script.
 * Resolving `pi` from PATH is unreliable: under Volta the PATH entry is a shim
 * that refuses to run when the working directory has no project-local install,
 * which is exactly the case in most projects.
 */
function piInvocation(): { command: string; prefixArgs: string[] } {
  const entry = process.argv[1];
  if (entry && existsSync(entry)) {
    return { command: process.execPath, prefixArgs: [entry] };
  }
  return { command: "pi", prefixArgs: [] };
}

/**
 * Summarize one turn as third-person notes.
 * Falls back through: memsearch-managed LLM -> `pi -p` -> raw tail.
 */
async function summarizeTurn(turnText: string): Promise<string> {
  const cmd = await getMemsearchCmd();

  // 1. memsearch-managed provider, when the user configured plugins.pi.summarize
  try {
    const out = await runChild(
      "bash",
      ["-c", `${cmd} summarize --plugin pi --agent-name Pi`],
      { input: turnText, timeoutMs: 60000 }
    );
    if (out.trim()) return out.trim();
  } catch (err) {
    debugLog("summarize/memsearch", err);
  }

  // 2. pi itself, in print mode
  try {
    const template = readFileSync(
      join(PLUGIN_DIR, "prompts", "summarize.txt"),
      "utf-8"
    ).replace(/\{\{AGENT_NAME\}\}/g, "Pi");
    const { command, prefixArgs } = piInvocation();
    const stdout = await runChild(
      command,
      [...prefixArgs, "-p", `${template}\n\nTranscript:\n${turnText}`],
      { timeoutMs: 120000 }
    );
    if (stdout.trim().includes("- ")) return stdout.trim();
    debugLog("summarize/pi", `no bullets in output: ${JSON.stringify(stdout.slice(0, 200))}`);
  } catch (err) {
    debugLog("summarize/pi", err);
  }

  // 3. Raw text, truncated
  return tailTruncate(turnText, 1500);
}

// The per-session heading is written on first capture, not at session start,
// so sessions that never produce a memory leave no stub behind.
let sessionHeadingWritten = false;

/** Summarize a turn and append it to today's journal, then reindex. */
async function writeTurnCapture(
  turnText: string,
  projectDir: string,
  sessionId?: string,
  sessionFile?: string
): Promise<void> {
  const memoryDir = getMemoryDir(projectDir);
  const now = new Date();
  const today = now.toISOString().split("T")[0];
  const clock = now.toTimeString().slice(0, 5);
  const memoryFile = join(memoryDir, `${today}.md`);

  const summary = await summarizeTurn(turnText);
  const cleaned = summary
    .split("\n")
    .filter((line) => !isNoiseLine(line))
    .join("\n")
    .trim();
  if (!cleaned) return;

  ensureDir(memoryDir);
  if (!existsSync(memoryFile)) {
    writeFileSync(memoryFile, `# ${today}\n\n`, "utf-8");
  }
  if (!sessionHeadingWritten) {
    appendFileSync(memoryFile, `## Session ${clock}\n\n`, "utf-8");
    sessionHeadingWritten = true;
  }

  const anchor = sessionId
    ? `<!-- session:${sessionId}${sessionFile ? ` transcript:${sessionFile}` : ""} -->\n`
    : "";
  appendFileSync(memoryFile, `### ${clock}\n${anchor}${cleaned}\n\n`, "utf-8");

  const cmd = await getMemsearchCmd();
  const collection = await getCollectionName(projectDir);
  execFileAsync(
    "bash",
    ["-c", `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`],
    { timeout: 60000 }
  ).catch(() => {
    /* the journal is the source of truth; indexing can catch up later */
  });
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
    if (IS_CHILD_PROCESS) return;
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

  // ----- Hook: agent_settled — capture the turn -----
  // agent_settled rather than agent_end: pi may still auto-retry, auto-compact,
  // or drain queued messages after agent_end, which would capture the same turn
  // more than once.
  pi.on("agent_settled", async (_event, ctx) => {
    if (IS_CHILD_PROCESS) return;
    try {
      const entries = ctx.sessionManager.buildContextEntries();
      const turn = extractLastTurn(entries);
      if (!turn || turn.length < 50) return;

      await writeTurnCapture(
        turn,
        ctx.cwd,
        ctx.sessionManager.getSessionId(),
        ctx.sessionManager.getSessionFile()
      );
    } catch (err) {
      debugLog("capture", err);
    }
  });
}
