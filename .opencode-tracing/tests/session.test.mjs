import assert from 'node:assert/strict'
import test from 'node:test'
import { createSessionHooks, redactor, usageDetails } from '../plugins/session-root-core.mjs'

function harness({ env: envOverrides = {}, ...extra } = {}) {
  const spans = [], receipts = []
  let flushes = 0
  const span = (name, attributes = {}, parent, times) => {
    const obj = { name, attributes, parent, times, ended: 0, spanContext: () => ({ traceId: 'a'.repeat(32), spanId: String(spans.indexOf(obj) + 1).padStart(16, '0') }), setAttribute(k, v) { this.attributes[k] = v }, setStatus(v) { this.status = v }, end(time) { this.ended++; this.endTime = time } }
    spans.push(obj); return obj
  }
  const env = { UXD_TRACE_COMPONENT: 'creator', UXD_TRACE_RUN_ID: 'test-run', UXD_TRACE_WORKSPACE: '/nonexistent-trace-fixture', UXD_TRACE_TICKET: 'none', UXD_TRACE_PROTOTYPE_URL: 'none', UXD_TRACE_RECEIPT: '/nonexistent-trace-receipt', LANGFUSE_BASE_URL: 'https://example.test', LANGFUSE_PROJECT_ID: 'project', LANGFUSE_USER_ID: 'sha256:0123456789abcdef', OPENAI_API_KEY: 'synthetic-secret-value', ...envOverrides }
  const hooks = createSessionHooks({ env, root: span('root'), startSpan: span, flush: async () => { flushes++ }, shutdown: async () => {}, writeReceipt: r => receipts.push(structuredClone(r)), log: () => {}, ...extra })
  const event = (type, properties) => hooks.event({ event: { type, properties } })
  return { hooks, event, spans, receipts, flushes: () => flushes }
}
test('generation has readable I/O, deduplicated parts and usage with real timing', async () => {
  const h = harness()
  await h.hooks['chat.message']({ sessionID: 'owner' }, { parts: [{ type: 'text', text: 'Create a card' }] })
  for (const text of ['He', 'Hello synthetic-secret-value']) await h.event('message.part.updated', { part: { sessionID: 'owner', messageID: 'm1', id: 'p1', type: 'text', text } })
  const info = { id: 'm1', sessionID: 'owner', role: 'assistant', modelID: 'test-model', providerID: 'test', time: { created: 1000, completed: 2000 }, tokens: { input: 10, output: 3, reasoning: 2, cache: { read: 5, write: 0 } }, cost: 0.1 }
  await h.event('message.updated', { info }); await h.event('message.updated', { info })
  await h.event('session.status', { sessionID: 'owner', status: { type: 'idle' } })
  await h.hooks.dispose()
  const gens = h.spans.filter(s => s.name === 'opencode.generation')
  assert.equal(gens.length, 1)
  assert.match(gens[0].attributes['langfuse.observation.input'], /Create a card/)
  assert.match(gens[0].attributes['langfuse.observation.output'], /Hello \[REDACTED\]/)
  assert.equal(gens[0].times.startTime.getTime(), 1000)
  assert.equal(gens[0].endTime.getTime(), 2000)
  assert.equal(h.receipts.at(-1).known_session_cost_usd, 0.1)
  assert.equal(h.flushes(), 1)
  assert.equal(h.receipts.at(-1).task_outcome, 'unconfirmed')
})
test('child idle does not close root; tool bridge matches actual parent and errors block outcome', async () => {
  const h = harness()
  await h.hooks['chat.message']({ sessionID: 'owner' }, { parts: [] })
  await h.hooks['tool.execute.before']({ sessionID: 'owner', callID: 'c1', tool: 'bash' }, { args: { command: 'test' } })
  const output = { env: {} }
  await h.hooks['shell.env']({ sessionID: 'owner', callID: 'c1' }, output)
  assert.equal(output.env.LANGFUSE_TRACE_ID, 'a'.repeat(32))
  assert.equal(output.env.LANGFUSE_PARENT_SPAN_ID, h.spans.find(s => s.name === 'bash').spanContext().spanId)
  await h.event('session.created', { info: { id: 'child', parentID: 'owner' } })
  await h.event('session.idle', { sessionID: 'child' })
  assert.equal(h.flushes(), 0)
  const part = { id: 'p', sessionID: 'owner', messageID: 'm', callID: 'c1', type: 'tool', state: { status: 'error', error: 'Permission rejected' } }
  await h.event('message.part.updated', { part }); await h.event('message.part.updated', { part })
  await h.event('session.idle', { sessionID: 'owner' })
  assert.equal(h.receipts.at(-1).tool_failures, 1)
  assert.equal(h.receipts.at(-1).task_outcome, 'blocked')
})
test('shutdown callers await the same pending flush', async () => {
  let resolve
  const gate = new Promise(r => { resolve = r })
  const h = harness({ flush: () => gate })
  const a = h.hooks.dispose(), b = h.hooks.dispose()
  assert.equal(a, b)
  await Promise.resolve()
  assert.notEqual(h.receipts.at(-1).export_status, 'flush_completed')
  resolve(); await a
  assert.equal(h.receipts.at(-1).export_status, 'flush_completed')
})
test('redacts nested keys and preserves explicit zero tokens without total duplication', () => {
  assert.deepEqual(redactor({})({ password: 'private', content: 'Bearer abcdef' }), { password: '[REDACTED]', content: 'Bearer [REDACTED]' })
  assert.deepEqual(usageDetails({ input: 1, output: 0, reasoning: 2, total: 99, cache: { read: 3, write: 0 } }), { input: 1, output: 0, reasoning: 2, cache_read_input_tokens: 3, cache_write_input_tokens: 0 })
})
test('snapshot-only policy disables inherited Atlassian servers without disabling PatternFly', async () => {
  const h = harness({ env: { UXD_TRACE_OFFLINE_ATLASSIAN: 'true', UXD_TRACE_CONTEXT_FILE: '/snapshot.md', UXD_TRACE_CONTEXT_SHA256: 'fixture-hash' } })
  const cfg = { mcp: { atlassian: { type: 'remote', enabled: true, url: 'https://example.test' }, 'team-jira': { enabled: true }, 'patternfly-mcp': { enabled: true } } }
  await h.hooks.config(cfg)
  assert.deepEqual(cfg.mcp.atlassian, { enabled: false })
  assert.deepEqual(cfg.mcp['team-jira'], { enabled: false })
  assert.deepEqual(cfg.mcp['patternfly-mcp'], { enabled: true })
  assert.equal(h.receipts[0].source_context.atlassian_access, 'offline_snapshot_only')
  await h.hooks.dispose()
})
