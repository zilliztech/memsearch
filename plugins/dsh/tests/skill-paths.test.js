import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { resolveSkillInstallTarget } from '../index.js'

for (const [name, configured, homeRelative, suffix] of [
  ['bare home', '~', true],
  ['forward-slash home', '~/skills directory', true],
  ['forward-slash home with backslash component', '~/skills\\literal', true],
  ['backslash home', '~\\skills directory', process.platform === 'win32'],
  ['backslash home only', '~\\', process.platform === 'win32'],
  ['named user remains literal', '~someone/skills', false],
  ['repeated forward slashes', '~//skills directory', true, 'skills directory'],
  ['repeated backslashes', '~\\\\skills directory', process.platform === 'win32', 'skills directory'],
  ['mixed separators after home', '~/\\skills directory', true, process.platform === 'win32' ? 'skills directory' : '\\skills directory'],
  ['relative directory', './skills directory', false],
]) {
  test(`skill install path: ${name} follows native path semantics`, () => {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'memsearch skill paths '))
    try {
      const script = path.join(root, 'config.cjs')
      // Exercise the same JSON boundary as `memsearch config list --json-output`.
      fs.writeFileSync(script, `
        const assert = require('node:assert/strict')
        assert.deepEqual(process.argv.slice(2), ['config', 'list', '--json-output'])
        process.stdout.write(${JSON.stringify(JSON.stringify({
          plugins: { dsh: { memory_to_skill: { paths: [configured] } } },
        }))})
      `)
      const project = path.join(root, 'project')
      const expected = homeRelative
        ? path.resolve(os.homedir(), suffix ?? (configured === '~' ? '' : configured.slice(2)))
        : path.resolve(project, configured)
      assert.equal(resolveSkillInstallTarget([process.execPath, script], project), expected)
    } finally {
      fs.rmSync(root, { recursive: true, force: true })
    }
  })
}
