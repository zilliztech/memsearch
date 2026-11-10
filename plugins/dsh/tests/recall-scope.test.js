import test from 'node:test'
import assert from 'node:assert/strict'
import { mkdtempSync, mkdirSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { deriveCollection, registerMemoryRecallSkill } from '../index.js'

test('recall skill loads the calling workspace collection without changing other sessions', async () => {
  const root = mkdtempSync(join(tmpdir(), 'memsearch-skill-scope-'))
  const boot = join(root, 'boot')
  const project = join(root, 'project')
  for (const dir of [boot, project]) mkdirSync(dir)
  const previous = process.env.MEMSEARCH_DIR
  delete process.env.MEMSEARCH_DIR
  try {
    let provider
    registerMemoryRecallSkill({
      skills: { registerProvider: create => { provider = create() } },
      logger: { warn: () => {} },
    }, { agentName: 'DeepSeek Harness', milvusUri: '' }, ['memsearch'], boot)
    const [candidate] = await provider.list({ cwd: project })
    assert.equal(candidate.name, 'memory-recall')
    assert.equal(candidate.provider, provider.name)
    assert.deepEqual(candidate.invocation, { modelInvocable: true, userInvocable: true })
    const [first, second] = await Promise.all([
      provider.get(candidate, { cwd: boot }),
      provider.get(candidate, { cwd: project }),
    ])
    const bootCollection = deriveCollection(boot)
    const projectCollection = deriveCollection(project)
    assert.notEqual(bootCollection, projectCollection)
    assert.ok(first.content.includes(`--default-collection "${bootCollection}"`))
    assert.ok(second.content.includes(`--default-collection "${projectCollection}"`))
    assert.ok(!second.content.includes(bootCollection))
    assert.equal((await provider.get(candidate, { cwd: boot })).content, first.content)
    assert.equal((await provider.get(candidate)).content, first.content)
    assert.ok(second.content.includes('memory-recall') || second.content.includes('Memory Recall'))
    assert.ok(second.content.includes('expand <chunk_hash>'))

    process.env.MEMSEARCH_DIR = root
    const sharedDirectory = await provider.get(candidate, { cwd: project })
    assert.ok(sharedDirectory.content.includes(`--default-collection "${projectCollection}"`))
  } finally {
    if (previous === undefined) delete process.env.MEMSEARCH_DIR
    else process.env.MEMSEARCH_DIR = previous
    rmSync(root, { recursive: true, force: true })
  }
})
