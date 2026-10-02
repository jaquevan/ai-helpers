import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { credentialManager, loadRoutingConfig, bindingStore } from '../interactive-project-config.mjs'
import { canonicalHost, canonicalProjects } from '../runtime.mjs'
import { ioDigest } from '../interactive-routing-core.mjs'
import { compareInteractiveObservations } from '../interactive-verification.mjs'
import { adaptRecorder } from '../build-interactive-recorder.mjs'
import Router from '../plugins/interactive-project-router.mjs'

function fixture() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-interactive-test-'))
  const projects = Object.fromEntries(['creator', 'consistency', 'evaluator', 'generic'].map(c => {
    const projectId = canonicalProjects[c] || 'generic-fixture'
    const file = path.join(dir, `${c}.env`)
    fs.writeFileSync(file, `LANGFUSE_BASE_URL=${canonicalHost}\nLANGFUSE_PROJECT_ID=${projectId}\nLANGFUSE_PUBLIC_KEY=fixture-public-${c}\nLANGFUSE_SECRET_KEY=fixture-secret-${c}\n`, { mode: 0o600 })
    return [c, { projectId, credentialFile: file, format: 'env' }]
  }))
  return { dir, config: { version: 1, host: canonicalHost, stateDirectory: path.join(dir, 'state'), projects }, cleanup: () => fs.rmSync(dir, { recursive: true, force: true }) }
}
test('project checks require exclusive ownership, secure files and no credential fallback', async () => {
  const f = fixture()
  try {
    const calls = []
    const manager = credentialManager(f.config, { request: async (url, options) => {
      calls.push({ url, method: options.method })
      const auth = Buffer.from(options.headers.Authorization.slice(6), 'base64').toString()
      const component = auth.match(/fixture-public-(\w+):/)[1]
      return { ok: true, json: async () => ({ data: [{ id: f.config.projects[component].projectId }] }) }
    } })
    const identities = []
    for (const component of Object.keys(f.config.projects)) identities.push((await manager.verify(component)).LANGFUSE_USER_ID)
    assert.equal(new Set(identities).size, 1)
    assert.match(identities[0], /^sha256:[a-f0-9]{16}$/)
    assert.equal(calls.length, 4); assert(calls.every(c => c.method === 'GET'))
    assert.equal(manager.redact('fixture-secret-creator fixture-secret-generic'), '[REDACTED] [REDACTED]')
    const wrong = credentialManager(f.config, { request: async () => ({ ok: true, json: async () => ({ data: [{ id: 'wrong-project' }] }) }) })
    await assert.rejects(wrong.verify('creator'), /ownership verification failed/)
    fs.chmodSync(f.config.projects.consistency.credentialFile, 0o644)
    await assert.rejects(manager.verify('consistency'), /securely load/)
    fs.unlinkSync(f.config.projects.evaluator.credentialFile)
    await assert.rejects(manager.verify('evaluator'), /securely load/)
  } finally { f.cleanup() }
})
test('routing config and sticky state reject wrong mappings, symlinks and concurrent destination changes', () => {
  const f = fixture()
  try {
    const file = path.join(f.dir, 'routing.json')
    fs.writeFileSync(file, JSON.stringify(f.config), { mode: 0o600 })
    assert.deepEqual(loadRoutingConfig(file), f.config)
    const store = bindingStore(f.config.stateDirectory, 'fixture-workspace')
    store.save('a', { destination: 'creator', projectId: canonicalProjects.creator })
    assert.equal(store.load('a').destination, 'creator')
    assert.throws(() => store.save('a', { destination: 'evaluator' }), /ownership differs/)
    f.config.projects.creator.projectId = 'wrong'
    fs.writeFileSync(file, JSON.stringify(f.config))
    assert.throws(() => loadRoutingConfig(file), /canonical/)
    const symlink = path.join(f.dir, 'link.json'); fs.symlinkSync(file, symlink)
    assert.throws(() => loadRoutingConfig(symlink), /nonsymlink/)
  } finally { f.cleanup() }
})
test('independent receipts check IDs, hierarchy, I/O, usage, cost and unintended destinations', () => {
  const row = { id: 'span', traceId: 'trace', parentObservationId: null, name: 'opencode.generation', type: 'GENERATION',
    model: 'fixture-model', startTime: '1970-01-01T00:00:01.000Z', endTime: '1970-01-01T00:00:02.000Z',
    input: [{ role: 'user', content: 'Hello' }], output: [{ role: 'assistant', content: 'Hi' }], usageDetails: { input: 10 }, costDetails: { total: 0.12 } }
  const expected = { id: row.id, traceId: row.traceId, parentId: null, name: row.name, type: 'generation', model: row.model,
    startTime: [1, 0], endTime: [2, 0], inputSHA256: ioDigest(row.input), outputSHA256: ioDigest(row.output), usage: '{"input":10}', cost: 0.12 }
  const state = { sessionID: 'session', destination: 'creator', projectId: 'project', receipts: [{ expected: [expected] }] }
  assert.equal(compareInteractiveObservations(state, [row], { generic: [], consistency: [], evaluator: [] }).status, 'verified')
  const wrong = { ...row, input: null, parentObservationId: 'other', costDetails: { total: 0.24 }, usageDetails: {} }
  const failed = compareInteractiveObservations(state, [wrong], { generic: [row] })
  for (const problem of ['io_hash_differs', 'trace_or_parent_differs', 'explicit_cost_differs', 'usage_differs', 'expected_observation_in_unintended_project']) assert(failed.discrepancies.some(d => d.problem === problem))
  assert.equal(compareInteractiveObservations(state, [], {}).status, 'partial')
})
test('generation/formatting/accounting implementations remain byte-identical to upstream', () => {
  const source = fs.readFileSync(new URL('../node_modules/@langfuse/opencode-observability-plugin/dist/index.js', import.meta.url), 'utf8')
  const adapted = adaptRecorder(source)
  const section = (text, a, b) => text.slice(text.indexOf(a), text.indexOf(b, text.indexOf(a)))
  assert.equal(section(adapted, '\ttraceGeneration(input)', '\ttraceFailedGenerationStep'), section(source, '\ttraceGeneration(input)', '\ttraceFailedGenerationStep'))
  assert.equal(section(adapted, 'function splitAssistantSteps', 'var LangfuseClientService'), section(source, 'function splitAssistantSteps', 'var LangfuseClientService'))
  assert(!adapted.includes('provider.register()'))
})
test('dedicated launcher deferral is preserved and estimate wrapper rejects paid execution without spawning', async () => {
  const previous = process.env.OPENCODE_DEDICATED_TRACE
  process.env.OPENCODE_DEDICATED_TRACE = '1'
  try { assert.deepEqual(await Router({}), {}) }
  finally { if (previous === undefined) delete process.env.OPENCODE_DEDICATED_TRACE; else process.env.OPENCODE_DEDICATED_TRACE = previous }
  const script = fileURLToPath(new URL('../../scripts/interactive-eval-estimate.mjs', import.meta.url))
  const result = spawnSync(process.execPath, [script, 'not-python', 'not-pipeline', '--approve-estimate'], {
    encoding: 'utf8', env: { ...process.env, UXD_INTERACTIVE_COMPONENT: 'evaluator', UXD_INTERACTIVE_SESSION_ID: 'fixture' },
  })
  assert.equal(result.status, 2)
  assert.match(result.stderr, /Paid approval is not supported/)
})
