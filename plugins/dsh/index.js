/**
 * memsearch-dsh — MemSearch plugin for DeepSeek Harness.
 *
 * Gives DSH persistent, cross-agent memory on top of memsearch:
 *
 *   capture  — every completed turn from the `session/event` stream is
 *              summarized (memsearch-managed `[llm.providers.*]` or a one-shot
 *              DSH headless agent, see `summarizeMode`) and appended to
 *              `<project>/.memsearch/memory/YYYY-MM-DD.md` alongside the other
 *              platform plugins (Claude Code, Codex, OpenClaw, OpenCode). The
 *              anchor format is identical, so DSH writes join the same shared
 *              memory store. Processing is fire-and-forget: each turn is
 *              summarized and written asynchronously, serialized so LLM calls
 *              never overlap, with `captureExists` dedup so a turn is recorded
 *              exactly once even across restarts.
 *   inject   — before the first model step of each turn, `agent/pre-step`
 *              runs a bounded memsearch search over the user's question and,
 *              only when relevant results exist, injects them plus a
 *              `[memsearch] Memory available.` hint. When nothing is relevant
 *              the decision is returned unchanged — zero context cost.
 *   recall   — registers a `memory-recall` skill (search → expand → transcript)
 *              that the model can invoke through the native `skill` tool.
 *
 * The plugin is a plain ESM module with no build step. It is installed into a
 * DSH profile via `dsh plugin --profile <name> add <path>` (pnpm link), where
 * the package.json `dsh.bundle` declaration points at `cordis.patch.yml`.
 *
 * @module memsearch-dsh
 */

import { execFile, execFileSync, spawn } from 'node:child_process'
import {
  appendFileSync,
  existsSync,
  mkdirSync,
  readFileSync,
  realpathSync,
  readdirSync,
  statSync,
  writeFileSync,
} from 'node:fs'
import { createRequire } from 'node:module'
import { basename, dirname, extname, isAbsolute, join, relative, resolve, sep } from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const PLUGIN_DIR = dirname(fileURLToPath(import.meta.url))

/** Cordis plugin name; also the `source.plugin` tag on injected messages. */
export const name = 'memsearch'

/** Services this plugin needs before `apply()` runs. */
export const inject = ['agents', 'skills', 'sessionPersistence']

const DEFAULT_AGENT_NAME = 'DeepSeek Harness'
const MEMSEARCH_MARKER = '[memsearch] Memory available.'
const SEARCH_TOP_K = 5
const SEARCH_TIMEOUT_MS = 15000
const SUMMARIZE_TIMEOUT_MS = 30000
const CAPTURE_MAX_CHARS = 6000
const INJECT_SNIPPET_CHARS = 180
const DAILY_FILE_RE = /^\d{4}-\d{2}-\d{2}\.md$/
const MAINTENANCE_INTERVAL_MS = 6 * 60 * 60 * 1000 // 6h; runner's due-state gates actual runs

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Shell-escape a string for safe use inside single quotes. */
function shellEscape(s) {
  return String(s).replace(/'/g, "'\\''")
}

let dshLlmModule = null

/**
 * Lazily load `@deepseek-ai/dsh-llm` for its `createUserMessage` factory.
 *
 * This plugin is installed as an out-of-tree package (pnpm `link:`), so its
 * real directory is outside the DSH workspace and Node's bare-specifier walk
 * from `import.meta.url` cannot see the DSH packages. DSH maintains a flat
 * module fallback at `$DSH_HOME/profiles/node_modules` covering the whole app
 * dependency closure — the documented "bundles come from the installation"
 * contract — reachable by Node's parent-directory walk from any profile. The
 * loader anchors `ctx.baseUrl` at the profile directory, so we resolve through
 * a `createRequire` there and `import()` the resolved absolute path. When the
 * package is genuinely unreachable we fall back to building the same message
 * shape inline so injection never hard-fails the plugin.
 * @param ctx - the Cordis context (its `baseUrl` is the profile dir).
 * @returns the dsh-llm module namespace, or `null` when unresolvable.
 */
async function loadDshLlm(ctx) {
  if (dshLlmModule) return dshLlmModule
  dshLlmModule = (async () => {
    try {
      let anchor = import.meta.url
      if (ctx?.baseUrl) {
        const base = String(ctx.baseUrl)
        anchor = pathToFileURL(join(base.startsWith('file:') ? fileURLToPath(base) : base, '_memsearch.js')).href
      }
      const resolved = createRequire(anchor).resolve('@deepseek-ai/dsh-llm')
      return await import(pathToFileURL(resolved).href)
    } catch {
      return null
    }
  })()
  return dshLlmModule
}

/**
 * Build one plugin-sourced user message carrying the memory block.
 * @param ctx - the Cordis context (profile anchor for dsh-llm resolution).
 * @param text - the rendered memory block.
 * @returns a frozen `UserMessage` with a plugin snapshot source.
 */
async function createMemoryMessage(ctx, text) {
  const dshLlm = await loadDshLlm(ctx)
  if (dshLlm?.createUserMessage) {
    return dshLlm.createUserMessage({
      content: [{ type: 'text', text }],
      source: {
        kind: 'plugin',
        plugin: name,
        form: 'snapshot',
        sections: [{ name, text }],
      },
    })
  }
  return Object.freeze({
    id: crypto.randomUUID(),
    role: 'user',
    content: [{ type: 'text', text }],
    source: {
      kind: 'plugin',
      plugin: name,
      form: 'snapshot',
      sections: [{ name, text }],
    },
  })
}

/**
 * Detect the memsearch CLI command: installed binary on PATH first, then the
 * uvx fallback, then a bare `memsearch` best effort.
 *
 * `command -v` is resolved through bash so the check sees the same PATH the
 * later `bash -c` invocations use; calling `which` as a direct executable
 * bypasses shell built-ins and can miss the installed tool.
 */
function detectMemsearchCmd() {
  const home = process.env.HOME || ''
  const onPath = (cmd) => {
    try {
      execFileSync('bash', ['-c', `command -v ${cmd} >/dev/null 2>&1`], { stdio: 'pipe' })
      return true
    } catch {
      return false
    }
  }
  if (onPath('memsearch')) return 'memsearch'
  const uvxPath = join(home, '.local', 'bin', 'uvx')
  const uvxBin = existsSync(uvxPath) ? uvxPath : (onPath('uvx') ? 'uvx' : '')
  if (uvxBin) {
    return `${uvxBin} --from 'memsearch[onnx]' memsearch`
  }
  return 'memsearch'
}

/** Derive the per-project Milvus collection name via the shared script. */
function deriveCollection(projectDir, override) {
  if (override) return override
  const script = join(PLUGIN_DIR, 'scripts', 'derive-collection.sh')
  try {
    const result = execFileSync('bash', [script, projectDir], {
      encoding: 'utf-8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return result.trim() || undefined
  } catch {
    return undefined
  }
}

/**
 * Read a dotted value from the memsearch config (e.g. `plugins.dsh.summarize.provider`).
 *
 * Tolerant of older memsearch installs that predate the `dsh` plugin section:
 * a missing key, missing binary, or any failure returns `null` (treated as
 * "not configured") instead of throwing — so the plugin never breaks on a
 * user's existing memsearch version.
 */
/**
 * Read a dotted memsearch config value. Returns `{ ok, value }` so callers can
 * tell "successfully read and the value is empty" from "the command failed or
 * timed out". A failure must not be mistaken for an authoritative "not
 * configured": a slow/absent memsearch (e.g. first uvx run) would otherwise
 * silently flip auto mode to the wrong backend.
 */
function readMemsearchConfigValue(memsearchCmd, key) {
  try {
    // memsearchCmd may be a full command line (e.g. `uvx --from 'memsearch[onnx]' memsearch`),
    // so route through bash rather than execFileSync's single executable.
    const result = execFileSync('bash', ['-c', `${memsearchCmd} config get '${key}'`], {
      encoding: 'utf-8',
      timeout: 5000,
      stdio: ['ignore', 'pipe', 'ignore'],
    })
    return { ok: true, value: result.trim() || null }
  } catch {
    return { ok: false, value: null }
  }
}

/**
 * Resolve the effective summarization backend for `summarizeMode`.
 *
 * - explicit `custom-llm` / `dsh-headless` pin the backend;
 * - unset (auto) mirrors the other platform plugins: if the user configured a
 *   provider under `[plugins.dsh.summarize]` (memsearch config), use the
 *   lightweight `custom-llm` route; otherwise fall back to `dsh-headless`
 *   (zero-config DSH agent).
 *
 * A read failure of `[plugins.dsh.summarize]` is NOT treated as "not
 * configured": it is logged (via `logger`) and falls back to `dsh-headless`
 * rather than silently picking a backend the user may not have intended.
 * An unknown explicit mode is also logged and treated as auto.
 *
 * Returns `{ mode, provider, model }` where provider/model carry the
 * memsearch-config values when auto resolved them.
 */
function resolveSummarizeMode(memsearchCmd, opts, config, logger) {
  if (opts.summarizeMode === 'custom-llm' || opts.summarizeMode === 'dsh-headless') {
    return {
      mode: opts.summarizeMode,
      provider: opts.summarizeProvider,
      model: opts.summarizeModel,
    }
  }
  if (opts.summarizeMode !== undefined && opts.summarizeMode !== 'auto') {
    logger?.warn?.(`[memsearch] unknown summarizeMode '${opts.summarizeMode}'; treating as auto`)
  }
  // auto: consult memsearch config [plugins.dsh.summarize], aligned with the
  // other platform plugins. Tolerate missing section / older memsearch.
  const provider = readMemsearchConfigValue(memsearchCmd, 'plugins.dsh.summarize.provider')
  if (!provider.ok) {
    logger?.warn?.(
      '[memsearch] could not read [plugins.dsh.summarize] provider from memsearch config; using dsh-headless',
    )
    return { mode: 'dsh-headless', provider: opts.summarizeProvider, model: opts.summarizeModel }
  }
  if (provider.value) {
    const model = readMemsearchConfigValue(memsearchCmd, 'plugins.dsh.summarize.model')
    const enabled = readMemsearchConfigValue(memsearchCmd, 'plugins.dsh.summarize.enabled')
    if (enabled.ok && (enabled.value === null || enabled.value === 'true')) {
      return { mode: 'custom-llm', provider: provider.value, model: model.ok ? model.value || '' : '' }
    }
  }
  return { mode: 'dsh-headless', provider: opts.summarizeProvider, model: opts.summarizeModel }
}

/** Project directory for a session (its durable cwd) or the process cwd. */
function projectDirFor(session) {
  return session?.header?.cwd || process.cwd()
}

/**
 * Memory directory for a project. `MEMSEARCH_DIR` (explicit → global scope)
 * wins, mirroring the other platform plugins; otherwise `<project>/.memsearch`.
 */
function memsearchDirFor(projectDir) {
  return process.env.MEMSEARCH_DIR || join(projectDir, '.memsearch')
}

/** `[User]`/`[Assistant]` text from a message's content blocks. */
function textFromContent(content) {
  return (Array.isArray(content) ? content : [])
    .filter((block) => block && block.type === 'text' && typeof block.text === 'string')
    .map((block) => block.text)
    .join('\n')
    .trim()
}

/** True when the memory directory holds at least one daily markdown file. */
function hasMemoryFiles(memoryDir) {
  try {
    return readdirSync(memoryDir).some((file) => DAILY_FILE_RE.test(file))
  } catch {
    return false
  }
}

/** Local YYYY-MM-DD date string. */
function todayStr() {
  return new Date().toISOString().slice(0, 10)
}

/** Local HH:MM time string. */
function hhmmStr() {
  const now = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return `${pad(now.getHours())}:${pad(now.getMinutes())}`
}

// ---------------------------------------------------------------------------
// Search / index (memsearch CLI)
// ---------------------------------------------------------------------------

/**
 * `--milvus-uri '<uri>'` CLI flag when a dedicated Milvus is configured for the
 * profile; empty otherwise (memsearch falls back to its own config).
 */
function milvusUriFlag(milvusUri) {
  return milvusUri ? `--milvus-uri '${shellEscape(milvusUri)}' ` : ''
}

/**
 * Run one bounded memsearch search over the project collection.
 * @returns the parsed result array, or null on any failure (caller treats
 *          null as "no relevant memory" and stays a no-op).
 */
function runSearch(memsearchCmd, query, collection, projectDir, milvusUri) {
  return new Promise((resolve) => {
    const command =
      `${memsearchCmd} search '${shellEscape(query)}' ` +
      `--top-k ${SEARCH_TOP_K} --json-output ` +
      `${milvusUriFlag(milvusUri)}` +
      `--collection '${shellEscape(collection)}'`
    execFile(
      'bash',
      ['-c', command],
      { cwd: projectDir, timeout: SEARCH_TIMEOUT_MS, maxBuffer: 4 * 1024 * 1024 },
      (error, stdout) => {
        if (error) return resolve(null)
        try {
          const chunks = JSON.parse(stdout)
          resolve(Array.isArray(chunks) ? chunks : null)
        } catch {
          resolve(null)
        }
      },
    )
  })
}

/** Fire-and-forget `memsearch index` refresh for a project. */
function indexMemory(ctx, memsearchCmd, memoryDir, collection, projectDir, milvusUri) {
  if (!existsSync(memoryDir)) return
  const command =
    `${memsearchCmd} index '${shellEscape(memoryDir)}' ` +
    `${milvusUriFlag(milvusUri)}` +
    `--collection '${shellEscape(collection)}'`
  // Detached + unref so the index survives the DSH process: a headless or
  // one-shot session can exit right after the turn that wrote the memory, and
  // an ordinary child would be torn down with the parent before indexing.
  const child = execFile('bash', ['-c', command], {
    cwd: projectDir,
    timeout: 120000,
    maxBuffer: 4 * 1024 * 1024,
    detached: true,
    stdio: 'ignore',
    env: { ...process.env, MEMSEARCH_NO_WATCH: '1' },
  }, (error) => {
    if (error) ctx.logger.warn(`[memsearch] background index failed: ${error.message}`)
  })
  child.unref()
}

/**
 * Run the shared maintenance runner (PROJECT.md / USER.md upkeep and
 * memory-to-skill distillation) for a project, fire-and-forget.
 *
 * Mirrors the other platform plugins: the runner is a due-state machine —
 * each task runs at most once per `min_interval_hours` and only when
 * `[plugins.dsh.<task>].enabled` is true in memsearch config. A missing
 * memsearch CLI or python3 is a no-op (the runner also checks internally).
 */
function runMaintenance(ctx, projectDir, memsearchDir) {
  const runner = join(PLUGIN_DIR, 'scripts', 'maintenance-runner.py')
  if (!existsSync(runner)) return
  const command =
    `MEMSEARCH_NO_WATCH=1 python3 '${shellEscape(runner)}' ` +
    `--platform dsh ` +
    `--project-dir '${shellEscape(projectDir)}' ` +
    `--memsearch-dir '${shellEscape(memsearchDir)}'`
  const child = execFile('bash', ['-c', command], {
    cwd: projectDir,
    timeout: 180000,
    maxBuffer: 4 * 1024 * 1024,
    detached: true,
    stdio: 'ignore',
    env: { ...process.env, MEMSEARCH_NO_WATCH: '1' },
  }, (error) => {
    if (error) ctx.logger.warn(`[memsearch] maintenance run failed: ${error.message}`)
  })
  child.unref()
}

// ---------------------------------------------------------------------------
// Skill review panel (host side)
// ---------------------------------------------------------------------------

/**
 * Read every skill candidate from the `.memsearch/skill-candidates` directory.
 *
 * The candidates directory is the shared memory-to-skill output across all
 * platform plugins (git-tracked, never auto-installed). Each subdirectory
 * carries a `meta.json` plus a `SKILL.md` draft; a candidate whose status is
 * `candidate` is pending human review, `installed` means it was already
 * copied to an agent skill directory.
 * @param memsearchDir - the project's `.memsearch` directory.
 * @returns a stable array of candidate summaries (pending first, then name).
 */
function listSkillCandidates(memsearchDir) {
  const candidatesDir = join(memsearchDir, 'skill-candidates')
  let entries
  try {
    entries = readdirSync(candidatesDir, { withFileTypes: true })
  } catch {
    return []
  }
  const out = []
  for (const entry of entries) {
    if (!entry.isDirectory()) continue
    const metaPath = join(candidatesDir, entry.name, 'meta.json')
    let meta
    try {
      meta = JSON.parse(readFileSync(metaPath, 'utf-8'))
    } catch {
      continue // malformed or missing meta — not a candidate
    }
    out.push({
      name: meta.name || entry.name,
      status: meta.status || 'candidate',
      description: typeof meta.description === 'string' ? meta.description : '',
      occurrences: typeof meta.occurrences === 'number' ? meta.occurrences : 0,
      sources: Array.isArray(meta.sources) ? meta.sources : [],
      reason: typeof meta.reason === 'string' ? meta.reason : '',
      installedPaths: Array.isArray(meta.installed_paths) ? meta.installed_paths : [],
      updatedAt: meta.updated_at || meta.created_at || '',
    })
  }
  out.sort((a, b) => {
    const pa = a.status === 'candidate' ? 0 : 1
    const pb = b.status === 'candidate' ? 0 : 1
    return pa - pb || a.name.localeCompare(b.name)
  })
  return out
}

/**
 * Resolve the install target directory for a distilled skill on DSH.
 *
 * Mirrors the other platform plugins: the destination is the first entry of
 * `plugins.<agent>.memory_to_skill.paths` in memsearch config when the user
 * set one (relative entries resolve against the project dir); otherwise DSH's
 * default user-agents skill directory (`~/.agents/skills`), which the
 * `skill-filesystem` provider watches and loads automatically.
 */
function resolveSkillInstallTarget(memsearchCmd, projectDir) {
  const read = readMemsearchConfigValue(memsearchCmd, 'plugins.dsh.memory_to_skill.paths')
  if (read.ok && read.value) {
    try {
      const paths = JSON.parse(read.value)
      if (Array.isArray(paths) && paths.length > 0) {
        const first = String(paths[0])
        return join(first.startsWith('/') ? first : projectDir, first)
      }
    } catch { /* fall through to the DSH default */ }
  }
  return join(process.env.HOME || '', '.agents', 'skills')
}

/** Hard cap for read-file payloads (protects the browser from huge files). */
const READ_FILE_MAX_BYTES = 256 * 1024

/** File extensions the read-only preview may serve (text only). */
const TEXT_FILE_EXTS = new Set(['md', 'markdown', 'json', 'txt', 'toml', 'yml', 'yaml', 'sh', 'py', 'js', 'ts'])

/**
 * Resolve `rel` inside `root` and reject anything that escapes the root
 * (path traversal). Returns the absolute path or null.
 */
function safeJoinWithin(root, rel) {
  const abs = resolve(root, rel || '.')
  const rootResolved = resolve(root)
  return pathIsWithin(rootResolved, abs) ? abs : null
}

/** Return true when `target` is `root` or one of its descendants. */
function pathIsWithin(root, target) {
  const rel = relative(root, target)
  return rel === '' || (rel !== '..' && !rel.startsWith(`..${sep}`) && !isAbsolute(rel))
}

/**
 * Resolve symlinks for an existing candidate and reject targets outside the
 * real memory root. `undefined` means one of the paths does not exist.
 */
function realPathWithin(root, candidate) {
  try {
    const rootReal = realpathSync(root)
    const candidateReal = realpathSync(candidate)
    return pathIsWithin(rootReal, candidateReal) ? candidateReal : null
  } catch {
    return undefined
  }
}

/**
 * Register the browser-facing skill-review JSON routes on the web server.
 *
 * The memsearch plugin mounts early (base bundle layer), before the DSH web
 * server service is provided, so this must be called with the service already
 * available — `apply` retries until it is (see the wait loop) and headless
 * profiles never see it, so no routes are registered there.
 */
function registerSkillReviewRoutes(ctx, webServer, memsearchCmd) {
  const readJsonBody = (req) => new Promise((resolve) => {
    let body = ''
    req.on('data', (chunk) => { body += chunk })
    req.on('end', () => {
      try { resolve(JSON.parse(body || '{}')) } catch { resolve({}) }
    })
  })
  const sendJson = (res, status, payload) => {
    res.writeHead(status, { 'Content-Type': 'application/json; charset=utf-8' })
    res.end(JSON.stringify(payload))
  }
  // Project dir for a session id (its durable cwd), else the process cwd.
  // A long-lived web surface serves many projects, so we never assume the
  // boot dir is the only one (mirrors the capture path).
  const projectDirForSession = (sessionId) => {
    const agent = ctx.agents?.get?.(sessionId)
    return projectDirFor(agent?.session)
  }

  webServer.register({
    kind: 'exact',
    path: '/memsearch-dsh/skill-candidates',
    handler: (req, res) => {
      if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
      const sessionId = new URL(req.url, 'http://localhost').searchParams.get('sessionId')
      const projectDir = projectDirForSession(sessionId)
      const memoryDir = memsearchDirFor(projectDir)
      sendJson(res, 200, { candidates: listSkillCandidates(memoryDir) })
    },
  })

  webServer.register({
    kind: 'exact',
    path: '/memsearch-dsh/skill-review',
    handler: async (req, res) => {
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      const body = await readJsonBody(req)
      const { sessionId, name, action } = body
      if (!name || (action !== 'review' && action !== 'install')) {
        return sendJson(res, 400, { error: 'name and action (review|install) are required' })
      }
      if (action === 'review') {
        // Non-blocking: queue a user message into the live agent's inbox.
        // The agent picks it up on the next turn (never interrupts a running
        // turn, never asks the human via a blocking dialog).
        const agent = ctx.agents?.get?.(sessionId)
        if (!agent) {
          return sendJson(res, 404, { error: `no live agent for session ${sessionId}` })
        }
        const text =
          `[memsearch] Skill candidate "${name}" is ready for review.\n\n` +
          `Read the candidate at .memsearch/skill-candidates/${name}/ (SKILL.md plus meta.json), ` +
          `verify it against the cited memory journals, decide whether it is worth installing, ` +
          `and report your recommendation to the user. Installation stays a manual step: ` +
          `memsearch skills install ${name} --path <dir>.`
        const message = await createMemoryMessage(ctx, text)
        agent.inbox.append('next-turn', message)
        return sendJson(res, 200, { ok: true, action, name, injected: true })
      }
      // install: background `memsearch skills install` to the resolved target.
      // Detached + unref so the install survives the DSH process; the
      // skill-filesystem watcher picks up the new SKILL.md automatically.
      const projectDir = projectDirForSession(sessionId)
      const target = resolveSkillInstallTarget(memsearchCmd, projectDir)
      const command =
        `${memsearchCmd} skills install '${shellEscape(name)}' ` +
        `--path '${shellEscape(target)}'`
      const child = execFile('bash', ['-c', command], {
        cwd: projectDir,
        timeout: 60000,
        maxBuffer: 4 * 1024 * 1024,
        detached: true,
        stdio: 'ignore',
        env: { ...process.env, MEMSEARCH_NO_WATCH: '1' },
      }, (error) => {
        if (error) ctx.logger.warn(`[memsearch] skill install failed: ${error.message}`)
      })
      child.unref()
      return sendJson(res, 200, { ok: true, action, name, started: true, target })
    },
  })

  webServer.register({
    kind: 'exact',
    path: '/memsearch-dsh/open-memsearch',
    handler: async (req, res) => {
      if (req.method !== 'POST') return sendJson(res, 405, { error: 'method not allowed' })
      const body = await readJsonBody(req)
      const { sessionId, scope } = body // scope: 'memsearch' (default) | 'candidates'
      const projectDir = projectDirForSession(sessionId)
      const memsearchDir = memsearchDirFor(projectDir)
      const dir = scope === 'candidates' ? join(memsearchDir, 'skill-candidates') : memsearchDir
      if (!existsSync(dir)) {
        return sendJson(res, 404, { ok: false, error: `no such directory: ${dir}`, path: dir })
      }
      // Open the directory in the local file manager (xdg-open on Linux). The
      // response is success regardless of whether a desktop is present; the
      // path is returned so the client can show it if nothing opens.
      const child = execFile('xdg-open', [dir], {
        detached: true,
        stdio: 'ignore',
        timeout: 10000,
      }, (error) => {
        if (error) ctx.logger.warn(`[memsearch] open dir failed: ${error.message}`)
      })
      child.unref()
      return sendJson(res, 200, { ok: true, path: dir })
    },
  })

  webServer.register({
    kind: 'exact',
    path: '/memsearch-dsh/list-memsearch',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
      const sessionId = new URL(req.url, 'http://localhost').searchParams.get('sessionId')
      const relPath = new URL(req.url, 'http://localhost').searchParams.get('path') || ''
      const projectDir = projectDirForSession(sessionId)
      const memsearchDir = memsearchDirFor(projectDir)
      // Only ever list inside the project's .memsearch tree.
      const abs = safeJoinWithin(memsearchDir, relPath)
      if (abs === null) return sendJson(res, 400, { error: 'path outside .memsearch' })
      const realAbs = realPathWithin(memsearchDir, abs)
      if (realAbs === null) return sendJson(res, 400, { error: 'path outside .memsearch' })
      if (realAbs === undefined) {
        return sendJson(res, 404, { error: `no such directory: ${abs}`, path: abs })
      }
      let entries = []
      try {
        entries = readdirSync(realAbs, { withFileTypes: true })
      } catch {
        return sendJson(res, 404, { error: `no such directory: ${abs}`, path: abs })
      }
      const dirs = []
      const files = []
      for (const e of entries) {
        if (e.name.startsWith('.')) continue // skip hidden (e.g. .git inside candidates)
        if (e.isDirectory()) dirs.push(e.name)
        else if (e.isFile()) files.push(e.name)
      }
      dirs.sort()
      files.sort()
      sendJson(res, 200, {
        path: abs,
        rel: relPath,
        dirs,
        files,
      })
    },
  })

  webServer.register({
    kind: 'exact',
    path: '/memsearch-dsh/read-file',
    handler: async (req, res) => {
      if (req.method !== 'GET') return sendJson(res, 405, { error: 'method not allowed' })
      const sessionId = new URL(req.url, 'http://localhost').searchParams.get('sessionId')
      const relPath = new URL(req.url, 'http://localhost').searchParams.get('path') || ''
      const projectDir = projectDirForSession(sessionId)
      const memsearchDir = memsearchDirFor(projectDir)
      const abs = safeJoinWithin(memsearchDir, relPath)
      if (abs === null) return sendJson(res, 400, { error: 'path outside .memsearch' })
      const realAbs = realPathWithin(memsearchDir, abs)
      if (realAbs === null) return sendJson(res, 400, { error: 'path outside .memsearch' })
      if (realAbs === undefined) {
        return sendJson(res, 404, { error: `no such file: ${abs}`, path: abs })
      }
      let stat
      try {
        stat = statSync(realAbs)
      } catch {
        return sendJson(res, 404, { error: `no such file: ${abs}`, path: abs })
      }
      if (!stat.isFile()) return sendJson(res, 400, { error: 'not a file' })
      if (stat.size > READ_FILE_MAX_BYTES) {
        return sendJson(res, 413, { error: `file too large (${stat.size} bytes, max ${READ_FILE_MAX_BYTES})` })
      }
      const ext = extname(realAbs).slice(1).toLowerCase()
      if (!TEXT_FILE_EXTS.has(ext)) {
        return sendJson(res, 415, { error: `unsupported file type: .${ext}` })
      }
      let content
      try {
        content = readFileSync(realAbs, 'utf-8')
      } catch {
        return sendJson(res, 500, { error: 'read failed' })
      }
      sendJson(res, 200, { path: abs, rel: relPath, name: basename(abs), ext, content })
    },
  })
}

/** Compact human-readable memory block injected into the request. */
function renderMemoryBlock(chunks) {
  const lines = chunks.map((chunk, index) => {
    const source = chunk.source || 'memory'
    const snippet = (chunk.content || '').trim().replace(/\s+/g, ' ').slice(0, INJECT_SNIPPET_CHARS)
    return `${index + 1}. [${source}] ${snippet}`
  })
  return `${MEMSEARCH_MARKER}\n\nRelevant memories from past sessions:\n${lines.join('\n')}`
}

// ---------------------------------------------------------------------------
// Capture
// ---------------------------------------------------------------------------

/** Resolve the durable session artifact path for an anchor's `db:` field. */
function sessionLogPath(ctx, session) {
  try {
    const location = ctx.sessionPersistence?.locate?.(session?.header)
    if (location && typeof location.path === 'string' && location.path) {
      return location.path
    }
  } catch { /* leave empty */ }
  return ''
}

/**
 * Render one completed turn as `[User]`/`[Assistant]` text for the summarizer
 * (and as the raw body when summarization is disabled). Returns null when the
 * turn carries no genuine user message.
 */
function renderTurn(session, turnEndEvent) {
  const turn = turnEndEvent.data.turn
  const events = session.events
  const startIndex = events.findIndex(
    (event) => event.type === 'turn/start' && event.data.turn === turn,
  )
  if (startIndex < 0) return null
  const endIndex = events.findIndex(
    (event) => event.type === 'turn/end' && event.data.turn === turn,
  )
  const turnEvents = endIndex > startIndex ? events.slice(startIndex + 1, endIndex) : []

  const lines = [`=== Turn ${turn} ===`]
  let hasUser = false
  for (const event of turnEvents) {
    if (event.type === 'user/message') {
      if (event.data.source?.kind !== 'user') continue
      const text = textFromContent(event.data.content)
      if (!text) continue
      lines.push('', `[User]: ${text}`)
      hasUser = true
    } else if (event.type === 'assistant/message') {
      const text = textFromContent(event.data.message?.content)
      if (!text) continue
      lines.push('', `[Assistant]: ${text}`)
    } else if (event.type === 'tool/call') {
      lines.push('', `[Tool call]: ${event.data.name}`)
    }
  }
  if (!hasUser) return null
  const render = lines.join('\n').slice(0, CAPTURE_MAX_CHARS).trim()
  if (render.length <= 10) return null
  return render
}

/** True when a session/turn anchor already exists in any daily memory file. */
function captureExists(memoryDir, sessionId, turn) {
  let files
  try {
    files = readdirSync(memoryDir)
  } catch {
    return false
  }
  const anchor = `<!-- session:${sessionId} turn:${turn} `
  for (const file of files) {
    if (!DAILY_FILE_RE.test(file)) continue
    try {
      if (readFileSync(join(memoryDir, file), 'utf-8').includes(anchor)) return true
    } catch { /* skip unreadable file */ }
  }
  return false
}

/** Append a captured turn to the daily memory file (shared 4-platform format). */
function writeCapture(memoryDir, body, sessionId, turn, dbPath) {
  mkdirSync(memoryDir, { recursive: true })
  const today = todayStr()
  const hhmm = hhmmStr()
  const file = join(memoryDir, `${today}.md`)
  if (!existsSync(file)) {
    writeFileSync(file, `# ${today}\n\n## Session ${hhmm}\n\n`, 'utf-8')
  }
  const anchor = `<!-- session:${sessionId} turn:${turn} db:${dbPath} -->\n`
  const entry = `### ${hhmm}\n${anchor}${body}\n\n`
  appendFileSync(file, entry, 'utf-8')
}

// ---------------------------------------------------------------------------
// Summarization (two modes, selected by `summarizeMode`)
// ---------------------------------------------------------------------------

/**
 * Summarize one rendered turn via scripts/summarize.py — the memsearch-managed
 * `[llm.providers.*]` route (the `custom-llm` mode). Lightweight: a single
 * python process, no DSH boot. Model/provider come from memsearch config
 * (`[plugins.dsh.summarize]` → `[llm.providers.*]`), resolved by
 * `resolveSummarizeMode` into `opts.summarizeProvider` / `opts.summarizeModel`.
 */
function summarizeCustomLlm(opts, render, projectDir) {
  return new Promise((resolve, reject) => {
    const args = [
      join(PLUGIN_DIR, 'scripts', 'summarize.py'),
      '--agent-name', opts.agentName,
      '--project-dir', projectDir,
    ]
    if (opts.summarizeProvider) args.push('--provider', opts.summarizeProvider)
    if (opts.summarizeModel) args.push('--model', opts.summarizeModel)
    const child = spawn('python3', args, { cwd: projectDir })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (data) => { stdout += data })
    child.stderr.on('data', (data) => { stderr += data })
    child.on('error', reject)
    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout.trim() || null)
      } else {
        reject(new Error(stderr.trim() || `summarize.py exited with status ${code}`))
      }
    })
    child.stdin.write(render)
    child.stdin.end()
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL') } catch { /* already exited */ }
      reject(new Error('summarization timed out'))
    }, SUMMARIZE_TIMEOUT_MS)
    timer.unref?.()
  })
}

/**
 * Resolve the dsh CLI command for one-shot headless summarization.
 *
 * `dsh` may not be on PATH (it is a pnpm-installed workspace bin). We check
 * PATH first, then `DSH_CLI` as an explicit override, then the pnpm global
 * bin directory. Returns the command as an argv array (`[cmd, ...args]`),
 * or null when not found. The array form is required because `DSH_CLI` may
 * be an interpreter invocation (e.g. `node /path/to/bin.js`), which `spawn`
 * cannot treat as a single executable.
 */
function detectDshCmd() {
  const onPath = (cmd) => {
    try {
      execFileSync('bash', ['-c', `command -v ${cmd} >/dev/null 2>&1`], { stdio: 'pipe' })
      return true
    } catch {
      return false
    }
  }
  if (onPath('dsh')) return ['dsh']
  const fromEnv = process.env.DSH_CLI
  if (fromEnv) return fromEnv.split(/\s+/).filter(Boolean)
  const home = process.env.HOME || ''
  const pnpmBin = join(home, '.local', 'share', 'pnpm')
  if (existsSync(join(pnpmBin, 'dsh'))) return [join(pnpmBin, 'dsh')]
  return null
}

/**
 * Summarize one rendered turn by booting a one-shot DSH headless agent
 * (`dsh --profile headless`), mirroring how the Claude Code / Codex / OpenCode
 * plugins reuse their own agent's headless mode with a small model.
 *
 * The headless profile is the same one the user already has; the plugin does
 * not manage its bundles. The sub-agent's model is the deployment's
 * `agent-default-model` — which the user layer of `~/.dsh/settings.yaml`
 * (`agent-default-model:` section, the same selection the Web UI models
 * settings writes) overrides with highest priority. A `--patch` overlay on
 * `agent-default-model` sits below the user layer and is silently ignored
 * when the user document sets the section, so this mode intentionally does
 * NOT patch the model: the model is whatever the user configured in DSH
 * (Web UI model picker → `settings.yaml`). The `[plugins.dsh.summarize]`
 * provider/model therefore apply only to the `custom-llm` mode
 * (see `summarizeCustomLlm`).
 *
 * Recursion guard: the sub-agent is booted with `MEMSEARCH_DSH_SUMMARIZE=1`.
 * This plugin checks that flag in `apply()` and, when set, skips capture,
 * injection, and skill registration — so the summarizer's own session never
 * gets re-captured and re-summarized in an infinite loop.
 */
function summarizeHeadless(ctx, opts, render, projectDir) {
  return new Promise((resolve, reject) => {
    const dshCmd = detectDshCmd()
    if (!dshCmd) {
      reject(new Error('dsh CLI not found; set DSH_CLI or install dsh on PATH for summarizeMode=dsh-headless'))
      return
    }
    const promptFile = join(PLUGIN_DIR, 'prompts', 'summarize.txt')
    let systemPrompt
    try {
      systemPrompt = readFileSync(promptFile, 'utf-8').replaceAll('{{AGENT_NAME}}', opts.agentName)
    } catch {
      systemPrompt = `You are a third-person note-taker for {{AGENT_NAME}}. Record the following transcript as 2-10 bullet points in the same language as the [User] text. Output ONLY bullet points.`.replaceAll('{{AGENT_NAME}}', opts.agentName)
    }
    const task = `${systemPrompt}\n\nTranscript:\n${render}`

    const args = ['--profile', 'headless', task]

    const child = spawn(dshCmd[0], [...dshCmd.slice(1), ...args], {
      cwd: projectDir,
      env: { ...process.env, MEMSEARCH_DSH_SUMMARIZE: '1' },
    })
    let stdout = ''
    let stderr = ''
    child.stdout.on('data', (data) => { stdout += data })
    child.stderr.on('data', (data) => { stderr += data })
    child.on('error', (error) => {
      reject(error)
    })
    child.on('close', (code) => {
      if (code === 0) {
        resolve(stdout.trim() || null)
      } else {
        reject(new Error(stderr.trim() || `dsh headless summarize exited with status ${code}`))
      }
    })
    const timer = setTimeout(() => {
      try { child.kill('SIGKILL') } catch { /* already exited */ }
      reject(new Error('dsh headless summarization timed out'))
    }, SUMMARIZE_TIMEOUT_MS)
    timer.unref?.()
  })
}

/**
 * Run the configured summarizer for one turn.
 *
 * `opts.summarizeMode` is normally resolved by `apply()` via
 * `resolveSummarizeMode` (auto → custom-llm when a `[plugins.dsh.summarize]`
 * provider is configured, else dsh-headless). When called directly with an
 * unset mode (tests, external callers), the same auto resolution is applied
 * here. There is deliberately NO automatic fallback between modes: whichever
 * backend is resolved either produces a summary or fails visibly (the caller
 * writes the unavailable note) — a silent switch to an unconfigured LLM would
 * be worse than an honest failure.
 * @returns the summary text, or null when the summarizer produced nothing.
 */
async function summarizeTurn(ctx, opts, render, projectDir) {
  let { summarizeMode, summarizeProvider, summarizeModel } = opts
  if (summarizeMode !== 'custom-llm' && summarizeMode !== 'dsh-headless') {
    const resolved = resolveSummarizeMode(detectMemsearchCmd(), opts, {}, ctx.logger)
    summarizeMode = resolved.mode
    summarizeProvider = resolved.provider || summarizeProvider
    summarizeModel = resolved.model || summarizeModel
  }
  if (summarizeMode === 'custom-llm') {
    return await summarizeCustomLlm({ ...opts, summarizeMode, summarizeProvider, summarizeModel }, render, projectDir)
  }
  return await summarizeHeadless(ctx, { ...opts, summarizeMode, summarizeProvider, summarizeModel }, render, projectDir)
}

// ---------------------------------------------------------------------------
// Memory-recall skill
// ---------------------------------------------------------------------------

function registerMemoryRecallSkill(ctx, opts, memsearchCmd, collection, projectDir) {
  const skillPath = join(PLUGIN_DIR, 'skills', 'memory-recall', 'SKILL.md')
  let content
  try {
    content = readFileSync(skillPath, 'utf-8')
  } catch (error) {
    ctx.logger.warn(`[memsearch] could not read memory-recall skill: ${error.message}`)
    return
  }
  const agentName = opts.agentName
  content = content
    .replace(/^﻿?---[\s\S]*?---\s*/u, '') // strip optional YAML frontmatter
    .replace(/^<!--[\s\S]*?-->\s*/u, '') // strip the human-facing metadata comment
    .replaceAll('{{AGENT_NAME}}', agentName)
    .replaceAll('{{MEMSEARCH_CMD}}', memsearchCmd)
    .replaceAll('{{PLUGIN_DIR}}', PLUGIN_DIR)
    .replaceAll('{{PROJECT_DIR}}', projectDir)
    .replaceAll('{{COLLECTION}}', collection || `$(bash "${PLUGIN_DIR}/scripts/derive-collection.sh")`)
    .replaceAll('{{MILVUS_FLAG}}', opts.milvusUri ? `--milvus-uri "${opts.milvusUri}" ` : '')
  ctx.skills.register({
    name: 'memory-recall',
    description:
      'Search memsearch persistent memory for context relevant to the user\'s question. ' +
      'Use when the question could benefit from past sessions, decisions, or work in this project.',
    whenToUse:
      'The user references past work, asks what was done before, or the task could reuse ' +
      'earlier context. Cheap to check; costs one index search.',
    content,
    source: 'runtime',
    invocation: { modelInvocable: true, userInvocable: true },
  })
}

// ---------------------------------------------------------------------------
// Plugin entry
// ---------------------------------------------------------------------------

/**
 * Start the memsearch plugin on the DSH context.
 * @param ctx - the Cordis plugin context.
 * @param config - resolved patch config (see cordis.patch.yml).
 */
export function apply(ctx, config = {}) {
  // Recursion guard: when DSH booted this plugin as the summarizer's own
  // headless sub-agent (`summarizeMode: dsh-headless` sets this flag), stay
  // inert — no capture, no injection, no skill. Otherwise the summarizer's
  // session would itself be captured and re-summarized forever.
  if (process.env.MEMSEARCH_DSH_SUMMARIZE === '1') {
    ctx.logger?.debug?.('[memsearch] summarize sub-agent: plugin inert')
    return
  }

  const opts = {
    captureEnabled: config.captureEnabled !== false,
    injectEnabled: config.injectEnabled !== false,
    summarizeEnabled: config.summarizeEnabled !== false,
    summarizeMode: config.summarizeMode,
  }

  const memsearchCmd = detectMemsearchCmd()
  // Legacy plugin-config fields were removed in favor of memsearch config /
  // environment (aligned with the other platform plugins). A leftover field in
  // the profile patch is now ignored; warn once so an upgrade is not silent.
  const LEGACY_CONFIG_FIELDS = ['summarizeProvider', 'summarizeModel', 'memsearchDir', 'collection', 'milvusUri', 'agentName']
  const legacyField = LEGACY_CONFIG_FIELDS.find((field) => config[field] !== undefined)
  if (legacyField) {
    ctx.logger.warn(
      `[memsearch] config field '${legacyField}' is no longer used; provider/model/milvus/memory-dir now come from memsearch config (see README "Configuration")`,
    )
  }
  // Resolve the effective summarize backend now: explicit summarizeMode wins;
  // otherwise (auto) mirror the other plugins — a configured
  // [plugins.dsh.summarize] provider selects custom-llm, else dsh-headless.
  const resolvedSummarize = resolveSummarizeMode(memsearchCmd, opts, config, ctx.logger)
  opts.summarizeMode = resolvedSummarize.mode
  if (resolvedSummarize.provider) opts.summarizeProvider = resolvedSummarize.provider
  if (resolvedSummarize.model) opts.summarizeModel = resolvedSummarize.model
  // Everything below comes from memsearch config / environment, mirroring the
  // other platform plugins (no per-plugin config fields):
  //   - memory dir:   MEMSEARCH_DIR env (explicit → global scope), else <project>/.memsearch
  //   - collection:   derived from the project path (derive-collection.sh)
  //   - milvus:       memsearch config [milvus] uri (CLI reads it; we only
  //                   surface it for the skill's MILVUS_FLAG)
  //   - agent name:   fixed display name
  opts.agentName = DEFAULT_AGENT_NAME
  opts.milvusUri = readMemsearchConfigValue(memsearchCmd, 'milvus.uri').value || ''
  const memoryDirFor = (projectDir) => join(memsearchDirFor(projectDir), 'memory')

  const collectionCache = new Map()
  const bootProjectDir = process.cwd()
  const bootCollection = deriveCollection(bootProjectDir, '')

  const resolveCollection = (projectDir) => {
    if (collectionCache.has(projectDir)) return collectionCache.get(projectDir)
    const resolved = deriveCollection(projectDir, '')
    collectionCache.set(projectDir, resolved)
    return resolved
  }

  // --- Recall skill (always available) ---
  registerMemoryRecallSkill(ctx, opts, memsearchCmd, bootCollection, bootProjectDir)

  // --- Pre-step injection: relevant memory only, zero context otherwise ---
  ctx.on(
    'agent/pre-step',
    async ({ agent, turn, step, signal }, next) => {
      const decision = await next()
      if (!opts.injectEnabled) return decision
      if (decision.kind === 'reject' || signal.aborted) return decision
      if (step !== 1) return decision

      const question = (decision.messages || [])
        .map((message) => textFromContent(message.content))
        .find((text) => text.length > 0)
      if (!question || question.length < 3) return decision

      const projectDir = projectDirFor(agent.session)
      const memoryDir = memoryDirFor(projectDir)
      if (!hasMemoryFiles(memoryDir)) return decision

      const collection = resolveCollection(projectDir)
      if (!collection) return decision
      const chunks = await runSearch(memsearchCmd, question, collection, projectDir, opts.milvusUri)
      if (!chunks || chunks.length === 0) return decision

      const text = renderMemoryBlock(chunks)
      const memoryMessage = await createMemoryMessage(ctx, text)
      return {
        kind: 'enter',
        messages: [...decision.messages, memoryMessage],
      }
    },
    { prepend: true },
  )

  // --- Capture: summarize + write each completed turn, fire-and-forget ---
  // Each turn is processed against its *own* project directory (from
  // `session.header.cwd`), which on a long-lived web surface is not
  // necessarily `process.cwd()` — the boot directory. Turns are serialized
  // through a promise chain so LLM summarize calls never overlap, and the
  // `captureExists` dedup keeps a turn idempotent if its event replays.
  let captureChain = Promise.resolve()
  const enqueueCapture = (work) => {
    captureChain = captureChain
      .then(work)
      .catch((error) => ctx.logger.warn(`[memsearch] capture failed: ${error.message}`))
  }

  const processTurn = async (session, turnEndEvent) => {
    const projectDir = projectDirFor(session)
    const render = renderTurn(session, turnEndEvent)
    if (!render) return
    const sessionId = session.id
    const turn = turnEndEvent.data.turn
    const dbPath = sessionLogPath(ctx, session)
    const memoryDir = memoryDirFor(projectDir)
    if (captureExists(memoryDir, sessionId, turn)) return

    let body = render
    if (opts.summarizeEnabled) {
      try {
        const summary = await summarizeTurn(ctx, opts, render, projectDir)
        if (summary) {
          body = summary
        } else {
          ctx.logger.warn('[memsearch] summarizer returned empty output; wrote unavailable note')
          body = '- Memory summary unavailable: summarizer returned empty output. Use the transcript anchor for progressive disclosure.'
        }
      } catch (error) {
        // Collapse newlines so the reason stays a single `- ` bullet in the
        // daily file (summarize.py stderr can span lines).
        const reason = String(error.message).replace(/\s+/g, ' ').trim()
        ctx.logger.warn(`[memsearch] summarization failed (${reason}); wrote unavailable note`)
        body = `- Memory summary unavailable: ${reason}; transcript content was omitted. Use the transcript anchor for progressive disclosure.`
      }
    }
    writeCapture(memoryDir, body, sessionId, turn, dbPath)
    // Index right after the write so the memory is searchable by the next
    // session (or by this one's later turns) instead of waiting for a future
    // boot-time index. The index is idempotent via chunk_hash dedup.
    const collection = resolveCollection(projectDir)
    if (collection && hasMemoryFiles(memoryDir)) {
      indexMemory(ctx, memsearchCmd, memoryDir, collection, projectDir, opts.milvusUri)
    }
  }

  if (opts.captureEnabled) {
    ctx.on('session/event', (session, event) => {
      if (event.type !== 'turn/end') return
      try {
        enqueueCapture(() => processTurn(session, event))
      } catch (error) {
        ctx.logger.warn(`[memsearch] capture listener failed: ${error.message}`)
      }
    })
  }

  // Maintenance (PROJECT.md / USER.md upkeep, memory-to-skill distillation)
  // runs when a session is disposed (`session/disposed`), mirroring the other
  // platform plugins' session-end triggers. The runner is a due-state machine,
  // so this fires at most once per task per `min_interval_hours` and only for
  // tasks the user enabled in memsearch config. An explicit interval fallback
  // keeps upkeep going on long-lived web sessions that rarely dispose.
  const maintenanceTimer = setInterval(() => {
    try {
      const projectDir = bootProjectDir
      const memoryDir = memoryDirFor(projectDir)
      if (!existsSync(memoryDir)) return
      runMaintenance(ctx, projectDir, memoryDir)
    } catch (error) {
      ctx.logger.warn(`[memsearch] maintenance timer failed: ${error.message}`)
    }
  }, MAINTENANCE_INTERVAL_MS)
  maintenanceTimer.unref?.()

  ctx.on('session/disposed', (session) => {
    try {
      const projectDir = projectDirFor(session)
      const memoryDir = memoryDirFor(projectDir)
      if (!existsSync(memoryDir)) return
      runMaintenance(ctx, projectDir, memoryDir)
    } catch (error) {
      ctx.logger.warn(`[memsearch] maintenance listener failed: ${error.message}`)
    }
  })

  // --- Skill review panel: browser-facing JSON API (web only) ---
  // The memsearch plugin mounts in the base bundle layer, before the DSH web
  // server service exists. Retry until the service appears (web profile) or
  // give up silently (headless / tui profiles never provide it). The retry
  // timer is unref'd so it never keeps the process alive, and the routes are
  // registered exactly once.
  let skillReviewAttempted = false
  const tryRegisterSkillReview = () => {
    if (skillReviewAttempted) return
    const webServer = typeof ctx.get === 'function' ? ctx.get('webServer') : undefined
    if (webServer === undefined) return // not available yet; retry later
    skillReviewAttempted = true
    try {
      registerSkillReviewRoutes(ctx, webServer, memsearchCmd)
    } catch (error) {
      ctx.logger.warn(`[memsearch] skill-review route registration failed: ${error.message}`)
    }
  }
  tryRegisterSkillReview()
  const skillReviewTimer = setInterval(tryRegisterSkillReview, 1000)
  skillReviewTimer.unref?.()

  // Warm the index for this project once at startup (fire-and-forget).
  const bootMemoryDir = memoryDirFor(bootProjectDir)
  if (bootCollection && hasMemoryFiles(bootMemoryDir)) {
    indexMemory(ctx, memsearchCmd, bootMemoryDir, bootCollection, bootProjectDir)
  }
}

// ---------------------------------------------------------------------------
// Exports for tests / external use
// ---------------------------------------------------------------------------

/** Detect the dsh CLI command used by `summarizeMode: dsh-headless`. */
export { detectDshCmd }

/** One-shot DSH-headless summarizer (see README "dsh-headless" mode). */
export { summarizeHeadless }

/** Summarize one rendered turn with the configured backend. */
export { summarizeTurn }

/** Resolve the effective summarize backend (auto → config-driven). */
export { resolveSummarizeMode }

/** Read a dotted memsearch config value (tolerant of missing sections). */
export { readMemsearchConfigValue }

/** Render one turn's events into the shared transcript format. */
export { renderTurn }

/** True when a session/turn anchor already exists in the memory dir. */
export { captureExists }

/** Append a captured turn to the daily memory file (shared format). */
export { writeCapture }

/** Fire-and-forget maintenance runner invocation (PROJECT.md/USER.md/skills). */
export { runMaintenance }

/** Memory dir for a project (MEMSEARCH_DIR env override, else <project>/.memsearch). */
export { memsearchDirFor }

/** Read skill candidates from the `.memsearch/skill-candidates` directory. */
export { listSkillCandidates }

/** Register the skill-review JSON routes on a web server service. */
export { registerSkillReviewRoutes }

/** Resolve the distilled-skill install target (paths config, else ~/.agents/skills). */
export { resolveSkillInstallTarget }
