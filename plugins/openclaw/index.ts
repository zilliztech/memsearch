/**
 * memsearch OpenClaw plugin — semantic memory search across sessions.
 *
 * Registers:
 * - memory_search tool: semantic search over past memories
 * - memory_get tool: expand a chunk to full context
 * - memory_transcript tool: parse original conversation from JSONL transcript
 * - before_agent_start hook: inject recent memories as cold-start context
 * - agent_end hook: auto-capture per-turn summary (extract → summarize → write)
 * - CLI: `memsearch` subcommand (search, index, status)
 */

import {
  readFileSync,
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  writeFileSync,
} from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Helpers (no external process calls — those live inside register())
// ---------------------------------------------------------------------------

function getMemsearchDir(projectDir: string): string {
  return join(projectDir, ".memsearch");
}

function getMemoryDir(projectDir: string): string {
  return join(getMemsearchDir(projectDir), "memory");
}

function ensureDir(dir: string): string {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  return dir;
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

  // Extract only bullet-point lines (start with "- ") to keep context
  // concise and avoid prependContext being echoed back as llm_output.
  const bullets: string[] = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = content.split("\n").slice(-tailLines);
      const fileBullets = lines.filter((l) => l.startsWith("- "));
      if (fileBullets.length > 0) {
        bullets.push(`[${file}]`, ...fileBullets);
      }
    } catch {
      /* skip unreadable files */
    }
  }

  if (bullets.length === 0) {
    return `You have ${files.length} past memory file(s). Use the memory_search tool when the user's question could benefit from historical context.`;
  }

  return `Recent memories (use memory_search for full search):\n${bullets.join("\n")}`;
}

/**
 * Shell-escape a string for safe use inside single quotes.
 * Replaces ' with '\'' (end quote, escaped quote, start quote).
 */
function shellEscape(s: string): string {
  return s.replace(/'/g, "'\\''");
}

/** Noise patterns to filter from extracted message text. */
const NOISE_PATTERNS = [
  /^\[plugins\]/,
  /^\[tools\]/,
  /^\[agent\//,
  /^Config warnings/,
  /^\[memsearch\]/,
  /^WARNING:/,
  /^Error:/,
  /^Config invalid/,
  /^Config overwrite/,
  /plugins\.allow is empty/,
  /Plugin loaded\./,
  /autoCapture:/,
  /^Sender \(untrusted/,
  /^```json$/,
  /^```$/,
  /^"label":/,
  /^"id":/,
  /^"name":/,
  /^"username":/,
  /^\{$/,
  /^\}$/,
  /^# Recent Memory/,
  /^## \d{4}-\d{2}-\d{2}\.md/,
  /^## Session \d/,
  /^### \d{2}:\d{2}$/,
  /^\[\[reply_to_\w+\]\]/,
];

/** Check if a text line is system/log noise. */
function isNoiseLine(line: string): boolean {
  const trimmed = line.trim();
  return NOISE_PATTERNS.some((pat) => pat.test(trimmed));
}

/** Extract meaningful text from message content, filtering noise. */
function extractText(content: any): string {
  let raw: string;
  if (typeof content === "string") {
    raw = content;
  } else if (Array.isArray(content)) {
    raw = content
      .filter((c: any) => c.type === "text")
      .map((c: any) => c.text || "")
      .join("\n");
  } else {
    return "";
  }
  // Filter out noise lines
  return raw
    .split("\n")
    .filter((line) => !isNoiseLine(line))
    .join("\n")
    .trim();
}

/**
 * Extract the last user+assistant turn from an array of messages.
 * Returns a formatted string or null if no valid turn found.
 */
function extractLastTurn(messages: any[]): string | null {
  // Find the last real user message (not tool_result, not empty)
  let lastUserIdx = -1;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    const role = msg?.role || msg?.message?.role;
    if (role === "user") {
      const content = msg?.content || msg?.message?.content;
      const text = extractText(content);
      if (text.length > 10) {
        lastUserIdx = i;
        break;
      }
    }
  }

  if (lastUserIdx === -1) return null;

  const parts: string[] = [];
  for (let i = lastUserIdx; i < messages.length; i++) {
    const msg = messages[i];
    const role = msg?.role || msg?.message?.role;
    const content = msg?.content || msg?.message?.content;
    const text = extractText(content);

    if (!text || text.length < 5) continue;

    if (role === "user") {
      parts.push(`[Human]: ${text}`);
    } else if (role === "assistant") {
      // Truncate long assistant responses
      parts.push(`[Assistant]: ${text.slice(0, 3000)}`);
    }
  }

  if (parts.length === 0) return null;
  return parts.join("\n\n");
}

/**
 * Build a full env object with overrides (needed because runCommandWithTimeout
 * replaces the env entirely when the env option is specified).
 */
function envWithOverrides(overrides: Record<string, string>): Record<string, string> {
  const env: Record<string, string> = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== undefined) env[k] = v;
  }
  return { ...env, ...overrides };
}

// ---------------------------------------------------------------------------
// Plugin entry
// ---------------------------------------------------------------------------

export default {
  id: "memsearch",
  name: "memsearch",
  description:
    "Semantic memory search — remembers what you worked on across sessions",
  kind: "memory" as const,

  register(api: any) {
    const pluginConfig = api.pluginConfig || {};
    // Skip capture/recall in child processes (e.g. summarize agent) to prevent recursion
    const isChildProcess = !!process.env.MEMSEARCH_NO_WATCH;
    const autoCapture = pluginConfig.autoCapture !== false && !isChildProcess;
    const autoRecall = pluginConfig.autoRecall !== false && !isChildProcess;
    const logger = api.logger;
    const home = process.env.HOME || "~";

    // Convenience wrapper for api.runtime.system.runCommandWithTimeout
    async function runCmd(
      argv: string[],
      opts?: { timeoutMs?: number; cwd?: string; env?: Record<string, string> }
    ): Promise<{ stdout: string; stderr: string; code: number | null }> {
      return api.runtime.system.runCommandWithTimeout(argv, opts || {});
    }

    // --- Lazy-cached memsearch CLI detection ---
    let _memsearchCmd: string | null = null;

    async function getMemsearchCmd(): Promise<string> {
      if (_memsearchCmd) return _memsearchCmd;
      const h = process.env.HOME || "";

      // 1. Check PATH
      try {
        const r = await runCmd(["which", "memsearch"], { timeoutMs: 5000 });
        if (r.code === 0) {
          _memsearchCmd = "memsearch";
          return _memsearchCmd;
        }
      } catch {
        /* ignore */
      }

      // 2. Check ~/.local/bin (where uv/uvx are installed)
      const uvxPath = join(h, ".local", "bin", "uvx");
      if (existsSync(uvxPath)) {
        _memsearchCmd = `${uvxPath} --from 'memsearch[onnx]' memsearch`;
        return _memsearchCmd;
      }

      // 3. Check if uvx is in PATH
      try {
        const r = await runCmd(["which", "uvx"], { timeoutMs: 5000 });
        if (r.code === 0) {
          _memsearchCmd = "uvx --from 'memsearch[onnx]' memsearch";
          return _memsearchCmd;
        }
      } catch {
        /* ignore */
      }

      // 4. Last resort: hope memsearch is somewhere in PATH at runtime
      _memsearchCmd = "memsearch";
      return _memsearchCmd;
    }

    // --- Lazy-cached collection name derivation ---
    let _collectionNameFor = "";
    let _collectionName = "ms_openclaw_default";

    async function getCollectionName(): Promise<string> {
      if (_collectionNameFor === projectDir) return _collectionName;
      const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
      try {
        const r = await runCmd(["bash", script, projectDir], { timeoutMs: 5000 });
        if (r.code === 0 && r.stdout?.trim()) {
          _collectionName = r.stdout.trim();
        } else {
          _collectionName = "ms_openclaw_default";
        }
      } catch {
        _collectionName = "ms_openclaw_default";
      }
      _collectionNameFor = projectDir;
      return _collectionName;
    }

    // Per-agent state — defaults updated on first tool call via factory ctx.
    // Memory lives under <workspace>/.memsearch/memory/ — co-located with
    // AGENTS.md, IDENTITY.md, etc. Collection name is derived from the
    // workspace path (same algorithm as Claude Code/Codex/OpenCode) so that
    // memories are automatically shared when multiple platforms work on the
    // same project directory.
    let agentId = "main";
    let projectDir = join(home, ".openclaw", "workspace");  // default main workspace
    let memsearchDir = join(projectDir, ".memsearch");
    let memoryDir = join(memsearchDir, "memory");

    /** Update agent context from tool factory ctx. Called on each tool invocation. */
    function updateAgentContext(ctx: any): void {
      const newId = ctx?.agentId;
      const newWorkspace = ctx?.workspaceDir;
      if (newId && (newId !== agentId || (newWorkspace && newWorkspace !== projectDir))) {
        agentId = newId;
        projectDir = newWorkspace || join(home, ".openclaw", `workspace-${agentId}`);
        memsearchDir = join(projectDir, ".memsearch");
        memoryDir = join(memsearchDir, "memory");
        // Invalidate cached collection name — will be re-derived on next getCollectionName()
        _collectionNameFor = "";
        logger?.info?.(
          `[memsearch] Agent context updated: ${agentId}, dir: ${projectDir}`
        );
      }
    }

    // ----- Tool: memory_search -----
    // Named "memory_search" to match OpenClaw's tools profile allowlist.
    // Uses factory pattern to capture agentId from ctx on each invocation.
    api.registerTool(
      (ctx: any) => {
        updateAgentContext(ctx);
        return {
          name: "memory_search",
          label: "Memory Search",
          description:
            "Search past conversation memories using memsearch semantic search. " +
            "Returns relevant chunks from past sessions, including dates, " +
            "topics discussed, and code referenced. Powered by Milvus hybrid " +
            "search (BM25 + dense vectors + RRF reranking).",
          parameters: {
            type: "object" as const,
            properties: {
              query: {
                type: "string" as const,
                description: "Search query — describe what you want to find",
              },
              top_k: {
                type: "number" as const,
                description: "Number of results to return (default: 5)",
              },
            },
            required: ["query"],
          },
          async execute(
            _toolCallId: string,
            params: { query: string; top_k?: number }
          ) {
            const topK = params.top_k || 5;
            try {
              const cmd = await getMemsearchCmd();
              const collection = await getCollectionName();
              const result = await runCmd(
                [
                  "bash", "-c",
                  `${cmd} search '${shellEscape(params.query)}' ` +
                    `--top-k ${topK} --json-output --collection ${collection}`,
                ],
                { timeoutMs: 30000 }
              );
              const output = result.stdout || result.stderr || "No results";
              return { content: [{ type: "text" as const, text: output }] };
            } catch (e: any) {
              return {
                content: [
                  { type: "text" as const, text: `Search failed: ${e.message}` },
                ],
              };
            }
          },
        };
      },
      { name: "memory_search" }
    );

    // ----- Tool: memory_get -----
    // Named "memory_get" to match OpenClaw's tools profile allowlist.
    // Expands a chunk to full context (equivalent to memsearch expand).
    api.registerTool(
      (ctx: any) => {
        updateAgentContext(ctx);
        return {
          name: "memory_get",
          label: "Memory Get",
          description:
            "Expand a memory chunk to see the full markdown section with " +
            "surrounding context. Use after memory_search to get details " +
            "about a specific result.",
          parameters: {
            type: "object" as const,
            properties: {
              chunk_hash: {
                type: "string" as const,
                description: "The chunk_hash from a search result to expand",
              },
            },
            required: ["chunk_hash"],
          },
          async execute(
            _toolCallId: string,
            params: { chunk_hash: string }
          ) {
            try {
              const cmd = await getMemsearchCmd();
              const collection = await getCollectionName();
              const result = await runCmd(
                [
                  "bash", "-c",
                  `${cmd} expand '${shellEscape(params.chunk_hash)}' ` +
                    `--collection ${collection}`,
                ],
                { timeoutMs: 15000 }
              );
              const output = result.stdout || result.stderr || "No content";
              return { content: [{ type: "text" as const, text: output }] };
            } catch (e: any) {
              return {
                content: [
                  { type: "text" as const, text: `Expand failed: ${e.message}` },
                ],
              };
            }
          },
        };
      },
      { name: "memory_get" }
    );

    // ----- Tool: memory_transcript (L3) -----
    // Parses the original conversation from an OpenClaw JSONL transcript file.
    // Use after memory_get when the expanded chunk contains a transcript anchor.
    api.registerTool(
      (ctx: any) => {
        updateAgentContext(ctx);
        return {
          name: "memory_transcript",
          label: "Memory Transcript",
          description:
            "Retrieve the original conversation from a past session transcript. " +
            "Use after memory_get when the expanded result contains a transcript " +
            "anchor (<!-- session:UUID transcript:PATH -->). Returns the formatted " +
            "dialogue with [Human] and [Assistant] labels.",
          parameters: {
            type: "object" as const,
            properties: {
              transcript_path: {
                type: "string" as const,
                description: "Path to the .jsonl transcript file (from the anchor comment)",
              },
            },
            required: ["transcript_path"],
          },
          async execute(
            _toolCallId: string,
            params: { transcript_path: string }
          ) {
            try {
              const scriptPath = join(PLUGIN_DIR, "scripts", "parse-transcript.sh");
              const result = await runCmd(
                ["bash", scriptPath, params.transcript_path],
                { timeoutMs: 15000 }
              );
              const output = result.stdout?.trim() || result.stderr || "No transcript content";
              return { content: [{ type: "text" as const, text: output }] };
            } catch (e: any) {
              return {
                content: [
                  { type: "text" as const, text: `Transcript parse failed: ${e.message}` },
                ],
              };
            }
          },
        };
      },
      { name: "memory_transcript" }
    );

    // ----- Hook: before_agent_start — inject recent memories -----
    if (autoRecall) {
      api.on("before_agent_start", async () => {
        try {
          const context = getRecentMemories(memoryDir);
          if (context) {
            return { prependContext: context };
          }
        } catch (e: any) {
          logger?.warn?.(
            `[memsearch] Failed to inject memories: ${e.message}`
          );
        }
        return {};
      });
    }

    // ----- Auto-capture: per-turn summary via agent_end -----
    //
    // agent_end fires after every turn in TUI mode (after each
    // runEmbeddedAttempt() completes) and in non-interactive mode.
    // It provides event.messages (full messagesSnapshot), which gives us
    // clean structured data to extract the last user+assistant turn.
    //
    // Known limitations (upstream OpenClaw issues):
    // - #50025: agent_end doesn't fire for non-default agents
    // - #51189: agent_end doesn't fire on Feishu channel
    // - #57636: Can't distinguish main agent vs subagent
    if (autoCapture) {
      /**
       * Summarize a conversation turn using an LLM CLI.
       * Tries: openclaw agent → raw text fallback.
       */
      async function summarizeWithLLM(turnText: string): Promise<string> {
        const systemPrompt =
          "You are a third-person note-taker. You will receive a transcript of ONE conversation turn " +
          "between a human and an AI assistant (OpenClaw). " +
          "Your job is to record what happened as factual third-person notes. " +
          "You are an EXTERNAL OBSERVER — you are NOT the assistant. " +
          "Do NOT answer the human's question, do NOT give suggestions. ONLY record what occurred.\n\n" +
          "Output 2-6 bullet points, each starting with '- '. NOTHING else.\n\n" +
          "Rules:\n" +
          "- Write in third person: 'User asked...', 'OpenClaw replied...', 'OpenClaw ran command Y'\n" +
          "- First bullet: what the user asked or wanted (one sentence)\n" +
          "- Remaining bullets: what was done — tools called, files read/edited, key findings\n" +
          "- Be specific: mention file names, function names, tool names, and concrete outcomes\n" +
          "- Do NOT answer the human's question yourself — just note what was discussed\n" +
          "- Do NOT add any text before or after the bullet points\n" +
          "- Write in the same language as the human's message";

        // 1. Try openclaw agent (uses user's default model)
        try {
          const msgText = `${systemPrompt}\n\nTranscript:\n${turnText}`;
          const result = await runCmd(
            ["openclaw", "agent", "--local", "--session-id", "memsearch-summarize", "-m", msgText],
            {
              timeoutMs: 30000,
              env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1" }),
            }
          );
          const output = result.stdout?.trim();
          if (output && output.includes("- ")) {
            return output;
          }
        } catch {
          /* ignore */
        }

        // 2. Fallback: return raw text (truncated)
        return turnText.length > 1500 ? turnText.slice(0, 1500) + "\n..." : turnText;
      }

      /** Write a turn summary to the daily memory file and re-index. */
      async function writeTurnCapture(turnText: string, sessionId?: string): Promise<void> {
        try {
          if (turnText.length < 1) return;

          ensureDir(memoryDir);
          const today = new Date().toISOString().split("T")[0];
          const now = new Date().toTimeString().slice(0, 5);
          const memoryFile = join(memoryDir, `${today}.md`);

          // Write session heading if this is a new file
          if (!existsSync(memoryFile)) {
            writeFileSync(
              memoryFile,
              `# ${today}\n\n## Session ${now}\n\n`,
              "utf-8"
            );
          }

          // Summarize the turn via LLM, or fall back to raw text
          let summary: string;
          try {
            summary = await summarizeWithLLM(turnText);
          } catch {
            summary = turnText;
          }

          // Final quality gate: skip if summary is empty or all noise
          const cleanSummary = summary
            .split("\n")
            .filter((line) => !isNoiseLine(line))
            .join("\n")
            .trim();
          if (!cleanSummary) return;

          // Append to daily memory file with optional anchor
          let anchor = "";
          if (sessionId) {
            const transcriptPath = `${home}/.openclaw/agents/${agentId}/sessions/${sessionId}.jsonl`;
            anchor = `<!-- session:${sessionId} transcript:${transcriptPath} -->\n`;
          }
          const entry = `### ${now}\n${anchor}${cleanSummary}\n\n`;
          appendFileSync(memoryFile, entry, "utf-8");

          // Index in background (non-blocking, fire-and-forget)
          const cmd = await getMemsearchCmd();
          const collection = await getCollectionName();
          runCmd(
            [
              "bash", "-c",
              `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`,
            ],
            { timeoutMs: 60000 }
          ).catch((err: any) => {
            logger?.warn?.(`[memsearch] Index failed: ${err.message}`);
          });

          logger?.info?.(`[memsearch] Captured turn summary → ${memoryFile}`);
        } catch (e: any) {
          logger?.warn?.(`[memsearch] Capture failed: ${e.message}`);
        }
      }

      // Primary capture: agent_end fires every turn with full message history
      api.on("agent_end", async (event: any) => {
        const messages = event.messages || [];
        if (messages.length < 2) return;

        const lastTurn = extractLastTurn(messages);
        if (!lastTurn || lastTurn.length < 50) return;

        const sessionId = event.sessionId || "";
        writeTurnCapture(lastTurn, sessionId);
      });
    }

    // ----- Hook: session_start — ensure config + start indexing -----
    api.on("session_start", async () => {
      try {
        const cmd = await getMemsearchCmd();
        const collection = await getCollectionName();

        // Ensure default config (onnx provider, no API key needed)
        const configFile = join(home, ".memsearch", "config.toml");
        const localConfig = join(projectDir, ".memsearch.toml");
        if (!existsSync(configFile) && !existsSync(localConfig)) {
          try {
            await runCmd(
              ["bash", "-c", `${cmd} config set embedding.provider onnx`],
              { timeoutMs: 5000 }
            );
          } catch {
            /* ignore */
          }
        }

        // Run initial index in background (fire-and-forget)
        if (existsSync(memoryDir)) {
          runCmd(
            [
              "bash", "-c",
              `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`,
            ],
            { timeoutMs: 120000 }
          ).catch((err: any) => {
            logger?.warn?.(
              `[memsearch] Initial index failed: ${err.message}`
            );
          });
        }
      } catch (e: any) {
        logger?.warn?.(`[memsearch] session_start failed: ${e.message}`);
      }
    });

    // ----- CLI: memsearch subcommand -----
    api.registerCli(({ program }: any) => {
      const cmd = program
        .command("memsearch")
        .description("Semantic memory search and management");

      cmd
        .command("search <query>")
        .description("Search past memories")
        .option("-k, --top-k <n>", "Number of results", "5")
        .action(async (query: string, opts: any) => {
          try {
            const memsearch = await getMemsearchCmd();
            const collection = await getCollectionName();
            const result = await runCmd(
              [
                "bash", "-c",
                `${memsearch} search '${shellEscape(query)}' ` +
                  `--top-k ${opts.topK || 5} --collection ${collection}`,
              ],
              { timeoutMs: 30000 }
            );
            if (result.stdout) process.stdout.write(result.stdout);
            if (result.stderr) process.stderr.write(result.stderr);
          } catch (e: any) {
            console.error(`Search failed: ${e.message}`);
          }
        });

      cmd
        .command("index [directory]")
        .description("Index memory files")
        .action(async (directory?: string) => {
          const dir = directory || memoryDir;
          try {
            const memsearch = await getMemsearchCmd();
            const collection = await getCollectionName();
            const result = await runCmd(
              [
                "bash", "-c",
                `${memsearch} index '${shellEscape(dir)}' --collection ${collection}`,
              ],
              { timeoutMs: 120000 }
            );
            if (result.stdout) process.stdout.write(result.stdout);
            if (result.stderr) process.stderr.write(result.stderr);
          } catch (e: any) {
            console.error(`Index failed: ${e.message}`);
          }
        });

      cmd
        .command("status")
        .description("Show memsearch status")
        .action(async () => {
          const memsearch = await getMemsearchCmd();
          const collection = await getCollectionName();
          console.log(`Agent:       ${agentId}`);
          console.log(`Collection:  ${collection}`);
          console.log(`Memory dir:  ${memoryDir}`);
          console.log(`Provider:    ${pluginConfig.provider || "onnx"}`);
          console.log(`CLI:         ${memsearch}`);
          console.log(`AutoCapture: ${autoCapture}`);
          console.log(`AutoRecall:  ${autoRecall}`);
          try {
            const result = await runCmd(
              ["bash", "-c", `${memsearch} stats --collection ${collection}`],
              { timeoutMs: 10000 }
            );
            if (result.stdout) process.stdout.write(result.stdout);
          } catch {
            console.log("Stats: (unavailable — collection may not exist yet)");
          }
        });
    }, {
      descriptors: [{
        name: "memsearch",
        description: "Semantic memory search and management",
        hasSubcommands: true,
      }],
    });

    // Eager init (non-blocking) — log when ready
    getCollectionName()
      .then((name) => {
        logger?.info?.(
          `[memsearch] Plugin loaded. Collection: ${name}, ` +
            `autoCapture: ${autoCapture}, autoRecall: ${autoRecall}`
        );
      })
      .catch(() => {
        logger?.info?.(
          `[memsearch] Plugin loaded. autoCapture: ${autoCapture}, autoRecall: ${autoRecall}`
        );
      });
  },
};
