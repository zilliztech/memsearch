import test from 'node:test'
import assert from 'node:assert/strict'

import { withIsolatedEnv } from './env.js'

function restoreEnv(key, value) {
  if (value === undefined) delete process.env[key]
  else process.env[key] = value
}

test('withIsolatedEnv masks routing variables and restores them after failure', async () => {
  const key = `MEMSEARCH_DSH_TEST_${process.pid}`
  const beforeKey = process.env[key]
  const beforeCommand = process.env.MEMSEARCH_DSH_COMMAND_JSON
  process.env[key] = 'outside'
  process.env.MEMSEARCH_DSH_COMMAND_JSON = '["ambient-dsh"]'

  try {
    await assert.rejects(
      withIsolatedEnv({ [key]: 'inside' }, async () => {
        assert.equal(process.env[key], 'inside')
        assert.equal(process.env.MEMSEARCH_DSH_COMMAND_JSON, undefined)
        throw new Error('expected test failure')
      }),
      /expected test failure/,
    )
    assert.equal(process.env[key], 'outside')
    assert.equal(process.env.MEMSEARCH_DSH_COMMAND_JSON, '["ambient-dsh"]')
  } finally {
    restoreEnv(key, beforeKey)
    restoreEnv('MEMSEARCH_DSH_COMMAND_JSON', beforeCommand)
  }
})

test('withIsolatedEnv rejects overlapping process-global mutations', async () => {
  let release
  const gate = new Promise((resolve) => { release = resolve })
  const first = withIsolatedEnv({}, async () => { await gate })
  try {
    await assert.rejects(withIsolatedEnv({}, () => {}), /withIsolatedEnv overlap/)
  } finally {
    release()
    await first
  }
})
