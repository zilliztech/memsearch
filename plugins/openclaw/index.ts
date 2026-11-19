/**
 * memsearch OpenClaw plugin — semantic memory search across sessions.
 *
 * Registers:
 * - memory_search tool: semantic search over past memories
 * - memory_get tool: expand a chunk to full context
 * - memory_transcript tool: parse original conversation from JSONL transcript
 * - before_prompt_build hook: inject recent memories as cold-start context
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
  unlinkSync,
  realpathSync,
} from "node:fs";
import { join, dirname, isAbsolute, resolve, relative, basename } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url));

// ---------------------------------------------------------------------------
// Helpers (no external process calls — those live inside register())
// ---------------------------------------------------------------------------

export function getMemsearchDir(projectDir: string): string {
  // Honor MEMSEARCH_DIR for shared/global scope — matches claude-code/codex behavior.
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? explicit : join(projectDir, ".memsearch");
}

export function getCollectionScopeDir(projectDir: string): string {
  const explicit = process.env.MEMSEARCH_DIR?.trim();
  return explicit ? explicit : projectDir;
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
 * Summarize the N most recent daily .md files for cold-start context.
 * Extracts recent non-empty session sections so empty SessionStart headings
 * do not crowd out useful context.
 */
function recentMemoryPreviewLines(content: string, maxLines: number): string[] {
  const sections: string[][] = [];
  let current: string[] = [];
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

function getRecentMemories(
  memDir: string,
  count = 2,
  maxLinesPerFile = 30
): string {
  if (!existsSync(memDir)) return "";

  const files = readdirSync(memDir)
    .filter((f) => f.endsWith(".md"))
    .sort()
    .slice(-count);

  if (files.length === 0) return "";

  const summary: string[] = [];
  for (const file of files) {
    try {
      const content = readFileSync(join(memDir, file), "utf-8");
      const lines = recentMemoryPreviewLines(content, maxLinesPerFile);
      if (lines.length > 0) {
        summary.push(`[${file}]`, ...lines);
      }
    } catch {
      /* skip unreadable files */
    }
  }

  if (summary.length === 0) {
    return `You have ${files.length} past memory file(s). Use the memory_search tool when the user's question could benefit from historical context.`;
  }

  return `Recent memories (use memory_search for full search):\n${summary.join("\n")}`;
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

function tailTruncate(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `...(truncated to tail)\n${text.slice(-maxChars)}`;
}

/**
 * Extract the last user+assistant turn from an array of messages.
 * Returns a formatted string or null if no valid turn found.
 */
/**
 * Strip injected memory context from a user message.
 * OpenClaw injects "Recent memories (use memory_search for full search):" blocks
 * and "Conversation info (untrusted metadata):" blocks into user messages.
 * These should not be captured as part of the user's actual input.
 */
function stripInjectedContext(text: string): string {
  // Remove "Recent memories ..." block (goes until a blank line followed by non-indented text, or end)
  let cleaned = text.replace(/Recent memories \(use memory_search for full search\):[\s\S]*?(?=\n\n(?!\s|-)|\n*$)/g, "");
  // Remove "Conversation info (untrusted metadata):" block
  cleaned = cleaned.replace(/Conversation info \(untrusted metadata\):[\s\S]*?(?=\n\n(?!\s|")|\n*$)/g, "");
  // Remove "[message_id: ...]" lines
  cleaned = cleaned.replace(/\[message_id:.*?\]\n/g, "");
  return cleaned.trim();
}

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
    let text = extractText(content);

    if (!text || text.length < 5) continue;

    if (role === "user") {
      // Strip injected memory context — only capture the user's actual message
      text = stripInjectedContext(text);
      if (!text || text.length < 5) continue;
      parts.push(`[User]: ${text}`);
    } else if (role === "assistant") {
      parts.push(`[Assistant]: ${tailTruncate(text, 3000)}`);
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

const SESSION_REFERENCE_PREFIX = "openclaw-session:";

/** Optional public SDK: old hosts continue to use their JSONL transcripts. */
async function loadTranscriptSdk(): Promise<any> {
  try {
    return await import("openclaw/plugin-sdk/session-transcript-runtime");
  } catch (error: any) {
    const missing = ["ERR_PACKAGE_PATH_NOT_EXPORTED", "ERR_MODULE_NOT_FOUND", "MODULE_NOT_FOUND"].includes(error.code);
    // Older jiti hosts expand the missing subpath under their root alias. Match
    // only the missing target, never a transitive dependency's require stack.
    if (missing && /(?:package 'openclaw'|openclaw\/plugin-sdk\/session-transcript-runtime|openclaw\/dist\/plugin-sdk\/(?:root-alias\.cjs\/)?session-transcript-runtime|session-transcript-runtime.*openclaw)/.test(error.message.split("\n")[0])) {
      return undefined;
    }
    throw error;
  }
}

async function loadSessionVisibilitySdk(): Promise<any> {
  const [visibility, routing] = await Promise.all([
    import("openclaw/plugin-sdk/session-visibility"),
    import("openclaw/plugin-sdk/routing"),
  ]);
  return { ...visibility, ...routing };
}

/** Resolve storage through the host; retain the selected profile on old hosts. */
function resolveStateDir(runtime: any): string {
  return runtime.state?.resolveStateDir?.() || process.env.OPENCLAW_STATE_DIR?.trim() ||
    join(process.env.HOME || "~", ".openclaw");
}

/** Storage-neutral L3 references retain both the session incarnation and its store scope. */
export function createTranscriptAccess(runtime: any, config: any = {}, loadSdk = loadTranscriptSdk, loadPolicy = loadSessionVisibilitySdk) {
  let sdkPromise: Promise<any> | undefined;
  let policyPromise: Promise<any> | undefined;
  const sdk = () => sdkPromise ??= loadSdk();
  const currentConfig = (ctx: any) => ctx.getRuntimeConfig?.() ?? ctx.runtimeConfig ?? ctx.config ?? config;
  function assertCaller(ctx: any, signal?: AbortSignal): void {
    signal?.throwIfAborted();
    ctx?.assertInvocationCurrent?.();
    ctx?.assertMemoryAudienceCurrent?.();
    if (!ctx?.agentId || ctx.sandboxed || ctx.fsPolicy?.workspaceOnly ||
        ctx.sessionKey?.split(":").includes("incognito")) {
      throw new Error("Transcript access requires an unsandboxed, identified session");
    }
  }
  function storePath(agentId: string, cfg: any): string {
    const resolveStore = runtime.agent?.session?.resolveStorePath ?? runtime.channel?.session?.resolveStorePath;
    return resolveStore ? resolveStore(cfg?.session?.store, { agentId }) :
      join(resolveStateDir(runtime), "agents", agentId, "sessions", "sessions.json");
  }
  async function authorizeTarget(policy: any, scope: any, ctx: any, signal?: AbortSignal): Promise<void> {
    assertCaller(ctx, signal);
    const cfg = currentConfig(ctx);
    if (scope.agentId !== ctx.agentId || scope.storePath !== storePath(ctx.agentId, cfg)) {
      throw new Error("Transcript reference is outside the current profile/agent store");
    }
    for (const key of [ctx.sessionKey, scope.sessionKey]) {
      if (typeof key !== "string" || key.trim() !== key ||
          policy.parseAgentSessionKey(key)?.agentId !== ctx.agentId || policy.isIncognitoSessionKey(key)) {
        throw new Error("Transcript access requires canonical, non-incognito session keys for the current agent");
      }
    }
    // These auxiliary surfaces can have private read-scope ceilings that the
    // public plugin context does not expose. Do not infer or reconstruct them.
    if (policy.isSubagentSessionKey(ctx.sessionKey) || policy.isAcpSessionKey(ctx.sessionKey) || cfg.session?.scope === "global") {
      throw new Error("Transcript access does not support this auxiliary/global session read scope");
    }
    const crossSession = scope.sessionKey !== ctx.sessionKey || scope.sessionId !== ctx.sessionId;
    if (crossSession && cfg.gateway?.roles) {
      throw new Error("Role-controlled cross-session transcript access requires host caller authorization");
    }
    const getEntry = runtime.agent?.session?.getSessionEntryAsync;
    if (typeof getEntry !== "function") throw new Error("Host cannot confirm target session metadata");
    const entry = await getEntry({ agentId: ctx.agentId, sessionKey: scope.sessionKey,
      storePath: scope.storePath, readConsistency: "latest" });
    assertCaller(ctx, signal);
    if (!entry || entry.sessionId !== scope.sessionId || entry.incognito === true ||
        (entry.visibility !== undefined && entry.visibility !== "shared")) {
      throw new Error("Target session metadata is missing, changed, draft or incognito");
    }
    const access = policy.createSessionVisibilityRowChecker({
      action: "history", requesterAgentId: ctx.agentId, defaultAgentId: ctx.agentId,
      requesterSessionKey: ctx.sessionKey,
      mainSessionKey: policy.buildAgentMainSessionKey({ agentId: ctx.agentId, mainKey: cfg.session?.mainKey }),
      visibility: policy.resolveEffectiveSessionToolsVisibility({ cfg, sandboxed: ctx.sandboxed === true }),
      a2aPolicy: policy.createAgentToAgentPolicy(cfg, { sandboxed: ctx.sandboxed === true }),
    }).check({ key: scope.sessionKey, agentId: ctx.agentId, ownerSessionKey: entry.ownerSessionKey,
      spawnedBy: entry.spawnedBy, parentSessionKey: entry.parentSessionKey });
    if (!access.allowed) throw new Error(access.error || "Session history visibility denied");
  }
  async function checkedIdentity(reader: any, scope: any): Promise<void> {
    const identity = await reader.resolveSessionTranscriptIdentity(scope);
    if (identity.agentId !== scope.agentId || identity.sessionId !== scope.sessionId ||
        identity.sessionKey !== scope.sessionKey) {
      throw new Error("Transcript session identity changed; refusing a different session");
    }
  }
  return {
    async capture(ctx: any): Promise<string> {
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
        // Explicit session metadata survives the host's credential-query redaction.
        ref.searchParams.set("sessionKey", scope.sessionKey);
        ref.searchParams.set("store", store);
        return ref.href;
      }
      const path = join(dirname(store), `${scope.sessionId}.jsonl`);
      // Do not advertise an invented legacy path for a SQLite-only session.
      return existsSync(path) ? path : "";
    },
    async read(reference: string, ctx: any, signal?: AbortSignal): Promise<string | undefined> {
      assertCaller(ctx, signal);
      const cfg = currentConfig(ctx);
      const currentStore = storePath(ctx.agentId, cfg);
      if (!reference.startsWith(SESSION_REFERENCE_PREFIX)) {
        const root = dirname(currentStore);
        const file = resolve(reference);
        const inside = (base: string, target: string) => {
          const rel = relative(base, target);
          return rel !== "" && !rel.startsWith("..") && !isAbsolute(rel);
        };
        if (!isAbsolute(reference) || !inside(resolve(root), file) || !file.endsWith(".jsonl") ||
            (existsSync(file) && !inside(realpathSync(root), realpathSync(file)))) {
          throw new Error("Legacy transcript is outside the current profile/agent store");
        }
        const modern = await sdk();
        assertCaller(ctx, signal);
        if (modern) {
          throw new Error("Use an SDK-generated session reference on this host; JSONL paths lack exact target key metadata");
        }
        if (basename(file) !== `${ctx.sessionId}.jsonl` &&
            (["self", "tree"].includes(cfg.tools?.sessions?.visibility) || cfg.gateway?.roles)) {
          throw new Error("Legacy transcript cannot confirm access under restricted session policy");
        }
        return undefined;
      }
      const ref = new URL(reference);
      const scope = {
        agentId: decodeURIComponent(ref.hostname), sessionId: decodeURIComponent(ref.pathname.slice(1)),
        sessionKey: ref.searchParams.get("sessionKey"), storePath: ref.searchParams.get("store"),
      };
      if (!scope.agentId || !scope.sessionId || !scope.sessionKey || !scope.storePath || !isAbsolute(scope.storePath) || ref.username || ref.password || ref.port || ref.hash) {
        throw new Error("Invalid OpenClaw session transcript reference");
      }
      if (scope.agentId !== ctx.agentId || scope.storePath !== currentStore) {
        throw new Error("Transcript reference is outside the current profile/agent store");
      }
      const reader = await sdk();
      if (!reader) throw new Error("This host does not provide the OpenClaw session transcript SDK");
      if (typeof reader.resolveSessionTranscriptIdentity !== "function" ||
          typeof reader.readVisibleSessionTranscriptMessageEntries !== "function") {
        throw new Error("This host lacks the required session transcript SDK readers");
      }
      const policy = await (policyPromise ??= loadPolicy());
      await authorizeTarget(policy, scope, ctx, signal);
      await checkedIdentity(reader, scope);
      assertCaller(ctx, signal);
      const entries = await reader.readVisibleSessionTranscriptMessageEntries(scope);
      // Recheck exact metadata and current policy before disclosing the result.
      await authorizeTarget(policy, scope, ctx, signal);
      assertCaller(ctx, signal);
      const messages = entries.map((entry: any) => entry.message).filter((m: any) => m?.role === "user" || m?.role === "assistant");
      const lastUser = messages.findLastIndex((m: any) => m.role === "user");
      if (lastUser < 0) return "(no user message found)";
      const lines = messages.slice(lastUser).map((m: any) => {
        const text = typeof m.content === "string" ? m.content : (m.content || [])
          .filter((block: any) => block.type === "text").map((block: any) => block.text || "").join("\n");
        return text.trim() ? `[${m.role === "user" ? "User" : "Assistant"}]: ${text}` : "";
      }).filter(Boolean);
      const output = ["=== Transcript of a conversation between User and an AI assistant ===", ...lines].join("\n");
      return output.length > 32000 ? `${output.slice(0, 32000)}\n[Transcript output truncated]` : output;
    },
  };
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
    const transcripts = createTranscriptAccess(api.runtime, api.config);

    // Convenience wrapper for api.runtime.system.runCommandWithTimeout
    async function runCmd(
      argv: string[],
      opts?: { timeoutMs?: number; cwd?: string; env?: Record<string, string> }
    ): Promise<{ stdout: string; stderr: string; code: number | null }> {
      return api.runtime.system.runCommandWithTimeout(argv, opts || {});
    }

    function commandFailure(
      action: string,
      result: { stdout: string; stderr: string; code: number | null }
    ): string | null {
      if (result.code === 0) return null;
      const detail = (result.stderr || result.stdout || "unknown error").trim();
      return `${action} failed (exit ${result.code ?? "unknown"}): ${detail}`;
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

    async function getMemsearchConfigValue(key: string, cwd = projectDir): Promise<string> {
      const cmd = await getMemsearchCmd();
      const r = await runCmd(
        ["bash", "-c", `${cmd} config get '${shellEscape(key)}'`],
        { timeoutMs: 5000, cwd }
      );
      return r.stdout?.trim() || "";
    }

    async function getSkillCandidateHint(cwd: string): Promise<string> {
      try {
        const cmd = await getMemsearchCmd();
        const r = await runCmd(
          [
            "bash", "-c",
            `MEMSEARCH_DIR='${shellEscape(getMemsearchDir(cwd))}' ${cmd} skills status --hint`,
          ],
          { timeoutMs: 5000, cwd }
        );
        if (r.code !== 0) return "";
        return r.stdout?.trim().split("\n")[0] || "";
      } catch {
        return "";
      }
    }

    async function wakeMaintenance(cwd = projectDir): Promise<void> {
      try {
        const runner = join(PLUGIN_DIR, "scripts", "maintenance-runner.py");
        runCmd(
          [
            "bash", "-c",
            `python3 '${shellEscape(runner)}' --platform openclaw ` +
              `--project-dir '${shellEscape(cwd)}' ` +
              `--memsearch-dir '${shellEscape(getMemsearchDir(cwd))}'`,
          ],
          {
            timeoutMs: 120000,
            cwd,
            env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" }),
          }
        ).catch(() => { /* ignore */ });
      } catch {
        /* ignore */
      }
    }

    // --- Lazy-cached collection name derivation ---
    const collections = new Map<string, Promise<string>>();

    async function requireDefaultCollectionSupport(
      cwd: string,
      collection: string
    ): Promise<void> {
      const cmd = await getMemsearchCmd();
      const r = await runCmd(
        [
          "bash",
          "-c",
          `${cmd} config get milvus.collection ` +
            `--default-collection '${shellEscape(collection)}'`,
        ],
        { timeoutMs: 5000, cwd }
      );
      if (r.code !== 0) {
        throw new Error(
          "Installed memsearch CLI is incompatible with this plugin; " +
            "--default-collection support is required. Upgrade memsearch core and the plugin together."
        );
      }
    }

    async function getCollectionName(cwd = projectDir): Promise<string> {
      const scopeDir = getCollectionScopeDir(cwd);
      const key = JSON.stringify([cwd, scopeDir]);
      if (!collections.has(key)) collections.set(key, (async () => {
        let collection = "ms_openclaw_default";
        const script = join(PLUGIN_DIR, "scripts", "derive-collection.sh");
        try {
          const r = await runCmd(["bash", script, scopeDir], { timeoutMs: 5000 });
          if (r.code === 0 && r.stdout?.trim()) {
            collection = r.stdout.trim();
          }
        } catch {
          /* use the compatibility default */
        }
        await requireDefaultCollectionSupport(cwd, collection);
        return collection;
      })().catch(error => { collections.delete(key); throw error; }));
      return collections.get(key)!;
    }

    // Per-agent state — updated by both hook and tool contexts.
    // Memory lives under <workspace>/.memsearch/memory/ — co-located with
    // AGENTS.md, IDENTITY.md, etc. Collection name is derived from the
    // workspace path (same algorithm as Claude Code/Codex/OpenCode) so that
    // memories are automatically shared when multiple platforms work on the
    // same project directory.
    let agentId = "main";
    let projectDir = join(resolveStateDir(api.runtime), "workspace");
    let memoryDir = getMemoryDir(projectDir);

    /** Hooks may run before any tool factory, including the first captured turn. */
    function updateAgentContext(ctx: any): void {
      const newId = ctx?.agentId || agentId;
      const newWorkspace = ctx?.workspaceDir ||
        api.runtime.agent?.resolveAgentWorkspaceDir?.(api.config, newId);
      if (newId !== agentId || (newWorkspace && newWorkspace !== projectDir)) {
        agentId = newId;
        projectDir = newWorkspace || join(resolveStateDir(api.runtime), agentId === "main" ? "workspace" : `workspace-${agentId}`);
        memoryDir = getMemoryDir(projectDir);
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
        const toolProjectDir = projectDir;
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
              const collection = await getCollectionName(toolProjectDir);
              const result = await runCmd(
                [
                  "bash", "-c",
                  `${cmd} search '${shellEscape(params.query)}' ` +
                    `--top-k ${topK} --json-output --default-collection ${collection}`,
                ],
                { timeoutMs: 30000, cwd: toolProjectDir }
              );
              const failure = commandFailure("Search", result);
              if (failure) {
                return { content: [{ type: "text" as const, text: failure }] };
              }
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
        const toolProjectDir = projectDir;
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
              const collection = await getCollectionName(toolProjectDir);
              const result = await runCmd(
                [
                  "bash", "-c",
                  `${cmd} expand '${shellEscape(params.chunk_hash)}' ` +
                    `--default-collection ${collection}`,
                ],
                { timeoutMs: 15000, cwd: toolProjectDir }
              );
              const failure = commandFailure("Expand", result);
              if (failure) {
                return { content: [{ type: "text" as const, text: failure }] };
              }
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
    // Reads the host transcript SDK, with compatibility for existing JSONL anchors.
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
            "anchor (<!-- session:UUID transcript:REFERENCE -->). Pass its exact reference unchanged. Returns the formatted " +
            "dialogue with [User] and [Assistant] labels.",
          parameters: {
            type: "object" as const,
            properties: {
              transcript_path: {
                type: "string" as const,
                description: "Exact transcript reference from the anchor: openclaw-session URI or legacy .jsonl path",
              },
            },
            required: ["transcript_path"],
          },
          async execute(
            _toolCallId: string,
            params: { transcript_path: string },
            signal?: AbortSignal
          ) {
            try {
              const transcript = await transcripts.read(params.transcript_path, ctx, signal);
              if (transcript !== undefined) {
                return { content: [{ type: "text" as const, text: transcript }] };
              }
              const scriptPath = join(PLUGIN_DIR, "scripts", "parse-transcript.sh");
              const result = await runCmd(
                ["bash", scriptPath, params.transcript_path],
                { timeoutMs: 15000 }
              );
              signal?.throwIfAborted();
              ctx?.assertInvocationCurrent?.();
              ctx?.assertMemoryAudienceCurrent?.();
              const failure = commandFailure("Transcript", result);
              if (failure) return { content: [{ type: "text" as const, text: failure }] };
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

    // ----- Hook: before_prompt_build — inject recent memories -----
    if (autoRecall) {
      api.on("before_prompt_build", async (_event: any, ctx: any) => {
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
      async function summarizeWithLLM(turnText: string, captureProjectDir: string): Promise<string> {
        // Load summarization prompt: user custom (via config) > plugin built-in template
        const agentName = "OpenClaw";
        let systemPrompt = "";

        // Try reading user-custom prompt from config
        let customPromptFile = "";
        try {
          customPromptFile = await getMemsearchConfigValue("prompts.summarize", captureProjectDir);
        } catch { /* ignore */ }
        if (customPromptFile && !isAbsolute(customPromptFile)) {
          customPromptFile = join(captureProjectDir, customPromptFile);
        }

        if (customPromptFile && existsSync(customPromptFile)) {
          systemPrompt = readFileSync(customPromptFile, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
        } else {
          // Fall back to plugin built-in template
          const builtinPath = join(PLUGIN_DIR, "prompts", "summarize.txt");
          if (existsSync(builtinPath)) {
            systemPrompt = readFileSync(builtinPath, "utf-8").replace(/\{\{AGENT_NAME\}\}/g, agentName);
          } else {
            systemPrompt =
              "You are a third-person note-taker. Summarize the transcript as 2-10 bullet points. " +
              "Write in third person. Mandatory language rule: write every bullet in the same primary language as the " +
              "[User] text. If User mixes languages, use the dominant user-facing language. " +
              "Do NOT answer User's question. Output ONLY bullet points.";
          }
        }

        let summarizeModel = "";
        try {
          summarizeModel = await getMemsearchConfigValue("plugins.openclaw.summarize.model", captureProjectDir);
        } catch { /* ignore */ }

        let summarizeProvider = "";
        try {
          summarizeProvider = await getMemsearchConfigValue("plugins.openclaw.summarize.provider", captureProjectDir);
        } catch { /* ignore */ }

        if (summarizeProvider && summarizeProvider !== "native") {
          try {
            const cmd = await getMemsearchCmd();
            const tmpInput = `/tmp/memsearch-summarize-input-${randomUUID()}.txt`;
            writeFileSync(tmpInput, turnText, "utf-8");
            const shellCmd =
              `cat ${JSON.stringify(tmpInput)} | ${cmd} summarize ` +
              `--plugin openclaw --agent-name OpenClaw`;
            const result = await runCmd(["bash", "-c", shellCmd], {
              timeoutMs: 60000,
              cwd: captureProjectDir,
              env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" }),
            });
            try { unlinkSync(tmpInput); } catch { /* ignore cleanup errors */ }
            const output = (result.stdout || "").trim();
            if (output) {
              return output;
            }
          } catch {
            /* timeout or exec error — fall through to fallback */
          }
        }

        // 1. Try openclaw agent (uses user's default model unless overridden)
        // Redirect stdout to a temp file because runCommandWithTimeout
        // truncates stdout before the LLM response arrives.
        try {
          const msgText = `${systemPrompt}\n\nTranscript:\n${turnText}`;
          const tmpFile = `/tmp/memsearch-summarize-${randomUUID()}.txt`;
          const modelArg = summarizeModel ? ` --model '${shellEscape(summarizeModel)}'` : "";
          const shellCmd = `openclaw agent --local --session-id ${randomUUID()}${modelArg} -m '${shellEscape(msgText)}' > ${JSON.stringify(tmpFile)} 2>/dev/null`;
          await runCmd(["bash", "-c", shellCmd], {
            timeoutMs: 60000,
            cwd: captureProjectDir,
            env: envWithOverrides({ MEMSEARCH_NO_WATCH: "1", MEMSEARCH_DISABLE: "1" }),
          });
          if (existsSync(tmpFile)) {
            const raw = readFileSync(tmpFile, "utf-8");
            try { unlinkSync(tmpFile); } catch { /* ignore cleanup errors */ }
            // Filter out plugin loading logs polluting stdout (openclaw/openclaw#51076)
            const output = raw
              .split("\n")
              .filter((line: string) => !line.startsWith("[plugins]") && !line.startsWith("[agents]"))
              .join("\n")
              .trim();
            if (output && output.includes("- ")) {
              return output;
            }
          }
        } catch {
          /* timeout or exec error — fall through to fallback */
        }

        // 2. Fallback: return raw text (truncated)
        return tailTruncate(turnText, 1500);
      }

      /** Write a turn summary to the daily memory file and re-index. */
      async function writeTurnCapture(turnText: string, ctx: any, provenance: Promise<string>): Promise<void> {
        try {
          if (turnText.length < 1) return;
          const captureMemoryDir = ctx.memoryDir;
          let anchor = "";
          try {
            const reference = await provenance;
            if (reference) anchor = `<!-- session:${ctx.sessionId} transcript:${reference} -->\n`;
          } catch (error: any) {
            logger?.warn?.(`[memsearch] Transcript provenance unavailable: ${error.message}`);
          }

          ensureDir(captureMemoryDir);
          const today = new Date().toISOString().split("T")[0];
          const now = new Date().toTimeString().slice(0, 5);
          const memoryFile = join(captureMemoryDir, `${today}.md`);

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
            summary = await summarizeWithLLM(turnText, ctx.projectDir);
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
          const entry = `### ${now}\n${anchor}${cleanSummary}\n\n`;
          ctx.assertInvocationCurrent?.();
          ctx.assertMemoryAudienceCurrent?.();
          appendFileSync(memoryFile, entry, "utf-8");

          // Index in background (non-blocking, fire-and-forget)
          const cmd = await getMemsearchCmd();
          const collection = await getCollectionName(ctx.projectDir);
          runCmd(
            [
              "bash", "-c",
              `${cmd} index '${shellEscape(captureMemoryDir)}' --default-collection ${collection}`,
            ],
            { timeoutMs: 60000, cwd: ctx.projectDir }
          ).catch((err: any) => {
            logger?.warn?.(`[memsearch] Index failed: ${err.message}`);
          });

          logger?.info?.(`[memsearch] Captured turn summary → ${memoryFile}`);
        } catch (e: any) {
          logger?.warn?.(`[memsearch] Capture failed: ${e.message}`);
        }
      }

      // Primary capture: agent_end fires every turn with full message history
      api.on("agent_end", async (event: any, ctx: any) => {
        // Failed turns and restricted audiences must not enter shared persistent memory.
        if (event.success === false || !ctx?.agentId || ctx.sandboxed ||
            ctx.sessionKey?.split(":").includes("incognito") ||
            (ctx.memoryAudience && (ctx.memoryAudience.kind !== "owner-private" || ctx.memoryAudience.agentId !== ctx.agentId))) return;
        ctx.assertMemoryAudienceCurrent?.();
        updateAgentContext(ctx);
        const captureContext = Object.freeze({
          ...ctx, agentId: ctx?.agentId, projectDir, memoryDir,
          sessionId: ctx?.sessionId || "", sessionKey: ctx?.sessionKey,
        });
        const messages = event.messages || [];
        if (messages.length < 2) return;
        const lastTurn = extractLastTurn(messages);
        if (!lastTurn || lastTurn.length < 50) return;
        // Start provenance resolution synchronously, freezing the host-selected
        // store before configuration or summarization can yield to another hook.
        const provenance = transcripts.capture(captureContext).catch((error: any) => {
          logger?.warn?.(`[memsearch] Transcript provenance unavailable: ${error.message}`);
          return "";
        });

        let summarizeEnabled = "true";
        try {
          summarizeEnabled = await getMemsearchConfigValue("plugins.openclaw.summarize.enabled", captureContext.projectDir);
        } catch { /* ignore */ }
        if (summarizeEnabled === "false") {
          wakeMaintenance(captureContext.projectDir).catch(() => { /* ignore */ });
          return;
        }

        await writeTurnCapture(lastTurn, captureContext, provenance);
        wakeMaintenance(captureContext.projectDir).catch(() => { /* ignore */ });
      });
    }

    // ----- Hook: session_start — ensure config + start indexing -----
    api.on("session_start", async (_event: any, ctx: any) => {
      updateAgentContext(ctx);
      const sessionProjectDir = projectDir;
      const sessionMemoryDir = memoryDir;
      try {
        const cmd = await getMemsearchCmd();
        const collection = await getCollectionName(sessionProjectDir);

        // Ensure default config (onnx provider, no API key needed)
        const configFile = join(home, ".memsearch", "config.toml");
        const localConfig = join(sessionProjectDir, ".memsearch.toml");
        if (!existsSync(configFile) && !existsSync(localConfig)) {
          try {
            await runCmd(
              ["bash", "-c", `${cmd} config set embedding.provider onnx`],
              { timeoutMs: 5000, cwd: sessionProjectDir }
            );
          } catch {
            /* ignore */
          }
        }

        // Run initial index in background (fire-and-forget)
        if (existsSync(sessionMemoryDir)) {
          runCmd(
            [
              "bash", "-c",
              `${cmd} index '${shellEscape(sessionMemoryDir)}' --default-collection ${collection}`,
            ],
            { timeoutMs: 120000, cwd: sessionProjectDir }
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
                  `--top-k ${opts.topK || 5} --default-collection ${collection}`,
              ],
              { timeoutMs: 30000, cwd: projectDir }
            );
            const failure = commandFailure("Search", result);
            if (failure) throw new Error(failure);
            if (result.stdout) process.stdout.write(result.stdout);
            if (result.stderr) process.stderr.write(result.stderr);
          } catch (e: any) {
            const message = String(e.message).startsWith("Search failed")
              ? String(e.message)
              : `Search failed: ${e.message}`;
            console.error(message);
            if (message === e.message) throw e;
            throw new Error(message);
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
                `${memsearch} index '${shellEscape(dir)}' --default-collection ${collection}`,
              ],
              { timeoutMs: 120000, cwd: projectDir }
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
          let effectiveCollection = collection;
          try {
            const result = await runCmd(
              [
                "bash", "-c",
                `${memsearch} config get milvus.collection --default-collection '${shellEscape(collection)}'`,
              ],
              { timeoutMs: 10000, cwd: projectDir }
            );
            effectiveCollection = result.stdout.trim() || collection;
          } catch {
            // Older CLI versions do not expose integration defaults on config get.
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
              { timeoutMs: 10000, cwd: projectDir }
            );
            const failure = commandFailure("Stats", result);
            if (failure) console.log(failure);
            else if (result.stdout) process.stdout.write(result.stdout);
          } catch (e: any) {
            console.log(`Stats failed: ${e.message}`);
          }
        });
    }, {
      commands: ["memsearch"],
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
      .catch((error: any) => {
        logger?.error?.(
          `[memsearch] Plugin initialization failed: ${error.message}`
        );
      });
  },
};
