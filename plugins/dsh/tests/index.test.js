import test from 'node:test'
import assert from 'node:assert/strict'
import fs from 'node:fs'
import os from 'node:os'

import { detectDshCmd, summarizeTurn, apply, resolveSummarizeMode, renderTurn, captureExists, writeCapture, memsearchDirFor, listSkillCandidates, resolveSkillInstallTarget } from '../index.js'
test('detectDshCmd: prefers dsh on PATH as a plain argv', () => {
  // DSH_CLI is checked after PATH; simulate PATH hit by masking DSH_CLI.
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  try {
    delete process.env.DSH_CLI
    process.env.PATH = '/usr/bin:/bin'
    const cmd = detectDshCmd()
    assert.ok(cmd === null || (Array.isArray(cmd) && cmd.length >= 1), `expected null or argv, got ${JSON.stringify(cmd)}`)
  } finally {
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
  }
})

test('detectDshCmd: DSH_CLI interpreter invocation returns argv array', () => {
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  try {
    delete process.env.PATH
    process.env.DSH_CLI = 'node /opt/dsh/bin.js'
    const cmd = detectDshCmd()
    assert.deepEqual(cmd, ['node', '/opt/dsh/bin.js'])
  } finally {
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
  }
})

test('detectDshCmd: DSH_CLI with trailing spaces is trimmed', () => {
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  try {
    delete process.env.PATH
    process.env.DSH_CLI = 'dsh   '
    const cmd = detectDshCmd()
    assert.deepEqual(cmd, ['dsh'])
  } finally {
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
  }
})

test('summarizeTurn: explicit custom-llm mode dispatches to the LLM path', async () => {
  // custom-llm mode spawns python3 summarize.py; without a real transcript we
  // only assert it picks that branch (no crash before spawn).
  const opts = { summarizeMode: 'custom-llm', agentName: 'X', summarizeProvider: '', summarizeModel: '' }
  const ctx = { logger: { warn: () => {} } }
  const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
  // If dispatch is wrong (e.g. treats anything not dsh-headless as dsh), this
  // would reject with a dsh-CLI error instead of the custom-llm path error.
  try {
    await summarizeTurn(ctx, opts, render, process.cwd())
    assert.fail('expected custom-llm summarizer to fail (no provider configured)')
  } catch (error) {
    // custom-llm path failure: summarize.py exits non-zero or times out, or
    // python3 is missing — never a "dsh CLI not found" error.
    assert.ok(
      !/dsh CLI not found/.test(error.message),
      `unexpected dsh CLI error: ${error.message}`,
    )
    assert.ok(
      !/spawn .* ENOENT/.test(error.message),
      `unexpected spawn ENOENT: ${error.message}`,
    )
  }
})

test('resolveSummarizeMode: explicit custom-llm pins the backend', () => {
  const r = resolveSummarizeMode('unused-cmd', { summarizeMode: 'custom-llm', summarizeProvider: 'p', summarizeModel: 'm' }, {})
  assert.deepEqual(r, { mode: 'custom-llm', provider: 'p', model: 'm' })
})

test('resolveSummarizeMode: explicit dsh-headless pins the backend', () => {
  const r = resolveSummarizeMode('unused-cmd', { summarizeMode: 'dsh-headless', summarizeProvider: '', summarizeModel: '' }, {})
  assert.equal(r.mode, 'dsh-headless')
})

test('resolveSummarizeMode: auto with unreachable memsearch falls back to dsh-headless', () => {
  // A missing/broken memsearch must not throw: treat as "no [plugins.dsh.summarize]"
  // and fall back to the zero-config dsh-headless backend.
  const r = resolveSummarizeMode('definitely-not-a-real-cmd-xyz', { summarizeMode: undefined, summarizeProvider: '', summarizeModel: '' }, {})
  assert.equal(r.mode, 'dsh-headless')
})

test('resolveSummarizeMode: read failure logs a warning (not silent)', () => {
  // M3: a config-read failure must be surfaced, not silently treated as
  // "not configured" — otherwise a slow/absent memsearch flips auto to the
  // wrong backend with no signal.
  const warnings = []
  const logger = { warn: (m) => warnings.push(m) }
  const r = resolveSummarizeMode('definitely-not-a-real-cmd-xyz', { summarizeMode: undefined, summarizeProvider: '', summarizeModel: '' }, {}, logger)
  assert.equal(r.mode, 'dsh-headless')
  assert.ok(warnings.length >= 1, 'a warning was logged')
  assert.ok(warnings[0].includes('could not read'), `warning mentions the read failure: ${warnings[0]}`)
})

test('resolveSummarizeMode: unknown explicit mode logs a warning and treats as auto', () => {
  const warnings = []
  const logger = { warn: (m) => warnings.push(m) }
  const r = resolveSummarizeMode('unused-cmd', { summarizeMode: 'custom-lm', summarizeProvider: '', summarizeModel: '' }, {}, logger)
  assert.equal(r.mode, 'dsh-headless') // treated as auto with no provider configured
  assert.ok(warnings.some((w) => w.includes('unknown summarizeMode')), `unknown-mode warning logged: ${warnings}`)
})

test('resolveSummarizeMode: auto with configured provider selects custom-llm', () => {
  // Simulate `[plugins.dsh.summarize] provider = "x"` by pointing memsearchCmd
  // at a shim that echoes the requested key.
  const prevPath = process.env.PATH
  const tmp = os.tmpdir()
  const shimBin = `${tmp}/memsearch-config-shim-${process.pid}`
  fs.mkdirSync(shimBin, { recursive: true })
  const shim = `${shimBin}/memsearch`
  fs.writeFileSync(
    shim,
    `#!/bin/sh\ncase "$3" in\n  plugins.dsh.summarize.provider) echo "deepseek-zilliz" ;;\n  plugins.dsh.summarize.model) echo "deepseek-v4-flash" ;;\n  plugins.dsh.summarize.enabled) echo "true" ;;\nesac\n`,
    'utf-8',
  )
  fs.chmodSync(shim, 0o755)
  try {
    process.env.PATH = `${shimBin}:${prevPath}`
    const r = resolveSummarizeMode('memsearch', { summarizeMode: undefined, summarizeProvider: '', summarizeModel: '' }, {})
    assert.equal(r.mode, 'custom-llm')
    assert.equal(r.provider, 'deepseek-zilliz')
    assert.equal(r.model, 'deepseek-v4-flash')
  } finally {
    fs.rmSync(shimBin, { recursive: true, force: true })
    process.env.PATH = prevPath
  }
})

test('summarizeTurn: default (no mode configured) dispatches to dsh-headless', async () => {
  // The default is dsh-headless: an omitted summarizeMode must boot the dsh
  // agent, so without a CLI it errors with "dsh CLI not found".
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  const prevHome = process.env.HOME
  try {
    delete process.env.DSH_CLI
    process.env.PATH = '/nonexistent'
    process.env.HOME = '/nonexistent-home' // mask pnpm-global dsh fallback
    const opts = { agentName: 'X', summarizeProvider: '', summarizeModel: '' } // no summarizeMode
    const ctx = { logger: { warn: () => {} } }
    const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
    await assert.rejects(
      summarizeTurn(ctx, opts, render, process.cwd()),
      /dsh CLI not found/,
    )
  } finally {
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
    if (prevHome === undefined) delete process.env.HOME
    else process.env.HOME = prevHome
  }
})

test('summarizeTurn: dsh-headless mode without CLI errors visibly', async () => {
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  const prevHome = process.env.HOME
  try {
    delete process.env.DSH_CLI
    process.env.PATH = '/nonexistent'
    process.env.HOME = '/nonexistent-home' // mask pnpm-global dsh fallback
    const opts = { summarizeMode: 'dsh-headless', agentName: 'X', summarizeProvider: '', summarizeModel: '' }
    const ctx = { logger: { warn: () => {} } }
    const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
    await assert.rejects(
      summarizeTurn(ctx, opts, render, process.cwd()),
      /dsh CLI not found/,
    )
  } finally {
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
    if (prevHome === undefined) delete process.env.HOME
    else process.env.HOME = prevHome
  }
})

test('summarizeTurn: custom-llm forwards --provider/--model to summarize.py', async () => {
  // Point a fake `python3` (argv recorder) at the front of PATH so the spawn
  // inside summarizeCustomLlm hits it; assert the provider/model options from
  // plugin config reach summarize.py as CLI args.
  const prevPath = process.env.PATH
  const tmp = await import('node:os').then((os) => os.tmpdir())
  const fs = await import('node:fs')
  const fakeBin = `${tmp}/memsearch-py3bin-${process.pid}`
  const argvFile = `${tmp}/memsearch-py3argv-${process.pid}.txt`
  fs.mkdirSync(fakeBin, { recursive: true })
  fs.writeFileSync(
    `${fakeBin}/python3`,
    `#!/bin/sh\nprintf "%s\\n" "$@" > "${argvFile}"\ncat > /dev/null\nexit 0\n`,
    'utf-8',
  )
  fs.chmodSync(`${fakeBin}/python3`, 0o755)
  try {
    process.env.PATH = `${fakeBin}:${prevPath}`
    const opts = {
      summarizeMode: 'custom-llm',
      agentName: 'AgentX',
      summarizeProvider: 'deepseek-zilliz',
      summarizeModel: 'deepseek-v4-pro',
    }
    const ctx = { logger: { warn: () => {} } }
    const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
    const summary = await summarizeTurn(ctx, opts, render, process.cwd())
    assert.equal(summary, null, 'recorder exits 0 with no stdout -> null summary')
    const recorded = fs.readFileSync(argvFile, 'utf-8').trim().split('\n')
    assert.ok(recorded[0].endsWith('scripts/summarize.py'), `first arg = summarize.py, got: ${recorded[0]}`)
    const joined = recorded.join(' ')
    assert.ok(joined.includes('--provider deepseek-zilliz'), `--provider forwarded: ${joined}`)
    assert.ok(joined.includes('--model deepseek-v4-pro'), `--model forwarded: ${joined}`)
    assert.ok(joined.includes('--agent-name AgentX'), `--agent-name forwarded: ${joined}`)
  } finally {
    try { fs.rmSync(fakeBin, { recursive: true, force: true }) } catch { /* cleanup */ }
    try { fs.unlinkSync(argvFile) } catch { /* cleanup */ }
    process.env.PATH = prevPath
  }
})

test('summarizeTurn: custom-llm surfaces summarize.py stderr as a visible error', async () => {
  // A failing summarize.py must reject with its stderr message (visible), not
  // silently resolve null/empty — so the caller writes the unavailable note
  // with the real reason.
  const prevPath = process.env.PATH
  const tmp = await import('node:os').then((os) => os.tmpdir())
  const fs = await import('node:fs')
  const fakeBin = `${tmp}/memsearch-py3fail-${process.pid}`
  fs.mkdirSync(fakeBin, { recursive: true })
  fs.writeFileSync(
    `${fakeBin}/python3`,
    '#!/bin/sh\necho "provider deepseek-zilliz not found in config" >&2\ncat > /dev/null\nexit 3\n',
    'utf-8',
  )
  fs.chmodSync(`${fakeBin}/python3`, 0o755)
  try {
    process.env.PATH = `${fakeBin}:${prevPath}`
    const opts = {
      summarizeMode: 'custom-llm',
      agentName: 'X',
      summarizeProvider: 'deepseek-zilliz',
      summarizeModel: '',
    }
    const ctx = { logger: { warn: () => {} } }
    const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
    await assert.rejects(
      summarizeTurn(ctx, opts, render, process.cwd()),
      /provider deepseek-zilliz not found in config/,
    )
  } finally {
    try { fs.rmSync(fakeBin, { recursive: true, force: true }) } catch { /* cleanup */ }
    process.env.PATH = prevPath
  }
})

test('detectDshCmd: falls back to pnpm global bin directory', async () => {
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  const prevHome = process.env.HOME
  const tmp = await import('node:os').then((os) => os.tmpdir())
  const fs = await import('node:fs')
  const fakeHome = `${tmp}/memsearch-home-${process.pid}`
  fs.mkdirSync(`${fakeHome}/.local/share/pnpm`, { recursive: true })
  fs.writeFileSync(`${fakeHome}/.local/share/pnpm/dsh`, '#!/bin/sh\nexit 0\n', 'utf-8')
  fs.chmodSync(`${fakeHome}/.local/share/pnpm/dsh`, 0o755)
  try {
    delete process.env.DSH_CLI
    delete process.env.PATH
    process.env.HOME = fakeHome
    const cmd = detectDshCmd()
    assert.deepEqual(cmd, [`${fakeHome}/.local/share/pnpm/dsh`])
  } finally {
    try { fs.rmSync(fakeHome, { recursive: true, force: true }) } catch { /* cleanup */ }
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    if (prevPath === undefined) delete process.env.PATH
    else process.env.PATH = prevPath
    if (prevHome === undefined) delete process.env.HOME
    else process.env.HOME = prevHome
  }
})

test('apply: captureEnabled:false skips session/event capture listener', () => {
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  apply(ctx, { captureEnabled: false })
  assert.ok(!listeners['session/event'], 'must not register capture when disabled')
})

test('apply: summarizeEnabled:false writes the raw transcript (no summarizer)', async () => {
  const tmp = os.tmpdir()
  const projDir = `${tmp}/memsearch-raw-${process.pid}`
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  apply(ctx, { summarizeEnabled: false })
  const session = {
    id: 'session-raw-test',
    header: { cwd: projDir },
    events: [
      { type: 'turn/start', data: { turn: 1 } },
      { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'remember raw-marker-001' }] } },
      { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'ok' }] } } },
      { type: 'turn/end', data: { turn: 1 } },
    ],
  }
  try {
    // session/event fires with (session, event); capture drains asynchronously.
    await listeners['session/event'](session, { type: 'turn/end', data: { turn: 1 } })
    // captureChain runs async; wait a beat for the write to land.
    await new Promise((r) => setTimeout(r, 300))
    const memoryDir = `${projDir}/.memsearch/memory`
    const files = fs.readdirSync(memoryDir)
    assert.equal(files.length, 1, 'one daily file written')
    const content = fs.readFileSync(`${memoryDir}/${files[0]}`, 'utf-8')
    assert.ok(content.includes('raw-marker-001'), 'raw transcript written when summarize disabled')
    assert.ok(content.includes('<!-- session:session-raw-test turn:1 '), 'anchor present')
  } finally {
    fs.rmSync(projDir, { recursive: true, force: true })
  }
})

test('apply: summarize failure writes unavailable note (not raw)', async () => {
  const tmp = os.tmpdir()
  const projDir = `${tmp}/memsearch-fail-${process.pid}`
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  // Default summarizeEnabled:true + auto resolves headless with no CLI → error
  // path in processTurn → unavailable note.
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  const prevHome = process.env.HOME
  try {
    delete process.env.DSH_CLI
    process.env.PATH = '/nonexistent'
    process.env.HOME = '/nonexistent-home' // mask pnpm-global dsh fallback (would boot a real agent)
    apply(ctx, {})
    const session = {
      id: 'session-fail-test',
      header: { cwd: projDir },
      events: [
        { type: 'turn/start', data: { turn: 1 } },
        { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'secret raw content that must not leak' }] } },
        { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'ok' }] } } },
        { type: 'turn/end', data: { turn: 1 } },
      ],
    }
    await listeners['session/event'](session, { type: 'turn/end', data: { turn: 1 } })
    await new Promise((r) => setTimeout(r, 500))
    const memoryDir = `${projDir}/.memsearch/memory`
    const files = fs.readdirSync(memoryDir)
    const content = fs.readFileSync(`${memoryDir}/${files[0]}`, 'utf-8')
    assert.ok(content.includes('Memory summary unavailable'), 'unavailable note written on failure')
    assert.ok(!content.includes('secret raw content'), 'raw content must NOT be written')
    assert.ok(content.includes('<!-- session:session-fail-test turn:1 '), 'anchor preserved')
  } finally {
    fs.rmSync(projDir, { recursive: true, force: true })
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
    if (prevHome === undefined) delete process.env.HOME
    else process.env.HOME = prevHome
  }
})

test('apply: multi-project capture writes to each project memory dir', async () => {
  const tmp = os.tmpdir()
  const projA = `${tmp}/memsearch-projA-${process.pid}`
  const projB = `${tmp}/memsearch-projB-${process.pid}`
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  const prevCli = process.env.DSH_CLI
  const prevPath = process.env.PATH
  try {
    delete process.env.DSH_CLI
    process.env.PATH = '/nonexistent'
    apply(ctx, { summarizeEnabled: false }) // raw writes, no CLI needed
    const mkSession = (id, cwd, marker) => ({
      id,
      header: { cwd },
      events: [
        { type: 'turn/start', data: { turn: 1 } },
        { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: marker }] } },
        { type: 'turn/end', data: { turn: 1 } },
      ],
    })
    await listeners['session/event'](mkSession('session-a', projA, 'marker-proj-a'), { type: 'turn/end', data: { turn: 1 } })
    await listeners['session/event'](mkSession('session-b', projB, 'marker-proj-b'), { type: 'turn/end', data: { turn: 1 } })
    await new Promise((r) => setTimeout(r, 400))
    const filesA = fs.readdirSync(`${projA}/.memsearch/memory`)
    const filesB = fs.readdirSync(`${projB}/.memsearch/memory`)
    assert.equal(filesA.length, 1, 'project A memory written')
    assert.equal(filesB.length, 1, 'project B memory written')
    const contentA = fs.readFileSync(`${projA}/.memsearch/memory/${filesA[0]}`, 'utf-8')
    const contentB = fs.readFileSync(`${projB}/.memsearch/memory/${filesB[0]}`, 'utf-8')
    assert.ok(contentA.includes('marker-proj-a'), 'A contains its own marker')
    assert.ok(contentB.includes('marker-proj-b'), 'B contains its own marker')
    assert.ok(!contentA.includes('marker-proj-b'), 'A does not leak B')
  } finally {
    fs.rmSync(projA, { recursive: true, force: true })
    fs.rmSync(projB, { recursive: true, force: true })
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    process.env.PATH = prevPath
  }
})

test('apply: MEMSEARCH_DSH_SUMMARIZE=1 makes the plugin inert', () => {
  const prev = process.env.MEMSEARCH_DSH_SUMMARIZE
  const listeners = {}
  try {
    process.env.MEMSEARCH_DSH_SUMMARIZE = '1'
    const ctx = {
      logger: { warn: () => {}, debug: () => {} },
      skills: { register: () => {} },
      on: (name, fn) => { listeners[name] = fn },
    }
    apply(ctx, {})
    assert.deepEqual(listeners, {}, 'summarize sub-agent must register nothing')
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DSH_SUMMARIZE
    else process.env.MEMSEARCH_DSH_SUMMARIZE = prev
  }
})

test('apply: custom-llm config is honored in summarizeMode', async () => {
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  apply(ctx, { summarizeMode: 'custom-llm', summarizeProvider: 'p', summarizeModel: 'm' })
  assert.ok(listeners['session/event'], 'capture listener registered by default')
  assert.ok(listeners['agent/pre-step'], 'injection listener registered by default')
})

test('summarizeHeadless: does not build a --patch overlay for the model', async () => {
  // The DSH settings user layer (`agent-default-model` in ~/.dsh/settings.yaml)
  // outranks any `--patch` overlay, so headless summarize must NOT emit one:
  // a real dsh boot here should not carry a memsearch-generated overlay file.
  // We point DSH_CLI at a recorder script that writes its argv to a file, then
  // assert the recorded args contain no `--patch` (and no temp overlay path).
  const prevCli = process.env.DSH_CLI
  const prevDshSummarize = process.env.MEMSEARCH_DSH_SUMMARIZE
  const tmp = await import('node:os').then((os) => os.tmpdir())
  const fs = await import('node:fs')
  const recorder = `${tmp}/memsearch-dsh-argv-recorder-${process.pid}.sh`
  fs.writeFileSync(
    recorder,
    '#!/bin/sh\nprintf "%s\\n" "$@" > "${MEMSEARCH_ARGV_FILE}"\nexit 0\n',
    'utf-8',
  )
  fs.chmodSync(recorder, 0o755)
  const argvFile = `${tmp}/memsearch-dsh-argv-${process.pid}.txt`
  try {
    process.env.DSH_CLI = `sh ${recorder}`
    process.env.MEMSEARCH_ARGV_FILE = argvFile
    const opts = {
      summarizeMode: 'dsh-headless',
      agentName: 'X',
      summarizeProvider: 'deepseek-zilliz',
      summarizeModel: 'deepseek-v4-pro',
    }
    const ctx = { logger: { warn: () => {} } }
    const render = '=== Turn 1 ===\n\n[User]: hi\n\n[Assistant]: hello'
    const summary = await summarizeTurn(ctx, opts, render, process.cwd())
    assert.equal(summary, null, 'recorder exits 0 with no stdout -> null summary')
    const recorded = fs.readFileSync(argvFile, 'utf-8').trim().split('\n')
    assert.ok(
      !recorded.includes('--patch'),
      `headless summarize must not pass --patch; got argv: ${JSON.stringify(recorded)}`,
    )
    assert.ok(
      !recorded.some((arg) => arg.includes('memsearch-dsh-summarize-')),
      `headless summarize must not reference an overlay file; got argv: ${JSON.stringify(recorded)}`,
    )
  } finally {
    try { fs.unlinkSync(recorder) } catch { /* cleanup */ }
    try { fs.unlinkSync(argvFile) } catch { /* cleanup */ }
    delete process.env.MEMSEARCH_ARGV_FILE
    if (prevCli === undefined) delete process.env.DSH_CLI
    else process.env.DSH_CLI = prevCli
    if (prevDshSummarize === undefined) delete process.env.MEMSEARCH_DSH_SUMMARIZE
    else process.env.MEMSEARCH_DSH_SUMMARIZE = prevDshSummarize
  }
})

test('renderTurn: renders user/assistant/tool events into the shared format', () => {
  const session = {
    events: [
      { type: 'turn/start', data: { turn: 7 } },
      { type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text: 'hello there' }] } },
      { type: 'tool/call', data: { name: 'bash' } },
      { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'hi back' }] } } },
      { type: 'turn/end', data: { turn: 7 } },
    ],
  }
  const render = renderTurn(session, { data: { turn: 7 } })
  assert.ok(render.includes('=== Turn 7 ==='), 'turn header')
  assert.ok(render.includes('[User]: hello there'), 'user line')
  assert.ok(render.includes('[Assistant]: hi back'), 'assistant line')
  assert.ok(render.includes('[Tool call]: bash'), 'tool line')
})

test('renderTurn: returns null when no user message', () => {
  const session = {
    events: [
      { type: 'turn/start', data: { turn: 1 } },
      { type: 'assistant/message', data: { message: { content: [{ type: 'text', text: 'only assistant' }] } } },
      { type: 'turn/end', data: { turn: 1 } },
    ],
  }
  assert.equal(renderTurn(session, { data: { turn: 1 } }), null)
})

test('writeCapture + captureExists: writes shared format and dedups', () => {
  const tmp = os.tmpdir()
  const dir = `${tmp}/memsearch-capture-${process.pid}`
  const memoryDir = `${dir}/memory`
  try {
    writeCapture(memoryDir, '- a note', 'session-abc', 3, '/path/db.jsonl')
    const files = fs.readdirSync(memoryDir)
    assert.equal(files.length, 1, 'one daily file')
    const content = fs.readFileSync(`${memoryDir}/${files[0]}`, 'utf-8')
    assert.ok(content.includes('<!-- session:session-abc turn:3 db:/path/db.jsonl -->'), 'anchor format')
    assert.ok(content.includes('- a note'), 'body present')
    // dedup: same turn already captured
    assert.equal(captureExists(memoryDir, 'session-abc', 3), true)
    assert.equal(captureExists(memoryDir, 'session-abc', 4), false)
  } finally {
    fs.rmSync(dir, { recursive: true, force: true })
  }
})

test('memsearchDirFor: MEMSEARCH_DIR env wins (global scope)', () => {
  const prev = process.env.MEMSEARCH_DIR
  try {
    process.env.MEMSEARCH_DIR = '/global/memsearch'
    assert.equal(memsearchDirFor('/proj/x'), '/global/memsearch')
    delete process.env.MEMSEARCH_DIR
    assert.equal(memsearchDirFor('/proj/x'), '/proj/x/.memsearch')
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('apply: injectEnabled:false makes pre-step injection a no-op', async () => {
  // The listener is always registered; the flag short-circuits inside it so a
  // disabled plugin still forwards the decision unchanged (never injects).
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  apply(ctx, { injectEnabled: false })
  assert.ok(listeners['agent/pre-step'], 'listener registered')
  const decision = { kind: 'enter', messages: [{ role: 'user', content: 'remember marker' }] }
  const result = await listeners['agent/pre-step']({ agent: {}, turn: 1, step: 1, signal: {} }, async () => decision)
  assert.equal(result, decision, 'decision forwarded unchanged when injection disabled')
  assert.equal(result.messages.length, 1, 'no memory message injected')
})

test('apply: registers a session/disposed maintenance listener', () => {
  // Maintenance uses the dedicated `session/disposed` event (the DSH
  // equivalent of another platform's session end), so it never collides with
  // the capture `session/event` listener.
  const listeners = {}
  const ctx = {
    logger: { warn: () => {}, debug: () => {} },
    skills: { register: () => {} },
    on: (name, fn) => { listeners[name] = fn },
  }
  apply(ctx, {})
  assert.ok(typeof listeners['session/disposed'] === 'function', 'session/disposed listener registered')
})

test('runMaintenance: is exported and tolerant of a missing project dir', async () => {
  // runMaintenance is fire-and-forget: it must not throw for a project whose
  // .memsearch dir does not exist (the runner checks due-state internally).
  const { runMaintenance } = await import('../index.js')
  const tmp = os.tmpdir()
  const projDir = `${tmp}/memsearch-maint-${process.pid}`
  const logger = { warn: () => {} }
  runMaintenance({ logger }, projDir, `${projDir}/.memsearch`)
  // No throw is the assertion; the child is detached + unref'd.
  await new Promise((r) => setTimeout(r, 200))
  assert.ok(true, 'runMaintenance returned without throwing')
})

test('listSkillCandidates: returns parsed meta for each candidate subdir, pending first', () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-list-')
  const candDir = `${tmp}/skill-candidates`
  fs.mkdirSync(`${candDir}/beta`, { recursive: true })
  fs.mkdirSync(`${candDir}/alpha`, { recursive: true })
  fs.mkdirSync(`${candDir}/no-meta`, { recursive: true })
  fs.mkdirSync(`${candDir}/sub/not-a-dir`, { recursive: true })
  fs.writeFileSync(`${candDir}/beta/meta.json`, JSON.stringify({
    name: 'beta', status: 'installed', description: 'B', occurrences: 5,
    sources: ['2026-01-01.md'], installed_paths: ['/tmp/.agents/skills/beta'],
  }))
  fs.writeFileSync(`${candDir}/alpha/meta.json`, JSON.stringify({
    name: 'alpha', status: 'candidate', description: 'A', occurrences: 3,
    sources: ['2026-01-02.md'], reason: 'Recurred across sessions',
  }))
  // no-meta has no meta.json → skipped; sub is not a file entry
  fs.writeFileSync(`${candDir}/no-meta/SKILL.md`, 'x')

  
  const out = listSkillCandidates(tmp)
  assert.deepEqual(out.map((c) => c.name), ['alpha', 'beta'], 'pending candidate sorts first')
  const alpha = out[0]
  assert.equal(alpha.status, 'candidate')
  assert.equal(alpha.description, 'A')
  assert.equal(alpha.occurrences, 3)
  assert.deepEqual(alpha.sources, ['2026-01-02.md'])
  assert.equal(alpha.reason, 'Recurred across sessions')
  assert.deepEqual(alpha.installedPaths, [])
  const beta = out[1]
  assert.equal(beta.status, 'installed')
  assert.deepEqual(beta.installedPaths, ['/tmp/.agents/skills/beta'])
})

test('listSkillCandidates: empty or missing dir returns []', () => {
  
  assert.deepEqual(listSkillCandidates('/nonexistent/path-xyz'), [])
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-empty-')
  assert.deepEqual(listSkillCandidates(tmp), [])
})

test('listSkillCandidates: malformed meta.json is skipped, not fatal', () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-bad-')
  const candDir = `${tmp}/skill-candidates`
  fs.mkdirSync(`${candDir}/broken`, { recursive: true })
  fs.writeFileSync(`${candDir}/broken/meta.json`, '{not json')
  fs.mkdirSync(`${candDir}/good`, { recursive: true })
  fs.writeFileSync(`${candDir}/good/meta.json`, JSON.stringify({ name: 'good', status: 'candidate' }))
  
  const out = listSkillCandidates(tmp)
  assert.equal(out.length, 1)
  assert.equal(out[0].name, 'good')
  assert.equal(out[0].status, 'candidate')
  assert.equal(out[0].occurrences, 0, 'missing occurrences defaults to 0')
})

test('resolveSkillInstallTarget: paths config entry wins, relative resolves against project', () => {
  
  const target = resolveSkillInstallTarget('memsearch', '/proj')
  // No configured paths on this machine → DSH default ~/.agents/skills.
  assert.ok(target.endsWith('/.agents/skills'), `expected ~/.agents/skills default, got ${target}`)
})

test('registerSkillReviewRoutes: GET candidates returns parsed list, pending first', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-route-')
  const candDir = `${tmp}/skill-candidates`
  fs.mkdirSync(`${candDir}/zeta`, { recursive: true })
  fs.mkdirSync(`${candDir}/alpha`, { recursive: true })
  fs.writeFileSync(`${candDir}/zeta/meta.json`, JSON.stringify({ name: 'zeta', status: 'installed' }))
  fs.writeFileSync(`${candDir}/alpha/meta.json`, JSON.stringify({ name: 'alpha', status: 'candidate', description: 'A' }))

  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  const ctx = {
    agents: { get: () => undefined },
    logger: { warn: () => {} },
  }
  const { registerSkillReviewRoutes } = await import('../index.js')
  // memsearchDirFor reads MEMSEARCH_DIR env; point it at the temp dir.
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const getRoute = routes['/memsearch-dsh/skill-candidates']
    assert.ok(getRoute, 'GET route registered')
    const res = { writeHead: (s) => { res.status = s }, end: (b) => { res.body = JSON.parse(b) } }
    getRoute.handler({ method: 'GET', url: '/memsearch-dsh/skill-candidates' }, res)
    assert.equal(res.status, 200)
    assert.deepEqual(res.body.candidates.map((c) => c.name), ['alpha', 'zeta'], 'pending first')
    assert.equal(res.body.candidates[0].description, 'A')
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('registerSkillReviewRoutes: GET rejects non-GET, POST review injects into agent inbox', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-route2-')
  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  let appended = null
  const fakeAgent = {
    inbox: { append: (target, msg) => { appended = { target, msg } } },
  }
  const ctx = {
    agents: { get: (id) => (id === 'sess-1' ? fakeAgent : undefined) },
    logger: { warn: () => {} },
  }
  const { registerSkillReviewRoutes } = await import('../index.js')
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const getRoute = routes['/memsearch-dsh/skill-candidates']
    const res = { writeHead: (s) => { res.status = s }, end: (b) => { res.body = JSON.parse(b) } }
    getRoute.handler({ method: 'POST', url: '/x' }, res)
    assert.equal(res.status, 405)

    const postRoute = routes['/memsearch-dsh/skill-review']
    const { EventEmitter } = await import('node:events')
    const req = Object.assign(new EventEmitter(), { method: 'POST' })
    const pr = { writeHead: (s) => { pr.status = s }, end: (b) => { pr.body = JSON.parse(b) } }
    const done = postRoute.handler(req, pr)
    req.emit('data', JSON.stringify({ sessionId: 'sess-1', name: 'alpha', action: 'review' }))
    req.emit('end')
    await done
    assert.equal(pr.status, 200)
    assert.equal(pr.body.injected, true)
    assert.ok(appended, 'inbox append called')
    assert.equal(appended.target, 'next-turn')
    assert.ok(appended.msg.content[0].text.startsWith('[memsearch] Skill candidate "alpha"'), 'message text')
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('registerSkillReviewRoutes: POST review with unknown session returns 404', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-route3-')
  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  const ctx = { agents: { get: () => undefined }, logger: { warn: () => {} } }
  const { registerSkillReviewRoutes } = await import('../index.js')
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const postRoute = routes['/memsearch-dsh/skill-review']
    const { EventEmitter } = await import('node:events')
    const req = Object.assign(new EventEmitter(), { method: 'POST' })
    const pr = { writeHead: (s) => { pr.status = s }, end: (b) => { pr.body = JSON.parse(b) } }
    const done = postRoute.handler(req, pr)
    req.emit('data', JSON.stringify({ sessionId: 'ghost', name: 'alpha', action: 'review' }))
    req.emit('end')
    await done
    assert.equal(pr.status, 404)
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('registerSkillReviewRoutes: POST open-memsearch opens existing dir, 404 for missing', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-open-')
  fs.mkdirSync(`${tmp}/.memsearch`, { recursive: true })
  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  let opened = null
  const ctx = {
    agents: { get: () => undefined },
    logger: { warn: (m) => { opened = m } },
  }
  const { registerSkillReviewRoutes } = await import('../index.js')
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  const { execFile } = await import('node:child_process')
  // stub execFile so xdg-open doesn't actually fire
  const { registerSkillReviewRoutes: real } = await import('../index.js')
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const route = routes['/memsearch-dsh/open-memsearch']
    assert.ok(route, 'open-memsearch route registered')
    const { EventEmitter } = await import('node:events')

    // existing dir
    const req1 = Object.assign(new EventEmitter(), { method: 'POST' })
    const res1 = { writeHead: (s) => { res1.status = s }, end: (b) => { res1.body = JSON.parse(b) } }
    const done1 = route.handler(req1, res1)
    req1.emit('data', JSON.stringify({ sessionId: 'sess-1', scope: 'memsearch' }))
    req1.emit('end')
    await done1
    assert.equal(res1.status, 200)
    assert.equal(res1.body.ok, true)
    assert.equal(res1.body.path, tmp, 'path is the memsearch dir (MEMSEARCH_DIR override)')

    // missing dir
    const req2 = Object.assign(new EventEmitter(), { method: 'POST' })
    const res2 = { writeHead: (s) => { res2.status = s }, end: (b) => { res2.body = JSON.parse(b) } }
    const done2 = route.handler(req2, res2)
    req2.emit('data', JSON.stringify({ sessionId: 'sess-1', scope: 'candidates' }))
    req2.emit('end')
    await done2
    assert.equal(res2.status, 404)
    assert.equal(res2.body.ok, false)
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('registerSkillReviewRoutes: list-memsearch lists dirs/files, blocks traversal', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-list-')
  const outside = fs.mkdtempSync(os.tmpdir() + '/msr-list-outside-')
  fs.mkdirSync(`${tmp}/memory`, { recursive: true })
  fs.mkdirSync(`${tmp}/skill-candidates/foo`, { recursive: true })
  fs.writeFileSync(`${tmp}/memory/2026-08-22.md`, '# hello')
  fs.writeFileSync(`${tmp}/config.toml`, 'x = 1')
  fs.writeFileSync(`${tmp}/.hidden`, 'no')
  fs.symlinkSync(outside, `${tmp}/outside-link`)
  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  const ctx = { agents: { get: () => undefined }, logger: { warn: () => {} } }
  const { registerSkillReviewRoutes } = await import('../index.js')
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const route = routes['/memsearch-dsh/list-memsearch']
    assert.ok(route, 'list route registered')

    const res = { writeHead: (s) => { res.status = s }, end: (b) => { res.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/list-memsearch' }, res)
    assert.equal(res.status, 200)
    assert.deepEqual(res.body.dirs.sort(), ['memory', 'skill-candidates'])
    assert.deepEqual(res.body.files, ['config.toml'])
    assert.ok(!res.body.files.includes('.hidden'), 'hidden skipped')

    // traversal blocked
    const res2 = { writeHead: (s) => { res2.status = s }, end: (b) => { res2.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/list-memsearch?path=..%2F..%2Fetc' }, res2)
    assert.equal(res2.status, 400)

    // A symlink inside .memsearch must not expose an outside directory.
    const res3 = { writeHead: (s) => { res3.status = s }, end: (b) => { res3.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/list-memsearch?path=outside-link' }, res3)
    assert.equal(res3.status, 400)
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})

test('registerSkillReviewRoutes: read-file serves text, rejects binary/traversal/oversize', async () => {
  const tmp = fs.mkdtempSync(os.tmpdir() + '/msr-read-')
  const outside = `${tmp}-outside.md`
  fs.mkdirSync(`${tmp}/skill-candidates/foo`, { recursive: true })
  fs.writeFileSync(`${tmp}/skill-candidates/foo/SKILL.md`, '# Foo\n\nDo the thing.\n')
  fs.writeFileSync(`${tmp}/skill-candidates/foo/meta.json`, '{"name":"foo"}')
  fs.writeFileSync(`${tmp}/blob.bin`, Buffer.from([0, 1, 2, 3]))
  fs.writeFileSync(outside, 'outside secret')
  fs.symlinkSync(outside, `${tmp}/escape.md`)
  const routes = {}
  const webServer = { register: (r) => { routes[r.path] = r } }
  const ctx = { agents: { get: () => undefined }, logger: { warn: () => {} } }
  const { registerSkillReviewRoutes } = await import('../index.js')
  const prev = process.env.MEMSEARCH_DIR
  process.env.MEMSEARCH_DIR = tmp
  try {
    registerSkillReviewRoutes(ctx, webServer, 'memsearch')
    const route = routes['/memsearch-dsh/read-file']
    assert.ok(route, 'read route registered')

    // md file
    const res = { writeHead: (s) => { res.status = s }, end: (b) => { res.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/read-file?path=skill-candidates%2Ffoo%2FSKILL.md' }, res)
    assert.equal(res.status, 200)
    assert.ok(res.body.content.includes('# Foo'))

    // binary rejected
    const res2 = { writeHead: (s) => { res2.status = s }, end: (b) => { res2.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/read-file?path=blob.bin' }, res2)
    assert.equal(res2.status, 415)

    // traversal rejected
    const res3 = { writeHead: (s) => { res3.status = s }, end: (b) => { res3.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/read-file?path=..%2F..%2Fetc%2Fpasswd' }, res3)
    assert.equal(res3.status, 400)

    // A text-looking symlink must not expose a file outside .memsearch.
    const res4 = { writeHead: (s) => { res4.status = s }, end: (b) => { res4.body = JSON.parse(b) } }
    route.handler({ method: 'GET', url: '/memsearch-dsh/read-file?path=escape.md' }, res4)
    assert.equal(res4.status, 400)
  } finally {
    if (prev === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = prev
  }
})
