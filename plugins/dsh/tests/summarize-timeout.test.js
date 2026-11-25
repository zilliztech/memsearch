import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, writeFileSync, readFileSync, readdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { pathToFileURL } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

const plugin = process.env.MEMSEARCH_TEST_PLUGIN_ROOT
  ? pathToFileURL(join(process.env.MEMSEARCH_TEST_PLUGIN_ROOT, 'plugins/dsh/index.js')).href
  : new URL('../index.js', import.meta.url).href
const { apply } = await import(plugin)

async function waitFor(read) {
  for (let attempt = 0; attempt < 250; attempt++) {
    const result = read()
    if (result) return result
    await sleep(20)
  }
  assert.fail('capture did not finish within five seconds')
}

function fixture(t, mode, timeout, { accelerate = true, slow = true } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'memsearch summary timeout '))
  const home = join(root, 'home')
  const memoryDir = join(root, 'state', 'memory')
  const childFile = join(root, 'child.mjs')
  const callsFile = join(root, 'indexed.txt')
  const environment = { ...process.env }
  const cwd = process.cwd()
  mkdirSync(home)
  writeFileSync(childFile, `
    import { appendFileSync } from 'node:fs';
    const args = process.argv.slice(2);
    if (args[0] === 'core') {
      if (args[1] === 'index') appendFileSync(${JSON.stringify(callsFile)}, 'indexed\\n');
      process.exit(0);
    }
    if (args.includes('-c')) process.exit(0); // Python executable probe.
    process.stdin.resume();
    setTimeout(() => {
      process.stdout.write('- Saved cedar marker');
      process.exit(0);
    }, ${slow ? 10000 : 20});
  `)
  process.env.HOME = home
  process.env.USERPROFILE = home
  process.env.MEMSEARCH_DIR = join(root, 'state')
  process.env.MEMSEARCH_CMD = JSON.stringify([process.execPath, childFile, 'core'])
  process.env.DSH_CLI = JSON.stringify([process.execPath, childFile, 'summary'])
  process.env.MEMSEARCH_PYTHON = process.env.DSH_CLI
  delete process.env.MEMSEARCH_DSH_SUMMARIZE
  process.chdir(root)
  const intervals = []
  const originalInterval = globalThis.setInterval
  t.mock.method(globalThis, 'setInterval', (...args) => {
    const timer = originalInterval(...args)
    intervals.push(timer)
    return timer
  })
  const timeouts = []
  const originalTimeout = globalThis.setTimeout
  t.mock.method(globalThis, 'setTimeout', (callback, milliseconds, ...args) => {
    // Keep background index launches on their real budget, including Windows startup.
    const indexing = timeouts.length > 0 && milliseconds === 120000
    timeouts.push(milliseconds)
    // Observe the actual configured deadline without waiting thirty seconds.
    return originalTimeout(callback, accelerate && !indexing ? Math.min(milliseconds, 100) : milliseconds, ...args)
  })
  t.after(() => {
    for (const timer of intervals) clearInterval(timer)
    process.chdir(cwd)
    for (const key of Object.keys(process.env)) if (!(key in environment)) delete process.env[key]
    Object.assign(process.env, environment)
    rmSync(root, { recursive: true, force: true })
  })
  const listeners = {}
  apply({
    logger: { warn() {}, debug() {} },
    skills: { register() {}, registerProvider() {} },
    on: (name, listener) => { listeners[name] = listener },
  }, { summarizeMode: mode, summarizeTimeoutMs: timeout })
  const enqueue = turn => {
    const end = { type: 'turn/end', data: { turn } }
    return listeners['session/event']({
      id: 'timeout-session', header: { cwd: root }, events: [
        { type: 'turn/start', data: { turn } },
        { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'Remember the cedar marker.' }] } },
        end,
      ],
    }, end)
  }
  const journal = () => {
    try {
      return readdirSync(memoryDir).map(file => readFileSync(join(memoryDir, file), 'utf8')).join('')
    } catch { return '' }
  }
  const waitForIndex = count => waitFor(() => {
    try { return readFileSync(callsFile, 'utf8').trim().split('\n').length >= count } catch { return false }
  })
  return { enqueue, journal, timeouts, waitForIndex }
}

for (const mode of ['dsh-headless', 'custom-llm']) {
  test(`${mode}: apply honors summary timeout and retains the default for invalid values`, async t => {
    for (const [label, value, expected] of [
      ['missing', undefined, 30000], ['longer', 120000, 120000], ['shorter', 300, 300],
      ['boolean', true, 30000], ['string', '120000', 30000], ['null', null, 30000],
      ['zero', 0, 30000], ['negative', -1, 30000], ['fraction', 0.5, 30000],
      ['NaN', NaN, 30000], ['infinite', Infinity, 30000],
      ['timer limit', 2147483647, 2147483647], ['overflow', 2147483648, 30000],
    ]) {
      await t.test(label, async t => {
        const capture = fixture(t, mode, value)
        assert.equal(capture.enqueue(1), undefined, 'the chat event returns without waiting for summary')
        await waitFor(() => capture.journal().includes('Memory summary unavailable'))
        await capture.waitForIndex(1)
        assert.equal(capture.timeouts[0], expected)
        assert.match(capture.journal(), /timed out/)
        assert.match(capture.journal(), /session:timeout-session turn:1 /)
      })
    }
  })

  test(`${mode}: summary completes under a configured longer deadline`, async t => {
    const capture = fixture(t, mode, 120000, { accelerate: false, slow: false })
    capture.enqueue(1)
    await waitFor(() => capture.journal().includes('Saved cedar marker'))
    await capture.waitForIndex(1)
    assert.equal(capture.timeouts[0], 120000)
    assert.doesNotMatch(capture.journal(), /unavailable/)
  })

  test(`${mode}: a timed-out turn releases the queue for the next turn`, async t => {
    const capture = fixture(t, mode, 300)
    capture.enqueue(1)
    capture.enqueue(2)
    await waitFor(() => capture.journal().includes('turn:2 '))
    await capture.waitForIndex(2)
    const journal = capture.journal()
    assert.equal((journal.match(/Memory summary unavailable/g) || []).length, 2)
    assert.ok(journal.indexOf('turn:1 ') < journal.indexOf('turn:2 '))
  })
}
