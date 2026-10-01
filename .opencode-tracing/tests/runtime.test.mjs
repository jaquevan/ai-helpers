import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { buildPlan, hashUser, nestedSession, readAssignments, validateRuntime } from '../runtime.mjs'
import { scopeWorkspace } from '../plugins/session-root-core.mjs'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..')
test('runtime floor and hashed identity', () => {
  for (const v of ['22.22.2', '24.15.0', '26.0.0']) validateRuntime(v)
  for (const v of ['18.20.0', '22.22.1', '24.10.0', '25.1.0']) assert.throws(() => validateRuntime(v))
  assert.match(hashUser('designer'), /^sha256:[a-f0-9]{16}$/)
  assert.equal(hashUser(hashUser('designer')), hashUser('designer'))
  assert.equal(nestedSession({ OPENCODE: '1' }), true)
})
test('plans execute command templates for all three components and scope smoke context', () => {
  for (const [component, command] of [['creator', 'designer-create'], ['consistency', 'designer-consistency'], ['evaluator', 'designer-evaluate']]) {
    const args = [component, '--ticket', 'none', '--workspace', root, '--prototype-url', 'http://127.0.0.1:3000', '--scenario', 'One button changes status.', '--run-kind', 'manual-smoke', '--dry-run']
    const plan = buildPlan(args, root)
    assert.deepEqual(plan.argv.slice(0, 5), ['run', '--dir', root, '--command', command])
    assert.match(plan.argv.at(-1), /^\[UXD-SESSION\]/)
    assert.match(plan.renderedTemplate, /UXD-SCORECARD/)
    assert.doesNotMatch(plan.renderedTemplate, /\$ARGUMENTS/)
    if (component === 'evaluator') {
      assert.match(plan.argv.at(-1), /--estimate-only/); assert.match(plan.argv.at(-1), /synthetic-smoke/)
      const approved = buildPlan([...args, '--approve-estimate'], root)
      assert.equal(approved.inputFingerprint, plan.inputFingerprint)
      assert.match(approved.argv.at(-1), /Pass --approve-estimate once/)
    }
  }
  assert.throws(() => buildPlan(['creator', '--approve-estimate'], root))
})
test('missing designer command fails before any credential access', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-stale-'))
  try { assert.throws(() => buildPlan(['creator', '--ticket', 'none', '--workspace', temp, '--prototype-url', 'none', '--scenario', 'smoke'], temp), /Missing .*designer-create/ ) }
  finally { fs.rmSync(temp, { recursive: true, force: true }) }
})
test('offline Atlassian refinement requires a local snapshot and fingerprints its contents', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-snapshot-'))
  try {
    const context = path.join(temp, 'context.md')
    fs.writeFileSync(context, 'Current source requirements')
    const args = ['creator', '--ticket', 'TEST-1', '--workspace', temp, '--prototype-url', 'none', '--scenario', 'Refine locally; never write to Jira.', '--offline-atlassian']
    assert.throws(() => buildPlan(args, root), /requires --context-file/)
    const first = buildPlan([...args, '--context-file', context], root)
    assert.equal(first.offlineAtlassian, true)
    assert.match(first.argv.at(-1), /Atlassian MCP is disabled/)
    assert.match(first.argv.at(-1), /including through shell commands/)
    fs.writeFileSync(context, 'Updated source requirements')
    const second = buildPlan([...args, '--context-file', context], root)
    assert.notEqual(first.inputFingerprint, second.inputFingerprint)
  } finally { fs.rmSync(temp, { recursive: true, force: true }) }
})
test('workspace rules are narrow and never replace existing denies', () => {
  const cfg = { permission: { external_directory: { '*': 'ask', '/secret/**': 'deny' }, bash: 'ask' } }
  scopeWorkspace(cfg, '/work/prototype')
  assert.deepEqual(cfg.permission.external_directory, { '*': 'ask', '/secret/**': 'deny', '/work/prototype': 'allow', '/work/prototype/**': 'allow' })
  assert.throws(() => scopeWorkspace({ permission: { external_directory: { '/work/**': 'deny' } } }, '/work/prototype'))
  assert.throws(() => scopeWorkspace({ agent: { build: { permission: 'deny' } } }, '/work/prototype'))
})
test('credential parsing is literal, owner-only and rejects shell execution', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-creds-'))
  const file = path.join(temp, 'creator.env')
  try {
    fs.writeFileSync(file, 'LANGFUSE_PROJECT_ID="synthetic-project"\n', { mode: 0o600 })
    assert.equal(readAssignments(file).LANGFUSE_PROJECT_ID, 'synthetic-project')
    fs.writeFileSync(file, 'LANGFUSE_PROJECT_ID=$(whoami)\n')
    assert.throws(() => readAssignments(file), /literal/)
    fs.chmodSync(file, 0o644)
    assert.throws(() => readAssignments(file), /mode 600/)
  } finally { fs.rmSync(temp, { recursive: true, force: true }) }
})
test('real launcher refuses nested/non-TTY execution without starting a session', () => {
  const result = spawnSync(process.execPath, [path.join(root, '.opencode-tracing/launcher.mjs'), 'creator', '--ticket', 'none', '--workspace', root, '--prototype-url', 'none', '--scenario', 'smoke'], { encoding: 'utf8', env: { ...process.env, OPENCODE: '1' } })
  assert.equal(result.status, 2)
  assert.match(result.stderr, /plain Terminal/)
})
