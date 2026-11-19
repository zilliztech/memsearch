import { execFileSync } from 'node:child_process'
import { accessSync, constants, existsSync, statSync } from 'node:fs'
import { delimiter, extname, isAbsolute, join, resolve } from 'node:path'
import spawn from 'cross-spawn'

/** Resolve only the supplied path or directories explicitly present on PATH. */
export function findExecutable(command) {
  const extensions = process.platform === 'win32' && !extname(command)
    ? (process.env.PATHEXT || '.COM;.EXE;.BAT;.CMD').split(';').filter(Boolean)
    : ['']
  const directories = isAbsolute(command) || /[/\\]/.test(command)
    ? [''] : (process.env.PATH || '').split(delimiter).filter(Boolean)
  for (const directory of directories) {
    const base = directory ? join(directory.replace(/^"|"$/g, ''), command) : command
    for (const extension of extensions) {
      const candidate = base + extension.toLowerCase()
      try {
        accessSync(candidate, constants.X_OK)
        if (statSync(candidate).isFile()) return resolve(candidate)
      } catch { /* Try the next configured directory. */ }
    }
  }
  return null
}

/** Accept an executable path, quoted command line, or explicit JSON argv. */
export function parseCommand(value, setting = 'command') {
  if (Array.isArray(value)) return value
  const text = String(value).trim()
  if (existsSync(text)) return [text]
  if (text.startsWith('[')) {
    let argv
    try { argv = JSON.parse(text) } catch { /* Report below. */ }
    if (Array.isArray(argv) && argv.length && argv[0] && argv.every(arg => typeof arg === 'string')) return argv
    throw new Error(`${setting} must be a nonempty JSON argument array`)
  }
  const argv = []
  const token = /\s*(?:"([^"]*)"|'([^']*)'|([^\s'"]+))/y
  while (token.lastIndex < text.length) {
    const match = token.exec(text)
    if (!match) throw new Error(`${setting} has unmatched quotes; quote paths containing spaces`)
    argv.push(match[1] ?? match[2] ?? match[3])
  }
  if (!argv[0]) throw new Error(`${setting} must specify an executable`)
  return argv
}

/** cross-spawn handles Windows command shims and escaping their arguments. */
export function spawnCommand(command, args = [], options = {}) {
  const [file, ...prefix] = parseCommand(command)
  const { timeout, ...spawnOptions } = options
  const child = spawn(file, [...prefix, ...args], { windowsHide: true, ...spawnOptions })
  if (timeout) {
    const timer = setTimeout(() => {
      child.timedOut = true
      killProcessTree(child)
    }, timeout)
    timer.unref()
    child.once('close', () => clearTimeout(timer))
  }
  return child
}

/** Terminate a command and its descendants, including Windows batch launchers. */
export function killProcessTree(child) {
  if (!child.pid) return
  if (process.platform === 'win32') {
    try {
      execFileSync('taskkill', ['/pid', String(child.pid), '/t', '/f'], { stdio: 'ignore', windowsHide: true })
      return
    } catch { /* Fall back to the direct child. */ }
  } else {
    try {
      process.kill(-child.pid, 'SIGKILL')
      return
    } catch { /* Fall back to the direct child. */ }
  }
  try { child.kill('SIGKILL') } catch { /* Already exited. */ }
}

export function execCommandSync(command, args, options = {}) {
  const [file, ...prefix] = parseCommand(command)
  const result = spawn.sync(file, [...prefix, ...args], { windowsHide: true, ...options })
  if (result.error) throw result.error
  if (result.status !== 0) {
    const error = new Error(String(result.stderr || `${file} exited with status ${result.status}`))
    error.status = result.status
    error.stderr = result.stderr
    throw error
  }
  return result.stdout
}

/** Bounded output collection for the existing CLI callbacks. */
export function execCommand(command, args, options, callback) {
  const child = spawnCommand(command, args, { detached: process.platform !== 'win32', ...options })
  let stdout = ''
  let stderr = ''
  let error = null
  let bytes = 0
  const collect = (target, chunk) => {
    if (error) return
    bytes += Buffer.byteLength(chunk)
    if (bytes > (options.maxBuffer ?? 4 * 1024 * 1024)) {
      error = new Error('command output exceeded its buffer limit')
      killProcessTree(child)
      return
    }
    if (target === 'stdout') stdout += chunk
    else stderr += chunk
  }
  child.stdout?.setEncoding('utf8').on('data', chunk => collect('stdout', chunk))
  child.stderr?.setEncoding('utf8').on('data', chunk => collect('stderr', chunk))
  child.on('error', caught => { error = caught })
  child.on('close', (code, signal) => {
    callback(error || (child.timedOut ? new Error('command timed out') : null) ||
      (code === 0 ? null : new Error(stderr.trim() || `command exited with ${signal || code}`)), stdout, stderr)
  })
  return child
}

/** Test Python 3 availability once per plugin environment, including Store aliases. */
let pythonCache = null
export function detectPythonCmd() {
  const key = JSON.stringify([process.env.MEMSEARCH_PYTHON, process.env.PATH, process.env.PATHEXT])
  if (pythonCache?.key === key) return pythonCache.command
  const explicit = process.env.MEMSEARCH_PYTHON
  const candidates = explicit
    ? [parseCommand(explicit, 'MEMSEARCH_PYTHON')]
    : [['python3'], ['python'], ['py', '-3']]
  for (const candidate of candidates) {
    const executable = findExecutable(candidate[0])
    if (!executable) continue
    const command = [executable, ...candidate.slice(1)]
    try {
      execCommandSync(command, ['-c', 'import sys; sys.exit(sys.version_info[0] != 3)'], { timeout: 3000, stdio: 'ignore' })
      pythonCache = { key, command }
      return command
    } catch { /* Try another standard name, unless the user pinned this one. */ }
  }
  pythonCache = { key, command: null }
  return null
}

/** Render commands for the host shell used by the recall skill. */
export function commandForSkill(command) {
  const argv = parseCommand(command)
  const quote = value => `'${value.replace(/'/g, process.platform === 'win32' ? "''" : "'\\''")}'`
  return (process.platform === 'win32' ? '& ' : '') + argv.map(quote).join(' ')
}
