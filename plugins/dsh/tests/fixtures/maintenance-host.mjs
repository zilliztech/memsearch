// Register the actual plugin in a minimal host; only registration and scheduling
// are simulated. The callback still uses runtime.js to spawn the Python runner.
import assert from 'node:assert/strict'
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
const { apply } = await import('../../index.js')
try {
  apply({
    logger: { warn(message) { warnings.push(message) } },
    skills: { register() {}, registerProvider() {} },
    on(name, callback) { listeners[name] = callback },
  }, { captureEnabled: false, summarizeEnabled: false })
} finally {
  globalThis.setInterval = originalInterval
}
const fire = process.env.MAINTENANCE_TEST_TRIGGER === 'timer'
  ? intervals.find(({ ms }) => ms === 6 * 60 * 60 * 1000)?.callback
  : () => listeners['session/disposed']({ header: { cwd: process.env.MAINTENANCE_TEST_SESSION } })
assert.equal(typeof fire, 'function', 'maintenance callback must be registered')
const launches = []
for (let n = 0; n < 2; n++) {
  fs.rmSync(process.env.MAINTENANCE_TEST_DONE, { force: true })
  fire()
  const deadline = Date.now() + 20000
  while (!fs.existsSync(process.env.MAINTENANCE_TEST_DONE) && Date.now() < deadline) await delay(20)
  assert.ok(fs.existsSync(process.env.MAINTENANCE_TEST_DONE), `runner did not finish: ${warnings}`)
  launches.push(JSON.parse(fs.readFileSync(process.env.MAINTENANCE_TEST_DONE, 'utf8')))
}
process.stdout.write(JSON.stringify({ launches, warnings }))
