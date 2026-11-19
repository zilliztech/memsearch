import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, writeFileSync, readFileSync, mkdirSync, rmSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { delimiter, join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { detectPythonCmd, execCommand, execCommandSync } from '../runtime.js'

const plugin = process.env.MEMSEARCH_RUNTIME_ROOT
  ? pathToFileURL(join(process.env.MEMSEARCH_RUNTIME_ROOT, 'plugins/dsh/index.js')).href
  : new URL('../index.js', import.meta.url).href
const { detectDshCmd, detectMemsearchCmd, deriveCollection, summarizeTurn, writeCapture } = await import(plugin)

function fixture(t) {
  const root = mkdtempSync(join(tmpdir(), 'memsearch runtime '))
  const environment = { ...process.env }
  t.after(() => {
    for (const name of Object.keys(process.env)) if (!(name in environment)) delete process.env[name]
    Object.assign(process.env, environment)
    rmSync(root, { recursive: true, force: true })
  })
  delete process.env.MEMSEARCH_PYTHON
  delete process.env.DSH_CLI
  delete process.env.MEMSEARCH_CMD
  return root
}

test('command discovery keeps existing home-directory fallbacks and explicit overrides', t => {
  const root = fixture(t)
  process.env.HOME = root
  process.env.USERPROFILE = root
  process.env.PATH = ''
  const launcher = (directory, name) => {
    mkdirSync(directory, { recursive: true })
    const windows = process.platform === 'win32'
    const file = join(directory, name + (windows ? '.cmd' : ''))
    writeFileSync(file, windows ? '@exit /b 0\r\n' : '#!/bin/sh\nexit 0\n', { mode: 0o755 })
    return file
  }
  const dsh = launcher(join(root, '.local', 'share', 'pnpm'), 'dsh')
  const uvx = launcher(join(root, '.local', 'bin'), 'uvx')
  const uvxArgs = ['--from', 'memsearch[onnx]', 'memsearch']
  assert.deepEqual(detectDshCmd(), [dsh])
  assert.deepEqual(detectMemsearchCmd(), [uvx, ...uvxArgs])

  const bin = join(root, 'path bin')
  const pathDsh = launcher(bin, 'dsh')
  const pathUvx = launcher(bin, 'uvx')
  process.env.PATH = bin
  assert.deepEqual(detectDshCmd(), [pathDsh])
  assert.deepEqual(detectMemsearchCmd(), [uvx, ...uvxArgs])
  rmSync(uvx)
  assert.deepEqual(detectMemsearchCmd(), [pathUvx, ...uvxArgs])
  const memsearch = launcher(bin, 'memsearch')
  assert.deepEqual(detectMemsearchCmd(), [memsearch])

  process.env.DSH_CLI = JSON.stringify([dsh, '--profile', 'custom'])
  process.env.MEMSEARCH_CMD = JSON.stringify([join(root, 'explicit-memsearch')])
  assert.deepEqual(detectDshCmd(), [dsh, '--profile', 'custom'])
  assert.deepEqual(detectMemsearchCmd(), [join(root, 'explicit-memsearch')])
})

test('headless summary uses the explicitly quoted CLI and writes Unicode memory', async t => {
  const root = fixture(t)
  const recorder = join(root, 'summary fixture.mjs')
  writeFileSync(recorder, "process.stdin.resume(); process.stdin.on('end', () => process.stdout.write('- 会议决定：周五发布 😀'))")
  process.env.DSH_CLI = `"${process.execPath}" "${recorder}"`
  const summary = await summarizeTurn({}, { summarizeMode: 'dsh-headless', agentName: 'Test' }, '中文对话', root)
  assert.equal(summary, '- 会议决定：周五发布 😀')
  const memory = join(root, 'memory')
  writeCapture(memory, summary, 'runtime-session', 1, join(root, 'session.jsonl'))
  const day = new Date().toISOString().slice(0, 10)
  assert.match(readFileSync(join(memory, `${day}.md`), 'utf8'), /会议决定：周五发布 😀/)
})

test('Windows Desktop cmd launcher preserves arguments and explicit selection', { skip: process.platform !== 'win32' }, async t => {
  const root = fixture(t)
  const recorder = join(root, 'record argv.mjs')
  const output = join(root, 'argv.json')
  writeFileSync(recorder, "import fs from 'node:fs'; let input=''; process.stdin.setEncoding('utf8'); process.stdin.on('data', part => input+=part); process.stdin.on('end', () => { fs.writeFileSync(process.env.DSH_TEST_ARGV, JSON.stringify({argv:process.argv.slice(2),input})); process.stdout.write('- Fixed summary') })")
  const launcher = join(root, 'dsh.cmd')
  writeFileSync(launcher, `@echo off\r\nsetlocal DisableDelayedExpansion\r\n"${process.execPath}" "${recorder}" %*\r\nexit /b %errorlevel%\r\n`)
  process.env.DSH_TEST_ARGV = output
  process.env.PATH = `${root}${delimiter}${process.env.PATH}`
  assert.deepEqual(detectDshCmd(), [launcher])
  process.env.DSH_CLI = `"${launcher}"`
  const transcript = 'word '.repeat(1180) + '中文 "quoted" & echo SHOULD_NOT_RUN | %PATH% !literal! ^caret^ (group)\nnext line'
  assert.equal(await summarizeTurn({}, { summarizeMode: 'dsh-headless', agentName: 'Test' }, transcript, root), '- Fixed summary')
  const result = JSON.parse(readFileSync(output, 'utf8'))
  assert.deepEqual(result.argv, ['--profile', 'headless'])
  assert.ok(result.input.endsWith(`Transcript:\n${transcript}`), JSON.stringify(result))
})

test('Python discovery rejects an unusable alias and respects an explicit override', t => {
  const root = fixture(t)
  const realPython = detectPythonCmd()
  assert.ok(realPython, 'test runner must provide Python 3')
  const interpreter = execCommandSync(realPython, ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim()
  const windows = process.platform === 'win32'
  writeFileSync(join(root, windows ? 'python3.cmd' : 'python3'), windows ? '@exit /b 9009\r\n' : '#!/bin/sh\nexit 127\n', { mode: 0o755 })
  writeFileSync(join(root, windows ? 'python.cmd' : 'python'), windows
    ? `@echo off\r\n"${interpreter}" %*\r\nexit /b %errorlevel%\r\n`
    : `#!/bin/sh\nexec "${interpreter}" "$@"\n`, { mode: 0o755 })
  process.env.PATH = `${root}${delimiter}${process.env.PATH}`
  const selected = detectPythonCmd()
  assert.equal(selected[0], join(root, windows ? 'python.cmd' : 'python'))
  assert.equal(execCommandSync(selected, ['-c', 'print("python-ok")'], { encoding: 'utf8' }).trim(), 'python-ok')
  process.env.MEMSEARCH_PYTHON = join(root, 'missing-python')
  assert.equal(detectPythonCmd(), null)
})

test('collection derivation preserves Linux names including symlinked missing paths', { skip: process.platform !== 'linux' }, t => {
  const root = fixture(t)
  const target = join(root, 'physical', 'Actual Project')
  mkdirSync(target, { recursive: true })
  symlinkSync(target, join(root, 'link'))
  for (const directory of [target, join(root, 'link'), `${root}/link/..`, `${root}/link/../missing`, join(root, 'link', 'not-created'), join(root, '中文 Project')]) {
    const expected = execFileSync('bash', [new URL('../scripts/derive-collection.sh', import.meta.url).pathname, directory], { encoding: 'utf8' }).trim()
    assert.equal(deriveCollection(directory), expected)
  }
})


test('command timeout rejects and terminates descendants holding its output pipe', async t => {
  const root = fixture(t)
  const script = join(root, 'waiting child.mjs')
  writeFileSync(script, `import {spawn} from 'node:child_process';
    spawn(process.execPath, ['-e', 'setInterval(()=>{}, 1000)'], {stdio:'inherit'});
    process.on('SIGTERM', () => {process.stdout.write('partial'); process.exit(0)});
    setInterval(()=>{}, 1000)`)
  const started = Date.now()
  await new Promise((resolve, reject) => {
    execCommand([process.execPath, script], [], {timeout: 200}, (error) => {
      try { assert.match(error?.message || '', /timed out/); resolve() } catch (caught) { reject(caught) }
    })
  })
  assert.ok(Date.now() - started < 5000, 'timeout must not wait for a surviving descendant')
})
