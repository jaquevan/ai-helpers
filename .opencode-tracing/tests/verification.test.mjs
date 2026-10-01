import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { artifactManifest } from '../plugins/session-root-core.mjs'
import { compareObservations, fetchObservations, verifyRemote } from '../remote-verification.mjs'

const traceID = 'a'.repeat(32)
const rows = [
  { id: 'root', traceId: traceID, type: 'SPAN', isRootObservation: true },
  { id: 'turn', traceId: traceID, name: 'opencode.turn', type: 'AGENT' },
  { id: 'gen1', traceId: traceID, name: 'opencode.generation', type: 'GENERATION', costDetails: { total: 0.1 }, metadata: { billing_source: 'opencode-model-price-card' } },
  { id: 'gen2', traceId: traceID, name: 'opencode.generation', type: 'GENERATION', costDetails: { total: 0.2 }, metadata: { billing_source: 'opencode-model-price-card' } },
  { id: 'tool1', traceId: traceID, name: 'read', type: 'TOOL' },
  { id: 'tool2', traceId: traceID, name: 'apply_patch', type: 'TOOL' },
]
const receipt = { run_id: 'fixture', trace_id: traceID, generations: 2, tool_calls: 2, user_turns: 1, known_session_cost_usd: 0.3, expected_observations: rows.map(({ id, name, type }) => ({ id, name, type })) }
test('remote reconciliation detects the missing generation/tool despite a root and completed flush', () => {
  const result = compareObservations({ ...receipt, export_status: 'flush_completed' }, rows.filter(o => !['gen2', 'tool2'].includes(o.id)))
  assert.equal(result.status, 'partial')
  assert.deepEqual(result.missing_observations.map(o => o.id), ['gen2', 'tool2'])
  assert.equal(result.remote_known_cost_usd, 0.1)
  assert.equal(result.local_known_cost_usd, 0.3)
})
test('matching IDs and costs verify; nested pipeline tools do not count as OpenCode tools', () => {
  const result = compareObservations(receipt, [...rows, { id: 'pipeline-tool', traceId: traceID, type: 'TOOL' }])
  assert.equal(result.status, 'verified')
  assert.equal(result.observed.tools, 2)
  assert.equal(compareObservations(receipt, [...rows, { id: 'extra-root', traceId: traceID, isRootObservation: true }]).status, 'partial')
})
test('legacy receipts compare counts and preserve explicit known cost differences', () => {
  const { expected_observations, ...legacy } = receipt
  assert.equal(compareObservations(legacy, rows).status, 'verified')
  assert.equal(compareObservations(legacy, rows.slice(0, 4)).status, 'partial')
})
test('backend-inferred prices never replace unavailable OpenCode costs', () => {
  const inferred = rows.map(o => o.id === 'gen2' ? { ...o, metadata: { billing_source: 'unavailable' } } : o)
  const result = compareObservations({ ...receipt, unpriced_generations: 1, known_session_cost_usd: 0.1 }, inferred)
  assert.equal(result.status, 'verified')
  assert.equal(result.remote_known_cost_usd, 0.1)
  assert.equal(compareObservations({ trace_id: traceID }, [rows[0]]).status, 'partial')
})
test('remote check retries only reads for ingestion delay, and reports network errors without guessing', async () => {
  let calls = 0
  const result = await verifyRemote(receipt, {}, { fetch: () => ++calls === 1 ? [] : rows, pause: async () => {} })
  assert.equal(result.status, 'verified')
  assert.equal(calls, 2)
  const failed = await verifyRemote(receipt, {}, { fetch: () => { throw new Error('offline') } })
  assert.equal(failed.status, 'unavailable')
})
test('v4 cursor paging stays on the same trace and keeps authorization out of argv', () => {
  const calls = []
  const result = fetchObservations(receipt, { LANGFUSE_BASE_URL: 'https://example.test', LANGFUSE_PUBLIC_KEY: 'fixture-public', LANGFUSE_SECRET_KEY: 'fixture-secret' }, (cmd, args, opts) => {
    calls.push(args)
    assert.doesNotMatch(args.join(' '), /fixture-secret|fixture-public|Authorization/)
    assert.match(opts.input, /Authorization: Basic/)
    return { status: 0, stdout: JSON.stringify(calls.length === 1 ? { data: rows.slice(0, 2), meta: { cursor: 'next-page' } } : { data: rows.slice(2), meta: {} }) }
  })
  assert.equal(result.length, rows.length)
  assert.match(calls[1].at(-1), /cursor=next-page/)
  assert.match(calls[1].at(-1), new RegExp(`traceId=${traceID}`))
})
test('ticket=none creator artifacts come from scorecard references, not a guessed none/eval directory', () => {
  const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-artifacts-'))
  try {
    const workspace = path.join(temp, 'workspace')
    const dir = path.join(workspace, '.artifacts/smoke-key')
    fs.mkdirSync(dir, { recursive: true })
    const report = path.join(dir, 'verification.json')
    const scorecard = path.join(dir, 'scorecard-test-run.md')
    fs.writeFileSync(report, '{}'); fs.writeFileSync(scorecard, '[UXD-SCORECARD]')
    const outside = path.join(temp, 'outside.txt')
    fs.writeFileSync(outside, 'outside')
    const symlink = path.join(dir, 'escape.txt')
    fs.symlinkSync(outside, symlink)
    const finalText = `[UXD-SCORECARD]\nreport_artifact: \`${report}\`; ${outside}; ${symlink}\nprototype_url: http://127.0.0.1:8765/\n`
    const found = artifactManifest({ UXD_TRACE_WORKSPACE: workspace, UXD_TRACE_TICKET: 'none', UXD_TRACE_RUN_ID: 'test-run', UXD_TRACE_PROTOTYPE_URL: 'none' }, finalText)
    assert.ok(found.some(a => a.path === report && a.run_ownership === 'session_reported'))
    assert.ok(found.some(a => a.path === scorecard))
    assert.ok(found.some(a => a.url === 'http://127.0.0.1:8765/' && a.access === 'local_server'))
    assert.ok(!found.some(a => a.path === outside || a.path === symlink))
  } finally { fs.rmSync(temp, { recursive: true, force: true }) }
})
