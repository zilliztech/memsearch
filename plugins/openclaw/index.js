import {
  readFileSync,
  appendFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  writeFileSync,
  unlinkSync,
  realpathSync
} from "node:fs";
import { join, dirname, isAbsolute, resolve, relative, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));
function getMemsearchDir(projectDir) {
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? explicit : join(projectDir, ".memsearch");
}
function getCollectionScopeDir(projectDir) {
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? explicit : projectDir;
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
function recentMemoryPreviewLines(content, maxLines) {
  const sections = [];
  let current = [];
  let hasBody = false;
  const flush = () => {
    if (current.length > 0 && hasBody) {
      sections.push(current);
    }
    current = [];
    hasBody = false;
  };
  for (const rawLine of content.split("\n")) {
    const line = rawLine.trimEnd();
    if (/^##\s/.test(line)) {
      flush();
      current = [line];
      continue;
    }
    if (/^#{3,4}\s/.test(line)) {
      current.push(line);
      continue;
    }
    if (line.startsWith("- ")) {
      current.push(line);
      hasBody = true;
    }
  }
  flush();
  return sections.flat().slice(-maxLines);
}
function getRecentMemories(memDir, count = 2, maxLinesPerFile = 30) {
  if (!existsSync(memDir)) return "";
  const files = readdirSync(memDir).filter((f) => f.endsWith(".md")).sort().slice(-count);
  if (files.length === 0) return "";
  const summary = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = recentMemoryPreviewLines(content, maxLinesPerFile);
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
function tailTruncate(text, maxChars) {
  if (text.length <= maxChars) return text;
  return `...(truncated to tail)
${text.slice(-maxChars)}`;
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
      parts.push(`[User]: ${text}`);
    } else if (role === "assistant") {
      parts.push(`[Assistant]: ${tailTruncate(text, 3e3)}`);
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
const SESSION_REFERENCE_PREFIX = "openclaw-session:";
async function loadTranscriptSdk() {
  try {
    return await import("openclaw/plugin-sdk/session-transcript-runtime");
  } catch (error) {
    const missing = ["ERR_PACKAGE_PATH_NOT_EXPORTED", "ERR_MODULE_NOT_FOUND", "MODULE_NOT_FOUND"].includes(error.code);
    if (missing && /(?:package 'openclaw'|openclaw\/plugin-sdk\/session-transcript-runtime|openclaw\/dist\/plugin-sdk\/(?:root-alias\.cjs\/)?session-transcript-runtime|session-transcript-runtime.*openclaw)/.test(error.message.split("\n")[0])) {
      return void 0;
    }
    throw error;
  }
}
async function loadSessionVisibilitySdk() {
  const [visibility, routing] = await Promise.all([
    import("openclaw/plugin-sdk/session-visibility"),
    import("openclaw/plugin-sdk/routing")
  ]);
  return { ...visibility, ...routing };
}
function resolveStateDir(runtime) {
  return runtime.state?.resolveStateDir?.() || process.env.OPENCLAW_STATE_DIR?.trim() || join(process.env.HOME || "~", ".openclaw");
}
function createTranscriptAccess(runtime, config = {}, loadSdk = loadTranscriptSdk, loadPolicy = loadSessionVisibilitySdk) {
  let sdkPromise;
  let policyPromise;
  const sdk = () => sdkPromise ??= loadSdk();
  const currentConfig = (ctx) => ctx.getRuntimeConfig?.() ?? ctx.runtimeConfig ?? ctx.config ?? config;
  function assertCaller(ctx, signal) {
    signal?.throwIfAborted();
    ctx?.assertInvocationCurrent?.();
    ctx?.assertMemoryAudienceCurrent?.();
    if (!ctx?.agentId || ctx.sandboxed || ctx.fsPolicy?.workspaceOnly || ctx.sessionKey?.split(":").includes("incognito")) {
      throw new Error("Transcript access requires an unsandboxed, identified session");
    }
  }
  function storePath(agentId, cfg) {
    const resolveStore = runtime.agent?.session?.resolveStorePath ?? runtime.channel?.session?.resolveStorePath;
    return resolveStore ? resolveStore(cfg?.session?.store, { agentId }) : join(resolveStateDir(runtime), "agents", agentId, "sessions", "sessions.json");
  }
  async function authorizeTarget(policy, scope, ctx, signal) {
    assertCaller(ctx, signal);
    const cfg = currentConfig(ctx);
    if (scope.agentId !== ctx.agentId || scope.storePath !== storePath(ctx.agentId, cfg)) {
      throw new Error("Transcript reference is outside the current profile/agent store");
    }
    for (const key of [ctx.sessionKey, scope.sessionKey]) {
      if (typeof key !== "string" || key.trim() !== key || policy.parseAgentSessionKey(key)?.agentId !== ctx.agentId || policy.isIncognitoSessionKey(key)) {
        throw new Error("Transcript access requires canonical, non-incognito session keys for the current agent");
      }
    }
    if (policy.isSubagentSessionKey(ctx.sessionKey) || policy.isAcpSessionKey(ctx.sessionKey) || cfg.session?.scope === "global") {
      throw new Error("Transcript access does not support this auxiliary/global session read scope");
    }
    const crossSession = scope.sessionKey !== ctx.sessionKey || scope.sessionId !== ctx.sessionId;
    if (crossSession && cfg.gateway?.roles) {
      throw new Error("Role-controlled cross-session transcript access requires host caller authorization");
    }
    const getEntry = runtime.agent?.session?.getSessionEntryAsync;
    if (typeof getEntry !== "function") throw new Error("Host cannot confirm target session metadata");
    const entry = await getEntry({
      agentId: ctx.agentId,
      sessionKey: scope.sessionKey,
      storePath: scope.storePath,
      readConsistency: "latest"
    });
    assertCaller(ctx, signal);
    if (!entry || entry.sessionId !== scope.sessionId || entry.incognito === true || entry.visibility !== void 0 && entry.visibility !== "shared") {
      throw new Error("Target session metadata is missing, changed, draft or incognito");
    }
    const access = policy.createSessionVisibilityRowChecker({
      action: "history",
      requesterAgentId: ctx.agentId,
      defaultAgentId: ctx.agentId,
      requesterSessionKey: ctx.sessionKey,
      mainSessionKey: policy.buildAgentMainSessionKey({ agentId: ctx.agentId, mainKey: cfg.session?.mainKey }),
      visibility: policy.resolveEffectiveSessionToolsVisibility({ cfg, sandboxed: ctx.sandboxed === true }),
      a2aPolicy: policy.createAgentToAgentPolicy(cfg, { sandboxed: ctx.sandboxed === true })
    }).check({
      key: scope.sessionKey,
      agentId: ctx.agentId,
      ownerSessionKey: entry.ownerSessionKey,
      spawnedBy: entry.spawnedBy,
      parentSessionKey: entry.parentSessionKey
    });
    if (!access.allowed) throw new Error(access.error || "Session history visibility denied");
  }
  async function checkedIdentity(reader, scope) {
    const identity = await reader.resolveSessionTranscriptIdentity(scope);
    if (identity.agentId !== scope.agentId || identity.sessionId !== scope.sessionId || identity.sessionKey !== scope.sessionKey) {
      throw new Error("Transcript session identity changed; refusing a different session");
    }
  }
  return {
    async capture(ctx) {
      if (!ctx.sessionId || !ctx.agentId) return "";
      assertCaller(ctx);
      if (!/^[a-zA-Z0-9_-]+$/.test(ctx.agentId) || !/^[a-zA-Z0-9_-]+$/.test(ctx.sessionId)) {
        throw new Error("Invalid transcript agent/session identity");
      }
      const agentId = ctx.agentId;
      const store = storePath(agentId, currentConfig(ctx));
      const scope = { agentId, sessionId: ctx.sessionId, sessionKey: ctx.sessionKey, storePath: store };
      const reader = await sdk();
      if (reader) {
        if (!scope.sessionKey) throw new Error("Transcript SDK requires hook context sessionKey");
        await checkedIdentity(reader, scope);
        assertCaller(ctx);
        const ref = new URL(`${SESSION_REFERENCE_PREFIX}//${encodeURIComponent(agentId)}/${encodeURIComponent(scope.sessionId)}`);
        ref.searchParams.set("sessionKey", scope.sessionKey);
        ref.searchParams.set("store", store);
        return ref.href;
      }
      const path = join(dirname(store), `${scope.sessionId}.jsonl`);
      return existsSync(path) ? path : "";
    },
    async read(reference, ctx, signal) {
      assertCaller(ctx, signal);
      const cfg = currentConfig(ctx);
      const currentStore = storePath(ctx.agentId, cfg);
      if (!reference.startsWith(SESSION_REFERENCE_PREFIX)) {
        const root = dirname(currentStore);
        const file = resolve(reference);
        const inside = (base, target) => {
          const rel = relative(base, target);
          return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
        };
        if (!isAbsolute(reference) || !inside(resolve(root), file) || !file.endsWith(".jsonl") || existsSync(file) && !inside(realpathSync(root), realpathSync(file))) {
          throw new Error("Legacy transcript is outside the current profile/agent store");
        }
        const modern = await sdk();
        assertCaller(ctx, signal);
        if (modern) {
          throw new Error("Use an SDK-generated session reference on this host; JSONL paths lack exact target key metadata");
        }
        if (basename(file) !== `${ctx.sessionId}.jsonl` && (["self", "tree"].includes(cfg.tools?.sessions?.visibility) || cfg.gateway?.roles)) {
          throw new Error("Legacy transcript cannot confirm access under restricted session policy");
        }
        return void 0;
      }
      const ref = new URL(reference);
      const scope = {
        agentId: decodeURIComponent(ref.hostname),
        sessionId: decodeURIComponent(ref.pathname.slice(1)),
        sessionKey: ref.searchParams.get("sessionKey"),
        storePath: ref.searchParams.get("store")
      };
      if (!scope.agentId || !scope.sessionId || !scope.sessionKey || !scope.storePath || !isAbsolute(scope.storePath) || ref.username || ref.password || ref.port || ref.hash) {
        throw new Error("Invalid OpenClaw session transcript reference");
      }
      if (scope.agentId !== ctx.agentId || scope.storePath !== currentStore) {
        throw new Error("Transcript reference is outside the current profile/agent store");
      }
      const reader = await sdk();
      if (!reader) throw new Error("This host does not provide the OpenClaw session transcript SDK");
      if (typeof reader.resolveSessionTranscriptIdentity !== "function" || typeof reader.readVisibleSessionTranscriptMessageEntries !== "function") {
        throw new Error("This host lacks the required session transcript SDK readers");
      }
      const policy = await (policyPromise ??= loadPolicy());
      await authorizeTarget(policy, scope, ctx, signal);
      await checkedIdentity(reader, scope);
      assertCaller(ctx, signal);
      const entries = await reader.readVisibleSessionTranscriptMessageEntries(scope);
      await authorizeTarget(policy, scope, ctx, signal);
      assertCaller(ctx, signal);
      const messages = entries.map((entry) => entry.message).filter((m) => m?.role === "user" || m?.role === "assistant");
      const lastUser = messages.findLastIndex((m) => m.role === "user");
      if (lastUser < 0) return "(no user message found)";
      const lines = messages.slice(lastUser).map((m) => {
        const text = typeof m.content === "string" ? m.content : (m.content || []).filter((block) => block.type === "text").map((block) => block.text || "").join("\n");
        return text.trim() ? `[${m.role === "user" ? "User" : "Assistant"}]: ${text}` : "";
      }).filter(Boolean);
      const output = ["=== Transcript of a conversation between User and an AI assistant ===", ...lines].join("\n");
      return output.length > 32e3 ? `${output.slice(0, 32e3)}
[Transcript output truncated]` : output;
    }
  };
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
    const transcripts = createTranscriptAccess(api.runtime, api.config);
    async function runCmd(argv, opts) {
      return api.runtime.system.runCommandWithTimeout(argv, opts || {});
    }
    function commandFailure(action, result) {
      if (result.code === 0) return null;
      const detail = (result.stderr || result.stdout || "unknown error").trim();
      return `${action} failed (exit ${result.code ?? "unknown"}): ${detail}`;
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
    async function getMemsearchConfigValue(key, cwd = projectDir) {
      const cmd = await getMemsearchCmd();
      const r = await runCmd(
        ["bash", "-c", `${cmd} config get '${shellEscape(key)}'`],
        { timeoutMs: 5e3, cwd }
      );
      return r.stdout?.trim() || "";
    }
    async function getSkillCandidateHint(cwd) {
      try {
        const cmd = await getMemsearchCmd();
        const r = await runCmd(
          [
            "bash",
            "-c",
            `MEMSEARCH_DIR='${shellEscape(getMemsearchDir(cwd))}' ${cmd} skills status --hint`
          ],
          { timeoutMs: 5e3, cwd }
        );
        if (r.code !== 0) return "";
        return r.stdout?.trim().split("\n")[0] || "";
      } catch {
        return "";
      }
    }
    async function wakeMaintenance(cwd = projectDir) {
      try {
        const runner = join(PLUGIN_DIR, "scripts", "maintenance-runner.py");
        runCmd(
          [
            "bash",
            "-c",
            `python3 '${shellEscape(runner)}' --platform openclaw --project-dir '${shellEscape(cwd)}' --memsearch-dir '${shellEscape(getMemsearchDir(cwd))}'`
          ],
          {
            timeoutMs: 12e4,
            cwd,
            env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" })
          }
        ).catch(() => {
        });
      } catch {
      }
    }
    const collections = /* @__PURE__ */ new Map();
    async function requireDefaultCollectionSupport(cwd, collection) {
      const cmd = await getMemsearchCmd();
      const r = await runCmd(
        [
          "bash",
          "-c",
          `${cmd} config get milvus.collection --default-collection '${shellEscape(collection)}'`
        ],
        { timeoutMs: 5e3, cwd }
      );
      if (r.code !== 0) {
        throw new Error(
          "Installed memsearch CLI is incompatible with this plugin; --default-collection support is required. Upgrade memsearch core and the plugin together."
        );
      }
    }
    async function getCollectionName(cwd = projectDir) {
      const scopeDir = getCollectionScopeDir(cwd);
      const key = JSON.stringify([cwd, scopeDir]);
      if (!collections.has(key)) collections.set(key, (async () => {
        let collection = "ms_openclaw_default";
        const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
        try {
          const r = await runCmd(["bash", script, scopeDir], { timeoutMs: 5e3 });
          if (r.code === 0 && r.stdout?.trim()) {
            collection = r.stdout.trim();
          }
        } catch {
        }
        await requireDefaultCollectionSupport(cwd, collection);
        return collection;
      })().catch((error) => {
        collections.delete(key);
        throw error;
      }));
      return collections.get(key);
    }
    let agentId = "main";
    let projectDir = join(resolveStateDir(api.runtime), "workspace");
    let memoryDir = getMemoryDir(projectDir);
    function updateAgentContext(ctx) {
      const newId = ctx?.agentId || agentId;
      const newWorkspace = ctx?.workspaceDir || api.runtime.agent?.resolveAgentWorkspaceDir?.(api.config, newId);
      if (newId !== agentId || newWorkspace && newWorkspace !== projectDir) {
        agentId = newId;
        projectDir = newWorkspace || join(resolveStateDir(api.runtime), agentId === "main" ? "workspace" : `workspace-${agentId}`);
        memoryDir = getMemoryDir(projectDir);
        logger?.info?.(
          `[memsearch] Agent context updated: ${agentId}, dir: ${projectDir}`
        );
      }
    }
    api.registerTool(
      (ctx) => {
        updateAgentContext(ctx);
        const toolProjectDir = projectDir;
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
              const collection = await getCollectionName(toolProjectDir);
              const result = await runCmd(
                [
                  "bash",
                  "-c",
                  `${cmd} search '${shellEscape(params.query)}' --top-k ${topK} --json-output --default-collection ${collection}`
                ],
                { timeoutMs: 3e4, cwd: toolProjectDir }
              );
              const failure = commandFailure("Search", result);
              if (failure) {
                return { content: [{ type: "text", text: failure }] };
              }
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
        const toolProjectDir = projectDir;
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
              const collection = await getCollectionName(toolProjectDir);
              const result = await runCmd(
                [
                  "bash",
                  "-c",
                  `${cmd} expand '${shellEscape(params.chunk_hash)}' --default-collection ${collection}`
                ],
                { timeoutMs: 15e3, cwd: toolProjectDir }
              );
              const failure = commandFailure("Expand", result);
              if (failure) {
                return { content: [{ type: "text", text: failure }] };
              }
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
          description: "Retrieve the original conversation from a past session transcript. Use after memory_get when the expanded result contains a transcript anchor (<!-- session:UUID transcript:REFERENCE -->). Pass its exact reference unchanged. Returns the formatted dialogue with [User] and [Assistant] labels.",
          parameters: {
            type: "object",
            properties: {
              transcript_path: {
                type: "string",
                description: "Exact transcript reference from the anchor: openclaw-session URI or legacy .jsonl path"
              }
            },
            required: ["transcript_path"]
          },
          async execute(_toolCallId, params, signal) {
            try {
              const transcript = await transcripts.read(params.transcript_path, ctx, signal);
              if (transcript !== void 0) {
                return { content: [{ type: "text", text: transcript }] };
              }
              const scriptPath = join(PLUGIN_DIR, "scripts", "parse-transcript.sh");
              const result = await runCmd(
                ["bash", scriptPath, params.transcript_path],
                { timeoutMs: 15e3 }
              );
              signal?.throwIfAborted();
              ctx?.assertInvocationCurrent?.();
              ctx?.assertMemoryAudienceCurrent?.();
              const failure = commandFailure("Transcript", result);
              if (failure) return { content: [{ type: "text", text: failure }] };
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
      api.on("before_prompt_build", async (_event, ctx) => {
        updateAgentContext(ctx);
        const promptProjectDir = projectDir;
        const promptMemoryDir = memoryDir;
        try {
          const context = getRecentMemories(promptMemoryDir);
          const skillHint = await getSkillCandidateHint(promptProjectDir);
          const blocks = [context, skillHint].filter(Boolean);
          if (blocks.length > 0) {
            return { prependContext: blocks.join("\n\n") };
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
      async function summarizeWithLLM(turnText, captureProjectDir) {
        const agentName = "OpenClaw";
        let systemPrompt = "";
        let customPromptFile = "";
        try {
          customPromptFile = await getMemsearchConfigValue("prompts.summarize", captureProjectDir);
        } catch {
        }
        if (customPromptFile && !isAbsolute(customPromptFile)) {
          customPromptFile = join(captureProjectDir, customPromptFile);
        }
        if (customPromptFile && existsSync(customPromptFile)) {
          systemPrompt = readFileSync(customPromptFile, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
        } else {
          const builtinPath = join(PLUGIN_DIR, "prompts", "summarize.txt");
          if (existsSync(builtinPath)) {
            systemPrompt = readFileSync(builtinPath, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
          } else {
            systemPrompt = "You are a third-person note-taker. Summarize the transcript as 2-10 bullet points. Write in third person. Mandatory language rule: write every bullet in the same primary language as the [User] text. If User mixes languages, use the dominant user-facing language. Do NOT answer User's question. Output ONLY bullet points.";
          }
        }
        let summarizeModel = "";
        try {
          summarizeModel = await getMemsearchConfigValue("plugins.openclaw.summarize.model", captureProjectDir);
        } catch {
        }
        let summarizeProvider = "";
        try {
          summarizeProvider = await getMemsearchConfigValue("plugins.openclaw.summarize.provider", captureProjectDir);
        } catch {
        }
        if (summarizeProvider && summarizeProvider !== "native") {
          try {
            const cmd = await getMemsearchCmd();
            const tmpInput = `/tmp/memsearch-summarize-input-${randomUUID()}.txt`;
            writeFileSync(tmpInput, turnText, "utf-8");
            const shellCmd = `cat ${JSON.stringify(tmpInput)} | ${cmd} summarize --plugin openclaw --agent-name OpenClaw`;
            const result = await runCmd(["bash", "-c", shellCmd], {
              timeoutMs: 6e4,
              cwd: captureProjectDir,
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
          const tmpFile = `/tmp/memsearch-summarize-${randomUUID()}.txt`;
          const modelArg = summarizeModel ? ` --model '${shellEscape(summarizeModel)}'` : "";
          const shellCmd = `openclaw agent --local --session-id ${randomUUID()}${modelArg} -m '${shellEscape(msgText)}' > ${JSON.stringify(tmpFile)} 2>/dev/null`;
          await runCmd(["bash", "-c", shellCmd], {
            timeoutMs: 6e4,
            cwd: captureProjectDir,
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
        return tailTruncate(turnText, 1500);
      }
      async function writeTurnCapture(turnText, ctx, provenance) {
        try {
          if (turnText.length < 1) return;
          const captureMemoryDir = ctx.memoryDir;
          let anchor = "";
          try {
            const reference = await provenance;
            if (reference) anchor = `<!-- session:${ctx.sessionId} transcript:${reference} -->
`;
          } catch (error) {
            logger?.warn?.(`[memsearch] Transcript provenance unavailable: ${error.message}`);
          }
          ensureDir(captureMemoryDir);
          const today = (/* @__PURE__ */ new Date()).toISOString().split("T")[0];
          const now = (/* @__PURE__ */ new Date()).toTimeString().slice(0, 5);
          const memoryFile = join(captureMemoryDir, `${today}.md`);
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
            summary = await summarizeWithLLM(turnText, ctx.projectDir);
          } catch {
            summary = turnText;
          }
          const cleanSummary = summary.split("\n").filter((line) => !isNoiseLine(line)).join("\n").trim();
          if (!cleanSummary) return;
          const entry = `### ${now}
${anchor}${cleanSummary}

`;
          ctx.assertInvocationCurrent?.();
          ctx.assertMemoryAudienceCurrent?.();
          appendFileSync(memoryFile, entry, "utf-8");
          const cmd = await getMemsearchCmd();
          const collection = await getCollectionName(ctx.projectDir);
          runCmd(
            [
              "bash",
              "-c",
              `${cmd} index '${shellEscape(captureMemoryDir)}' --default-collection ${collection}`
            ],
            { timeoutMs: 6e4, cwd: ctx.projectDir }
          ).catch((err) => {
            logger?.warn?.(`[memsearch] Index failed: ${err.message}`);
          });
          logger?.info?.(`[memsearch] Captured turn summary \u2192 ${memoryFile}`);
        } catch (e) {
          logger?.warn?.(`[memsearch] Capture failed: ${e.message}`);
        }
      }
      api.on("agent_end", async (event, ctx) => {
        if (event.success === false || !ctx?.agentId || ctx.sandboxed || ctx.sessionKey?.split(":").includes("incognito") || ctx.memoryAudience && (ctx.memoryAudience.kind !== "owner-private" || ctx.memoryAudience.agentId !== ctx.agentId)) return;
        ctx.assertMemoryAudienceCurrent?.();
        updateAgentContext(ctx);
        const captureContext = Object.freeze({
          ...ctx,
          agentId: ctx?.agentId,
          projectDir,
          memoryDir,
          sessionId: ctx?.sessionId || "",
          sessionKey: ctx?.sessionKey
        });
        const messages = event.messages || [];
        if (messages.length < 2) return;
        const lastTurn = extractLastTurn(messages);
        if (!lastTurn || lastTurn.length < 50) return;
        const provenance = transcripts.capture(captureContext).catch((error) => {
          logger?.warn?.(`[memsearch] Transcript provenance unavailable: ${error.message}`);
          return "";
        });
        let summarizeEnabled = "true";
        try {
          summarizeEnabled = await getMemsearchConfigValue("plugins.openclaw.summarize.enabled", captureContext.projectDir);
        } catch {
        }
        if (summarizeEnabled === "false") {
          wakeMaintenance(captureContext.projectDir).catch(() => {
          });
          return;
        }
        await writeTurnCapture(lastTurn, captureContext, provenance);
        wakeMaintenance(captureContext.projectDir).catch(() => {
        });
      });
    }
    api.on("session_start", async (_event, ctx) => {
      updateAgentContext(ctx);
      const sessionProjectDir = projectDir;
      const sessionMemoryDir = memoryDir;
      try {
        const cmd = await getMemsearchCmd();
        const collection = await getCollectionName(sessionProjectDir);
        const configFile = join(home, ".memsearch", "config.toml");
        const localConfig = join(sessionProjectDir, ".memsearch.toml");
        if (!existsSync(configFile) && !existsSync(localConfig)) {
          try {
            await runCmd(
              ["bash", "-c", `${cmd} config set embedding.provider onnx`],
              { timeoutMs: 5e3, cwd: sessionProjectDir }
            );
          } catch {
          }
        }
        if (existsSync(sessionMemoryDir)) {
          runCmd(
            [
              "bash",
              "-c",
              `${cmd} index '${shellEscape(sessionMemoryDir)}' --default-collection ${collection}`
            ],
            { timeoutMs: 12e4, cwd: sessionProjectDir }
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
              `${memsearch} search '${shellEscape(query)}' --top-k ${opts.topK || 5} --default-collection ${collection}`
            ],
            { timeoutMs: 3e4, cwd: projectDir }
          );
          const failure = commandFailure("Search", result);
          if (failure) throw new Error(failure);
          if (result.stdout) process.stdout.write(result.stdout);
          if (result.stderr) process.stderr.write(result.stderr);
        } catch (e) {
          const message = String(e.message).startsWith("Search failed") ? String(e.message) : `Search failed: ${e.message}`;
          console.error(message);
          if (message === e.message) throw e;
          throw new Error(message);
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
              `${memsearch} index '${shellEscape(dir)}' --default-collection ${collection}`
            ],
            { timeoutMs: 12e4, cwd: projectDir }
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
        let effectiveCollection = collection;
        try {
          const result = await runCmd(
            [
              "bash",
              "-c",
              `${memsearch} config get milvus.collection --default-collection '${shellEscape(collection)}'`
            ],
            { timeoutMs: 1e4, cwd: projectDir }
          );
          effectiveCollection = result.stdout.trim() || collection;
        } catch {
        }
        console.log(`Agent:       ${agentId}`);
        console.log(`Collection:  ${effectiveCollection}`);
        console.log(`Memory dir:  ${memoryDir}`);
        console.log(`Provider:    ${pluginConfig.provider || "onnx"}`);
        console.log(`CLI:         ${memsearch}`);
        console.log(`AutoCapture: ${autoCapture}`);
        console.log(`AutoRecall:  ${autoRecall}`);
        try {
          const result = await runCmd(
            ["bash", "-c", `${memsearch} stats --default-collection ${collection}`],
            { timeoutMs: 1e4, cwd: projectDir }
          );
          const failure = commandFailure("Stats", result);
          if (failure) console.log(failure);
          else if (result.stdout) process.stdout.write(result.stdout);
        } catch (e) {
          console.log(`Stats failed: ${e.message}`);
        }
      });
    }, {
      commands: ["memsearch"],
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
    }).catch((error) => {
      logger?.error?.(
        `[memsearch] Plugin initialization failed: ${error.message}`
      );
    });
  }
};
export {
  createTranscriptAccess,
  index_default as default,
  getCollectionScopeDir,
  getMemsearchDir
};
