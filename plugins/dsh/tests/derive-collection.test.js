import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { createHash } from 'node:crypto'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

import { normalizeCollectionPath, deriveCollection } from '../index.js'

function withPlatform(platform, fn) {
  const original = Object.getOwnPropertyDescriptor(process, 'platform')
  Object.defineProperty(process, 'platform', { value: platform, configurable: true })
  try {
    return fn()
  } finally {
    Object.defineProperty(process, 'platform', original)
  }
}

const sha256First8 = value => createHash('sha256').update(value).digest('hex').slice(0, 8)

test('normalizeCollectionPath converts win32 backslash drive paths to the shared slash spelling', () => {
  withPlatform('win32', () => {
    assert.equal(normalizeCollectionPath('C:\\repo'), 'C:/repo')
    assert.equal(normalizeCollectionPath('C:\\a\\b\\c'), 'C:/a/b/c')
  })
})

test('normalizeCollectionPath is a no-op off Windows', () => {
  withPlatform('linux', () => {
    assert.equal(normalizeCollectionPath('C:\\repo'), 'C:\\repo')
    assert.equal(normalizeCollectionPath('/home/u/repo'), '/home/u/repo')
  })
})

test('normalized win32 hash input matches the bash-side canonical spelling (hooks common.sh #753)', () => {
  // What deriveCollection hashes on Windows after the fix vs what the
  // claude-code/codex hooks hash for the same checkout (both drive spellings
  // converge on `C:/...`, per tests/test_claude_hooks.py
  // test_plugin_common_keeps_win32_project_dir_absolute).
  const hashedByDsh = withPlatform('win32', () => sha256First8(normalizeCollectionPath('C:\\repo')))
  assert.equal(hashedByDsh, sha256First8('C:/repo'))
  // Pre-fix behavior hashed the raw native spelling and split collections.
  assert.notEqual(sha256First8('C:\\repo'), sha256First8('C:/repo'))
})

test('deriveCollection keeps exact parity with derive-collection.sh on this platform', () => {
  const root = fs.mkdtempSync(`${os.tmpdir()}/memsearch-dsh-parity-`)
  const projectDir = path.join(root, 'repo')
  fs.mkdirSync(projectDir)
  const script = path.resolve(import.meta.dirname, '../../claude-code/scripts/derive-collection.sh')
  const fromSh = execFileSync('bash', [script, projectDir], { encoding: 'utf-8' }).trim()
  const fromDsh = deriveCollection(projectDir, undefined)
  assert.equal(fromDsh, fromSh)
})
