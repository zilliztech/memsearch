import test from 'node:test'
import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

// Run with `uv run --project ../.. npm run test:integration` so this interpreter
// has the real memsearch core. Missing dependencies fail rather than skip CI.
const python = execFileSync('python', ['-c', 'import sys; print(sys.executable)'], { encoding: 'utf8' }).trim()
const driver = fileURLToPath(new URL('./fixtures/maintenance-runner.py', import.meta.url))
const host = fileURLToPath(new URL('./fixtures/maintenance-host.mjs', import.meta.url))

for (const trigger of ['timer', 'session/disposed']) {
  for (const scope of ['project', 'custom']) {
    test(`maintenance ${trigger} persists state beside index state (${scope})`, () => {
      const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), 'memsearch integration ')))
      try {
        const boot = path.join(root, 'boot project')
        const session = path.join(root, 'session project')
        const project = trigger === 'timer' ? boot : session
        const memRoot = scope === 'custom'
          ? path.join(root, 'custom memory root') : path.join(project, '.memsearch')
        const home = path.join(root, 'home')
        const memory = path.join(memRoot, 'memory')
        for (const directory of [boot, session, memory, path.join(home, '.memsearch')]) {
          fs.mkdirSync(directory, { recursive: true })
        }
        fs.writeFileSync(path.join(memory, '2026-01-01.md'), '### 12:00\nJOURNAL_SENTINEL_832\n')
        fs.writeFileSync(path.join(home, '.memsearch', 'config.toml'),
          '[plugins.dsh.project_review]\nenabled = true\nprovider = "native"\nmin_interval_hours = 0\n')
        const fakeCli = path.join(root, 'unused-cli.cjs')
        fs.writeFileSync(fakeCli, '')
        const env = {
          ...process.env,
          HOME: home,
          USERPROFILE: home,
          MEMSEARCH_CMD: JSON.stringify([process.execPath, fakeCli]),
          MEMSEARCH_PYTHON: JSON.stringify([python, driver]),
          MAINTENANCE_TEST_TRIGGER: trigger,
          MAINTENANCE_TEST_SESSION: session,
          MAINTENANCE_TEST_DONE: path.join(root, 'done.json'),
        }
        delete env.MEMSEARCH_DIR
        delete env.MEMSEARCH_DSH_SUMMARIZE
        delete env.MEMSEARCH_DISABLE
        if (scope === 'custom') env.MEMSEARCH_DIR = memRoot
        // Seed index health via its real persistence API, without a database or
        // embeddings. Its location is independent of the maintenance argv.
        const indexState = execFileSync(python, [driver, '--prepare-index', memRoot], {
          cwd: project, env, encoding: 'utf8', timeout: 20000,
        }).trim()
        const beforeIndex = fs.readFileSync(indexState, 'utf8')
        const report = JSON.parse(execFileSync(process.execPath, [host], {
          cwd: boot, env, encoding: 'utf8', timeout: 50000,
        }))
        for (const launch of report.launches) assert.equal(launch.exit, 0, JSON.stringify(launch))
        assert.deepEqual(report.warnings, [])
        const statePath = path.join(memRoot, '.maintenance-state.json')
        assert.ok(fs.existsSync(statePath), 'maintenance state must be written at the memsearch root')
        assert.equal(path.dirname(statePath), path.dirname(indexState))
        assert.equal(fs.existsSync(path.join(memory, '.maintenance-state.json')), false)
        const state = JSON.parse(fs.readFileSync(statePath, 'utf8'))
        assert.equal(state['dsh.project_review'].last_action, 'replace')
        assert.equal(fs.readFileSync(path.join(project, '.memsearch', 'PROJECT.md'), 'utf8'), 'Checked fixture memory.\n')
        assert.deepEqual(report.launches[0].calls, [{ input_dir: memory, has_journal: true }])
        assert.deepEqual(report.launches[1].calls, [], 'unchanged input must suppress the second LLM call')
        assert.equal(fs.readFileSync(indexState, 'utf8'), beforeIndex)
      } finally {
        fs.rmSync(root, { recursive: true, force: true })
      }
    })
  }
}
