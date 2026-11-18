import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

test('maintenance watchdog allows three sequential ten-minute calls', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'memsearch maintenance budget '))
  try {
    const command = path.join(root, 'command.cjs')
    const done = path.join(root, 'done')
    fs.writeFileSync(command, `
      if (process.argv[2]?.endsWith('maintenance-runner.py')) {
        // Accelerate elapsed time by 1000x; three nine-minute calls.
        setTimeout(() => require('node:fs').writeFileSync(process.env.BUDGET_DONE, 'done'), 3 * 540)
      }
    `)
    const script = `
      import fs from 'node:fs'
      import { setTimeout as delay } from 'node:timers/promises'
      const original = globalThis.setTimeout
      globalThis.setTimeout = (fn, ms, ...args) => original(fn, ms / 1000, ...args)
      const { runMaintenance } = await import(process.env.BUDGET_PLUGIN)
      const warnings = []
      runMaintenance({ logger: { warn(text) { warnings.push(text) } } }, process.cwd(), process.cwd())
      const deadline = Date.now() + 5000
      while (!fs.existsSync(process.env.BUDGET_DONE) && !warnings.length && Date.now() < deadline) await delay(20)
      await delay(50)
      process.stdout.write(JSON.stringify({ warnings, done: fs.existsSync(process.env.BUDGET_DONE) }))
    `
    const output = execFileSync(process.execPath, ['--input-type=module', '--eval', script], {
      cwd: root,
      env: {
        ...process.env,
        MEMSEARCH_PYTHON: JSON.stringify([process.execPath, command]),
        BUDGET_PLUGIN: new URL('../index.js', import.meta.url).href,
        BUDGET_DONE: done,
      },
      encoding: 'utf8', timeout: 10000,
    })
    assert.deepEqual(JSON.parse(output), { warnings: [], done: true })
  } finally {
    fs.rmSync(root, { recursive: true, force: true })
  }
})

for (const trigger of ['timer', 'session/disposed']) {
  for (const scope of ['project', 'custom', 'missing-memory']) {
    test(`maintenance ${trigger} uses the ${scope} root`, () => {
      const root = fs.mkdtempSync(path.join(os.tmpdir(), 'memsearch maintenance '))
      try {
        const boot = path.join(root, 'boot project')
        const session = path.join(root, 'session project')
        const project = trigger === 'timer' ? boot : session
        const memRoot = scope === 'custom'
          ? path.join(root, 'shared memory root') : path.join(project, '.memsearch')
        fs.mkdirSync(boot, { recursive: true })
        fs.mkdirSync(session, { recursive: true })
        if (scope !== 'missing-memory') fs.mkdirSync(path.join(memRoot, 'memory'), { recursive: true })
        const log = path.join(root, 'runner.json')
        const command = path.join(root, 'command.cjs')
        // Use the real runtime command parsing/spawning, without starting an LLM.
        fs.writeFileSync(command, `
          const fs = require('node:fs')
          const args = process.argv.slice(2)
          if (args[0]?.endsWith('maintenance-runner.py')) {
            fs.writeFileSync(process.env.MAINTENANCE_TEST_LOG, JSON.stringify({
              args, cwd: process.cwd(), noWatch: process.env.MEMSEARCH_NO_WATCH,
            }))
          }
        `)
        const child = `
          import fs from 'node:fs'
          import { setTimeout as delay } from 'node:timers/promises'
          const intervals = []
          const listeners = {}
          const warnings = []
          const originalInterval = globalThis.setInterval
          globalThis.setInterval = (callback, ms) => {
            intervals.push({ callback, ms })
            return { unref() {} }
          }
          const { apply } = await import(process.env.MAINTENANCE_TEST_PLUGIN)
          apply({
            logger: { warn(message) { warnings.push(message) } },
            skills: { register() {}, registerProvider() {} },
            on(name, callback) { listeners[name] = callback },
          }, { captureEnabled: false, summarizeEnabled: false })
          globalThis.setInterval = originalInterval
          if (process.env.MAINTENANCE_TEST_TRIGGER === 'timer') {
            const interval = intervals.find(({ ms }) => ms === 6 * 60 * 60 * 1000)
            if (!interval) throw new Error('maintenance timer not registered')
            interval.callback()
          } else {
            listeners['session/disposed']({ header: { cwd: process.env.MAINTENANCE_TEST_SESSION } })
          }
          const deadline = Date.now() + (process.env.MAINTENANCE_TEST_MISSING === '1' ? 200 : 5000)
          while (!fs.existsSync(process.env.MAINTENANCE_TEST_LOG) && Date.now() < deadline) await delay(10)
          process.stdout.write(JSON.stringify({ warnings }))
        `
        const env = {
          ...process.env,
          MEMSEARCH_CMD: JSON.stringify([process.execPath, command]),
          MEMSEARCH_PYTHON: JSON.stringify([process.execPath, command]),
          MAINTENANCE_TEST_LOG: log,
          MAINTENANCE_TEST_PLUGIN: new URL('../index.js', import.meta.url).href,
          MAINTENANCE_TEST_TRIGGER: trigger,
          MAINTENANCE_TEST_SESSION: session,
          MAINTENANCE_TEST_MISSING: scope === 'missing-memory' ? '1' : '0',
        }
        delete env.MEMSEARCH_DSH_SUMMARIZE
        delete env.MEMSEARCH_DIR
        if (scope === 'custom') env.MEMSEARCH_DIR = memRoot
        const stdout = execFileSync(process.execPath, ['--input-type=module', '--eval', child], {
          cwd: boot, env, encoding: 'utf-8', timeout: 15000,
        })
        assert.deepEqual(JSON.parse(stdout).warnings, [])
        if (scope === 'missing-memory') {
          assert.equal(fs.existsSync(log), false)
          assert.equal(fs.existsSync(memRoot), false)
          return
        }
        assert.ok(fs.existsSync(log), 'registered callback must launch the maintenance runner')
        const call = JSON.parse(fs.readFileSync(log, 'utf-8'))
        assert.equal(path.basename(call.args[0]), 'maintenance-runner.py')
        assert.deepEqual(call.args.slice(1), [
          '--platform', 'dsh', '--project-dir', project, '--memsearch-dir', memRoot,
        ])
        assert.equal(call.cwd, project)
        assert.equal(call.noWatch, '1')
      } finally {
        fs.rmSync(root, { recursive: true, force: true })
      }
    })
  }
}
