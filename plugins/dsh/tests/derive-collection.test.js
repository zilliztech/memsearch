import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

import { deriveCollection } from '../index.js'
import { deriveCollectionNameFromScript } from '../../opencode/derive-collection.ts'

const scripts = ['claude-code', 'codex', 'dsh', 'opencode'].map(name =>
  fileURLToPath(new URL(`../../${name}/scripts/derive-collection.sh`, import.meta.url)))

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'memsearch collection '))
  t.after(() => fs.rmSync(root, { recursive: true, force: true }))
  return root
}

function fromShell(script, directory) {
  return execFileSync('bash', [script, directory], { encoding: 'utf8', timeout: 5000 }).trim()
}

test('native collection names match every shell helper for real project paths', t => {
  const root = fixture(t)
  const project = path.join(root, '项目 Spaced Project')
  fs.mkdirSync(project)
  const link = path.join(root, 'alias')
  fs.symlinkSync(project, link, process.platform === 'win32' ? 'junction' : 'dir')
  for (const directory of [project, link, `${link}${path.sep}..`, path.join(link, 'missing')]) {
    const expected = fromShell(scripts[0], directory)
    const shellPath = execFileSync('bash', ['-c', 'realpath -m "$1"', '_', directory], { encoding: 'utf8' }).trim()
    const resolved = fs.existsSync(directory) ? fs.realpathSync(directory) : directory
    assert.equal(deriveCollection(directory), expected, JSON.stringify({ directory, shellPath, resolved }))
    for (const script of scripts.slice(1)) assert.equal(fromShell(script, directory), expected, script)
    assert.equal(deriveCollectionNameFromScript(scripts[3], directory), expected)
  }
})

test('Windows drive spellings and OpenCode native fallback share the shell collection', { skip: process.platform !== 'win32' }, t => {
  const project = path.join(fixture(t), 'project')
  fs.mkdirSync(project)
  const expected = fromShell(scripts[0], project)
  const withoutBash = () => { throw new Error('Bash unavailable in this host') }
  for (const directory of [project, project.replaceAll('\\', '/')]) {
    assert.equal(deriveCollection(directory), expected)
    assert.equal(deriveCollectionNameFromScript(scripts[3], directory, withoutBash), expected)
  }
  const native = fs.realpathSync.native(project)
  const legacy = `ms_project_${createHash('sha256').update(native).digest('hex').slice(0, 8)}`
  assert.notEqual(legacy, expected, 'the old native Windows spelling split the collection')
})

test('explicit collection overrides remain unchanged', () => {
  assert.equal(deriveCollection('not-created', 'existing_collection'), 'existing_collection')
})

test('POSIX backslashes are preserved as filename characters', { skip: process.platform === 'win32' }, t => {
  const project = path.join(fixture(t), 'project\\part')
  fs.mkdirSync(project)
  assert.equal(deriveCollection(project), fromShell(scripts[0], project))
})

test('startup schedules existing journals for the current collection without rewriting them', t => {
  const root = fixture(t)
  const project = path.join(root, 'project')
  const memory = path.join(project, '.memsearch', 'memory')
  fs.mkdirSync(memory, { recursive: true })
  const journal = path.join(memory, '2026-11-19.md')
  const original = '# Existing memory\n\n- Keep cedar-852 for 47 minutes.\n'
  fs.writeFileSync(journal, original)
  const log = path.join(root, 'index-argv.json')
  const recorder = path.join(root, 'record-cli.mjs')
  fs.writeFileSync(recorder, `
    import fs from 'node:fs'
    const args = process.argv.slice(2)
    if (args[0] === 'index') fs.writeFileSync(process.env.INDEX_CALL_LOG, JSON.stringify(args))
  `)
  const source = `
    import fs from 'node:fs'
    import { setTimeout } from 'node:timers/promises'
    const { apply } = await import(process.env.TEST_PLUGIN_URL)
    apply({
      logger: { warn() {}, debug() {} },
      skills: { register() {}, registerProvider() {} },
      on() {},
    }, { captureEnabled: false, summarizeEnabled: false })
    const deadline = Date.now() + 10000
    while (!fs.existsSync(process.env.INDEX_CALL_LOG)) {
      if (Date.now() > deadline) throw new Error('Startup did not schedule indexing')
      await setTimeout(25)
    }
  `
  const env = { ...process.env, HOME: root, USERPROFILE: root,
    MEMSEARCH_CMD: JSON.stringify([process.execPath, recorder]), INDEX_CALL_LOG: log,
    TEST_PLUGIN_URL: pathToFileURL(fileURLToPath(new URL('../index.js', import.meta.url))).href }
  delete env.MEMSEARCH_DIR
  execFileSync(process.execPath, ['--input-type=module', '--eval', source], { cwd: project, env, timeout: 15000 })
  const args = JSON.parse(fs.readFileSync(log, 'utf8'))
  assert.deepEqual(args.slice(0, 2), ['index', memory])
  assert.equal(args[args.indexOf('--default-collection') + 1], deriveCollection(project))
  assert.ok(!args.includes('--force'))
  assert.equal(fs.readFileSync(journal, 'utf8'), original)
})
