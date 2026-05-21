import {
  readFileSync,
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  writeFileSync,
  unlinkSync
} from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
function getMemsearchDir(projectDir) {
  return join(projectDir, ".memsearch");
}
function getMemoryDir(projectDir) {
  return join(getMemsearchDir(projectDir), "memory");
}
function ensureDir(dir) {
  if (!existsSync(dir)) {
    mkdirSync(dir, { recursive: true });
  }
  return dir;
}
function getRecentMemories(memDir, count = 2, maxLinesPerFile = 30) {
  if (!existsSync(memDir)) return "";
  const files = readdirSync(memDir).filter((f) => f.endsWith(".md")).sort().slice(-count);
  if (files.length === 0) return "";
  const summary = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = content.split("\n").filter((l) => /^#{2,4}\s/.test(l) || l.startsWith("- ")).slice(0, maxLinesPerFile);
      if (lines.length > 0) {
        summary.push(`[${file}]`, ...lines);
      }
    } catch {
    }
  }
  if (summary.length === 0) {
    return `You have ${files.length} past memory file(s). Use the memory_search tool when the user's question could benefit from historical context.`;
  }
  return `Recent memories (use memory_search for full search):
${summary.join("\n")}`;
}
function shellEscape(s) {
  return s.replace(/'/g, "'\\''");
}
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
  /^\[\[reply_to_\w+\]\]/
];
function isNoiseLine(line) {
  const trimmed = line.trim();
  return NOISE_PATTERNS.some((pat) => pat.test(trimmed));
}
function extractText(content) {
  let raw;
  if (typeof content === "string") {
    raw = content;
  } else if (Array.isArray(content)) {
    raw = content.filter((c) => c.type === "text").map((c) => c.text || "").join("\n");
  } else {
    return "";
  }
  return raw.split("\n").filter((line) => !isNoiseLine(line)).join("\n").trim();
}
function stripInjectedContext(text) {
  let cleaned = text.replace(/Recent memories \(use memory_search for full search\):[\s\S]*?(?=\n\n(?!\s|-)|\n*$)/g, "");
  cleaned = cleaned.replace(/Conversation info \(untrusted metadata\):[\s\S]*?(?=\n\n(?!\s|")|\n*$)/g, "");
  cleaned = cleaned.replace(/\[message_id:.*?\]\n/g, "");
  return cleaned.trim();
}
function extractLastTurn(messages) {
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
  const parts = [];
  for (let i = lastUserIdx; i < messages.length; i++) {
    const msg = messages[i];
    const role = msg?.role || msg?.message?.role;
    const content = msg?.content || msg?.message?.content;
    let text = extractText(content);
    if (!text || text.length < 5) continue;
    if (role === "user") {
      text = stripInjectedContext(text);
      if (!text || text.length < 5) continue;
      parts.push(`[Human]: ${text}`);
    } else if (role === "assistant") {
      parts.push(`[Assistant]: ${text.slice(0, 3e3)}`);
    }
  }
  if (parts.length === 0) return null;
  return parts.join("\n\n");
}
function envWithOverrides(overrides) {
  const env = {};
  for (const [k, v] of Object.entries(process.env)) {
    if (v !== void 0) env[k] = v;
  }
  return { ...env, ...overrides };
}
var index_default = {
  id: "memsearch",
  name: "memsearch",
  description: "Semantic memory search \u2014 remembers what you worked on across sessions",
  kind: "memory",
  register(api) {
    const pluginConfig = api.pluginConfig || {};
    const isChildProcess = !!process.env.MEMSEARCH_NO_WATCH;
    const autoCapture = pluginConfig.autoCapture !== false && !isChildProcess;
    const autoRecall = pluginConfig.autoRecall !== false && !isChildProcess;
    const logger = api.logger;
    const home = process.env.HOME || "~";
    async function runCmd(argv, opts) {
      return api.runtime.system.runCommandWithTimeout(argv, opts || {});
    }
    let _memsearchCmd = null;
    async function getMemsearchCmd() {
      if (_memsearchCmd) return _memsearchCmd;
      const h = process.env.HOME || "";
      try {
        const r = await runCmd(["which", "memsearch"], { timeoutMs: 5e3 });
        if (r.code === 0) {
          _memsearchCmd = "memsearch";
          return _memsearchCmd;
        }
      } catch {
      }
      const uvxPath = join(h, ".local", "bin", "uvx");
      if (existsSync(uvxPath)) {
        _memsearchCmd = `${uvxPath} --from 'memsearch[onnx]' memsearch`;
        return _memsearchCmd;
      }
      try {
        const r = await runCmd(["which", "uvx"], { timeoutMs: 5e3 });
        if (r.code === 0) {
          _memsearchCmd = "uvx --from 'memsearch[onnx]' memsearch";
          return _memsearchCmd;
        }
      } catch {
      }
      _memsearchCmd = "memsearch";
      return _memsearchCmd;
    }
    async function getMemsearchConfigValue(key) {
      const cmd = await getMemsearchCmd();
      const r = await runCmd(
        ["bash", "-c", `${cmd} config get '${shellEscape(key)}'`],
        { timeoutMs: 5e3 }
      );
      return r.stdout?.trim() || "";
    }
    let _collectionNameFor = "";
    let _collectionName = "ms_openclaw_default";
    async function getCollectionName() {
      if (_collectionNameFor === projectDir) return _collectionName;
      const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
      try {
        const r = await runCmd(["bash", script, projectDir], { timeoutMs: 5e3 });
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
    let agentId = "main";
    let projectDir = join(home, ".openclaw", "workspace");
    let memsearchDir = join(projectDir, ".memsearch");
    let memoryDir = join(memsearchDir, "memory");
    function updateAgentContext(ctx) {
      const newId = ctx?.agentId;
      const newWorkspace = ctx?.workspaceDir;
      if (newId && (newId !== agentId || newWorkspace && newWorkspace !== projectDir)) {
        agentId = newId;
        projectDir = newWorkspace || join(home, ".openclaw", `workspace-${agentId}`);
        memsearchDir = join(projectDir, ".memsearch");
        memoryDir = join(memsearchDir, "memory");
        _collectionNameFor = "";
        logger?.info?.(
          `[memsearch] Agent context updated: ${agentId}, dir: ${projectDir}`
        );
      }
    }
    api.registerTool(
      (ctx) => {
        updateAgentContext(ctx);
        return {
          name: "memory_search",
          label: "Memory Search",
          description: "Search past conversation memories using memsearch semantic search. Returns relevant chunks from past sessions, including dates, topics discussed, and code referenced. Powered by Milvus hybrid search (BM25 + dense vectors + RRF reranking).",
          parameters: {
            type: "object",
            properties: {
              query: {
                type: "string",
                description: "Search query \u2014 describe what you want to find"
              },
              top_k: {
                type: "number",
                description: "Number of results to return (default: 5)"
              }
            },
            required: ["query"]
          },
          async execute(_toolCallId, params) {
            const topK = params.top_k || 5;
            try {
              const cmd = await getMemsearchCmd();
              const collection = await getCollectionName();
              const result = await runCmd(
                [
                  "bash",
                  "-c",
                  `${cmd} search '${shellEscape(params.query)}' --top-k ${topK} --json-output --collection ${collection}`
                ],
                { timeoutMs: 3e4 }
              );
              const output = result.stdout || result.stderr || "No results";
              return { content: [{ type: "text", text: output }] };
            } catch (e) {
              return {
                content: [
                  { type: "text", text: `Search failed: ${e.message}` }
                ]
              };
            }
          }
        };
      },
      { name: "memory_search" }
    );
    api.registerTool(
      (ctx) => {
        updateAgentContext(ctx);
        return {
          name: "memory_get",
          label: "Memory Get",
          description: "Expand a memory chunk to see the full markdown section with surrounding context. Use after memory_search to get details about a specific result.",
          parameters: {
            type: "object",
            properties: {
              chunk_hash: {
                type: "string",
                description: "The chunk_hash from a search result to expand"
              }
            },
            required: ["chunk_hash"]
          },
          async execute(_toolCallId, params) {
            try {
              const cmd = await getMemsearchCmd();
              const collection = await getCollectionName();
              const result = await runCmd(
                [
                  "bash",
                  "-c",
                  `${cmd} expand '${shellEscape(params.chunk_hash)}' --collection ${collection}`
                ],
                { timeoutMs: 15e3 }
              );
              const output = result.stdout || result.stderr || "No content";
              return { content: [{ type: "text", text: output }] };
            } catch (e) {
              return {
                content: [
                  { type: "text", text: `Expand failed: ${e.message}` }
                ]
              };
            }
          }
        };
      },
      { name: "memory_get" }
    );
    api.registerTool(
      (ctx) => {
        updateAgentContext(ctx);
        return {
          name: "memory_transcript",
          label: "Memory Transcript",
          description: "Retrieve the original conversation from a past session transcript. Use after memory_get when the expanded result contains a transcript anchor (<!-- session:UUID transcript:PATH -->). Returns the formatted dialogue with [Human] and [Assistant] labels.",
          parameters: {
            type: "object",
            properties: {
              transcript_path: {
                type: "string",
                description: "Path to the .jsonl transcript file (from the anchor comment)"
              }
            },
            required: ["transcript_path"]
          },
          async execute(_toolCallId, params) {
            try {
              const scriptPath = join(PLUGIN_DIR, "scripts", "parse-transcript.sh");
              const result = await runCmd(
                ["bash", scriptPath, params.transcript_path],
                { timeoutMs: 15e3 }
              );
              const output = result.stdout?.trim() || result.stderr || "No transcript content";
              return { content: [{ type: "text", text: output }] };
            } catch (e) {
              return {
                content: [
                  { type: "text", text: `Transcript parse failed: ${e.message}` }
                ]
              };
            }
          }
        };
      },
      { name: "memory_transcript" }
    );
    if (autoRecall) {
      api.on("before_agent_start", async () => {
        try {
          const context = getRecentMemories(memoryDir);
          if (context) {
            return { prependContext: context };
          }
        } catch (e) {
          logger?.warn?.(
            `[memsearch] Failed to inject memories: ${e.message}`
          );
        }
        return {};
      });
    }
    if (autoCapture) {
      async function summarizeWithLLM(turnText) {
        const agentName = "OpenClaw";
        let systemPrompt = "";
        let customPromptFile = "";
        try {
          customPromptFile = await getMemsearchConfigValue("prompts.summarize");
        } catch {
        }
        if (customPromptFile && existsSync(customPromptFile)) {
          systemPrompt = readFileSync(customPromptFile, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
        } else {
          const builtinPath = join(PLUGIN_DIR, "prompts", "summarize.txt");
          if (existsSync(builtinPath)) {
            systemPrompt = readFileSync(builtinPath, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
          } else {
            systemPrompt = "You are a third-person note-taker. Summarize the transcript as 2-6 bullet points. Write in third person. Output ONLY bullet points.";
          }
        }
        let summarizeModel = "";
        try {
          summarizeModel = await getMemsearchConfigValue("plugins.openclaw.summarize.model");
        } catch {
        }
        let summarizeProvider = "";
        try {
          summarizeProvider = await getMemsearchConfigValue("plugins.openclaw.summarize.provider");
        } catch {
        }
        if (summarizeProvider && summarizeProvider !== "native") {
          try {
            const cmd = await getMemsearchCmd();
            const tmpInput = `/tmp/memsearch-summarize-input-${Date.now()}.txt`;
            writeFileSync(tmpInput, turnText, "utf-8");
            const shellCmd = `cat ${JSON.stringify(tmpInput)} | ${cmd} summarize --plugin openclaw --agent-name OpenClaw`;
            const result = await runCmd(["bash", "-c", shellCmd], {
              timeoutMs: 6e4,
              env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" })
            });
            try {
              unlinkSync(tmpInput);
            } catch {
            }
            const output = (result.stdout || "").trim();
            if (output) {
              return output;
            }
          } catch {
          }
        }
        try {
          const msgText = `${systemPrompt}

Transcript:
${turnText}`;
          const tmpFile = `/tmp/memsearch-summarize-${Date.now()}.txt`;
          const modelArg = summarizeModel ? ` --model ${JSON.stringify(summarizeModel)}` : "";
          const shellCmd = `openclaw agent --local --session-id memsearch-summarize${modelArg} -m ${JSON.stringify(msgText)} > ${JSON.stringify(tmpFile)} 2>/dev/null`;
          await runCmd(["bash", "-c", shellCmd], {
            timeoutMs: 6e4,
            env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" })
          });
          if (existsSync(tmpFile)) {
            const raw = readFileSync(tmpFile, "utf-8");
            try {
              unlinkSync(tmpFile);
            } catch {
            }
            const output = raw.split("\n").filter((line) => !line.startsWith("[plugins]") && !line.startsWith("[agents]")).join("\n").trim();
            if (output && output.includes("- ")) {
              return output;
            }
          }
        } catch {
        }
        return turnText.length > 1500 ? turnText.slice(0, 1500) + "\n..." : turnText;
      }
      async function writeTurnCapture(turnText, sessionId) {
        try {
          if (turnText.length < 1) return;
          ensureDir(memoryDir);
          const today = (/* @__PURE__ */ new Date()).toISOString().split("T")[0];
          const now = (/* @__PURE__ */ new Date()).toTimeString().slice(0, 5);
          const memoryFile = join(memoryDir, `${today}.md`);
          if (!existsSync(memoryFile)) {
            writeFileSync(
              memoryFile,
              `# ${today}

## Session ${now}

`,
              "utf-8"
            );
          }
          let summary;
          try {
            summary = await summarizeWithLLM(turnText);
          } catch {
            summary = turnText;
          }
          const cleanSummary = summary.split("\n").filter((line) => !isNoiseLine(line)).join("\n").trim();
          if (!cleanSummary) return;
          let anchor = "";
          if (sessionId) {
            const transcriptPath = `${home}/.openclaw/agents/${agentId}/sessions/${sessionId}.jsonl`;
            anchor = `<!-- session:${sessionId} transcript:${transcriptPath} -->
`;
          }
          const entry = `### ${now}
${anchor}${cleanSummary}

`;
          appendFileSync(memoryFile, entry, "utf-8");
          const cmd = await getMemsearchCmd();
          const collection = await getCollectionName();
          runCmd(
            [
              "bash",
              "-c",
              `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`
            ],
            { timeoutMs: 6e4 }
          ).catch((err) => {
            logger?.warn?.(`[memsearch] Index failed: ${err.message}`);
          });
          logger?.info?.(`[memsearch] Captured turn summary \u2192 ${memoryFile}`);
        } catch (e) {
          logger?.warn?.(`[memsearch] Capture failed: ${e.message}`);
        }
      }
      api.on("agent_end", async (event) => {
        const messages = event.messages || [];
        if (messages.length < 2) return;
        const lastTurn = extractLastTurn(messages);
        if (!lastTurn || lastTurn.length < 50) return;
        const sessionId = event.sessionId || "";
        writeTurnCapture(lastTurn, sessionId);
      });
    }
    api.on("session_start", async () => {
      try {
        const cmd = await getMemsearchCmd();
        const collection = await getCollectionName();
        const configFile = join(home, ".memsearch", "config.toml");
        const localConfig = join(projectDir, ".memsearch.toml");
        if (!existsSync(configFile) && !existsSync(localConfig)) {
          try {
            await runCmd(
              ["bash", "-c", `${cmd} config set embedding.provider onnx`],
              { timeoutMs: 5e3 }
            );
          } catch {
          }
        }
        if (existsSync(memoryDir)) {
          runCmd(
            [
              "bash",
              "-c",
              `${cmd} index '${shellEscape(memoryDir)}' --collection ${collection}`
            ],
            { timeoutMs: 12e4 }
          ).catch((err) => {
            logger?.warn?.(
              `[memsearch] Initial index failed: ${err.message}`
            );
          });
        }
      } catch (e) {
        logger?.warn?.(`[memsearch] session_start failed: ${e.message}`);
      }
    });
    api.registerCli(({ program }) => {
      const cmd = program.command("memsearch").description("Semantic memory search and management");
      cmd.command("search <query>").description("Search past memories").option("-k, --top-k <n>", "Number of results", "5").action(async (query, opts) => {
        try {
          const memsearch = await getMemsearchCmd();
          const collection = await getCollectionName();
          const result = await runCmd(
            [
              "bash",
              "-c",
              `${memsearch} search '${shellEscape(query)}' --top-k ${opts.topK || 5} --collection ${collection}`
            ],
            { timeoutMs: 3e4 }
          );
          if (result.stdout) process.stdout.write(result.stdout);
          if (result.stderr) process.stderr.write(result.stderr);
        } catch (e) {
          console.error(`Search failed: ${e.message}`);
        }
      });
      cmd.command("index [directory]").description("Index memory files").action(async (directory) => {
        const dir = directory || memoryDir;
        try {
          const memsearch = await getMemsearchCmd();
          const collection = await getCollectionName();
          const result = await runCmd(
            [
              "bash",
              "-c",
              `${memsearch} index '${shellEscape(dir)}' --collection ${collection}`
            ],
            { timeoutMs: 12e4 }
          );
          if (result.stdout) process.stdout.write(result.stdout);
          if (result.stderr) process.stderr.write(result.stderr);
        } catch (e) {
          console.error(`Index failed: ${e.message}`);
        }
      });
      cmd.command("status").description("Show memsearch status").action(async () => {
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
            { timeoutMs: 1e4 }
          );
          if (result.stdout) process.stdout.write(result.stdout);
        } catch {
          console.log("Stats: (unavailable \u2014 collection may not exist yet)");
        }
      });
    }, {
      descriptors: [{
        name: "memsearch",
        description: "Semantic memory search and management",
        hasSubcommands: true
      }]
    });
    getCollectionName().then((name) => {
      logger?.info?.(
        `[memsearch] Plugin loaded. Collection: ${name}, autoCapture: ${autoCapture}, autoRecall: ${autoRecall}`
      );
    }).catch(() => {
      logger?.info?.(
        `[memsearch] Plugin loaded. autoCapture: ${autoCapture}, autoRecall: ${autoRecall}`
      );
    });
  }
};
export {
  index_default as default
};
