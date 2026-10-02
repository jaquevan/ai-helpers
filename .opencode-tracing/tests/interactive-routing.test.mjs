import assert from 'node:assert/strict'
import test from 'node:test'
import { AsyncLocalStorage } from 'node:async_hooks'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { ROOT_CONTEXT, trace } from '@opentelemetry/api'
import { createInteractiveRouting, hasExplicitTraceConsent } from '../interactive-routing-core.mjs'
import { adaptRecorder, buildRecorder } from '../build-interactive-recorder.mjs'
import { pathToFileURL } from 'node:url'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'

const { default: makeRecorder } = await import(pathToFileURL(buildRecorder()))
function memoryStore() {
  const saved = new Map()
  return { load: id => structuredClone(saved.get(id) || null), save: (id, state) => saved.set(id, structuredClone(state)), saved }
}
const consentText = 'TRACE — I consent to hosted capture of this fresh interactive session.'
async function harness({ store = memoryStore(), invalid = [], limit, failExport = false, delivery } = {}) {
  const rows = [], messages = new Map(), ancestry = new Map(), notices = []
  let router
  const provider = new NodeTracerProvider({ spanProcessors: [{ onStart() {}, onEnd: span => router.onEnd(span), forceFlush: async () => {}, shutdown: async () => {} }] })
  const tracer = provider.getTracer('opencode-langfuse-plugin', '0.4.0')
  const als = new AsyncLocalStorage()
  const localContext = { active: () => als.getStore() || ROOT_CONTEXT, with: (ctx, fn) => als.run(ctx, fn) }
  const client = {
    app: { log: async () => {} }, tool: { list: async () => ({ data: [] }) },
    session: { get: async ({ path }) => ({ data: { id: path.id, parentID: ancestry.get(path.id) } }),
      messages: async ({ path }) => ({ data: messages.get(path.id) || [] }) },
  }
  const scopedTracer = { startSpan: (name, options, supplied) => tracer.startSpan(name, options, supplied || localContext.active()) }
  const recorder = await makeRecorder({ client }, { tracer: scopedTracer, context: localContext, baseUrl: 'https://offline.invalid', forceFlush: async () => {}, shutdown: async () => {} })
  const projects = Object.fromEntries(['creator', 'consistency', 'evaluator', 'generic'].map(c => [c, { projectId: `project-${c}` }]))
  const credentials = { verify: async c => { if (invalid.includes(c)) throw new Error(`Invalid ${c} fixture keys`); return {} },
    redact: attrs => Object.fromEntries(Object.entries(attrs).map(([key, value]) => [key, typeof value === 'string' ? value.replaceAll('fixture-secret-value', '[REDACTED]') : value])) }
  router = createInteractiveRouting({ recorder, client, store, projects, credentials, bufferLimitBytes: limit,
    notify: async notice => notices.push(notice),
    deliver: (destination, span) => { if (failExport) throw new Error('fixture-secret-value'); rows.push({ destination, id: span.spanContext().spanId, traceId: span.spanContext().traceId, parentId: span.parentSpanContext?.spanId, attributes: structuredClone(span.attributes), startTime: [...span.startTime], endTime: [...span.endTime], name: span.name }) },
    flush: async () => delivery || ({ batches_failed: 0, pending_batches: 0 }), shutdown: () => provider.shutdown(),
  })
  const event = (type, properties) => router.hooks.event({ event: { type, properties } })
  async function chat(session, agent = 'build', id = `${session}-user`, text = 'Fixture task', { consent = true } = {}) {
    const hasPriorUser = (messages.get(session) || []).some(message => message.info.role === 'user')
    const alreadyConsented = router.snapshot(session).consented
    const userText = consent && !alreadyConsented && !hasPriorUser ? `${consentText}\n${text}` : text
    const message = { id, role: 'user', sessionID: session, agent, model: { providerID: 'test', modelID: 'fixture-model' }, time: { created: 1000 } }
    const parts = [{ id: `${id}-text`, sessionID: session, messageID: id, type: 'text', text: userText }]
    await router.hooks['chat.message']({ sessionID: session }, { message, parts })
    messages.set(session, [...(messages.get(session) || []), { info: message, parts }])
    return id
  }
  async function generation(session, id = `${session}-assistant`, { cost = 0.123, parentID = `${session}-user`, reconcileOnly = false } = {}) {
    const info = { id, sessionID: session, role: 'assistant', parentID, providerID: 'test', modelID: 'fixture-model', mode: 'build',
      time: { created: 2000, completed: 3000 }, finish: 'stop', cost, tokens: { input: 10, output: 3, reasoning: 2, cache: { read: 5, write: 0 } } }
    const parts = [{ id: `${id}-text`, type: 'text', text: 'Fixture response fixture-secret-value', messageID: id, sessionID: session }]
    messages.set(session, [...(messages.get(session) || []), { info, parts }])
    if (!reconcileOnly) {
      await event('session.next.step.started', { sessionID: session, assistantMessageID: id, timestamp: 2000, agent: 'build', model: { providerID: 'test', id: 'fixture-model' } })
      await event('message.part.updated', { part: parts[0] })
      await event('message.updated', { info })
    }
    return info
  }
  return { ...router, rows, messages, ancestry, store, notices, chat, generation, event, provider, client }
}
test('only an exact first-message TRACE statement opts a fresh session into capture', async () => {
  assert.equal(hasExplicitTraceConsent(`${consentText}\nRun the task`), true)
  assert.equal(hasExplicitTraceConsent('TRACE'), false)
  assert.equal(hasExplicitTraceConsent('Please include TRACE in the report'), false)

  const h = await harness()
  try {
    await h.chat('ordinary', 'build', 'ordinary-user', 'Normal unconsented chat', { consent: false })
    await h.generation('ordinary')
    await h.event('session.idle', { sessionID: 'ordinary' })
    assert.equal(h.rows.length, 0)
    assert.equal(h.store.load('ordinary'), null)
    await assert.rejects(h.chat('ordinary', 'build', 'late-consent', 'TRACE — I consent to hosted capture of this fresh interactive session.\nDo work'), /first user message in a fresh conversation/)
    assert.equal(h.rows.length, 0)
  } finally { await h.hooks.dispose() }
})
test('initial planning and follow-ups route once to all four destinations with readable I/O and costs', async () => {
  const h = await harness()
  try {
    for (const [session, agent, destination] of [['a', 'uxd-creator', 'creator'], ['b', 'uxd-consistency', 'consistency'], ['c', 'uxd-evaluator', 'evaluator'], ['d', 'build', 'generic']]) {
      await h.chat(session, agent)
      await h.generation(session)
      await h.event('session.idle', { sessionID: session })
      await h.chat(session, 'build', `${session}-followup`)
      await h.generation(session, `${session}-followup-response`, { parentID: `${session}-followup` })
      await h.event('session.idle', { sessionID: session })
      const rows = h.rows.filter(row => row.attributes['session.id'] === session)
      assert(rows.every(row => row.destination === destination))
      const gens = rows.filter(row => row.name === 'opencode.generation')
      assert.equal(gens.length, 2)
      for (const gen of gens) {
        assert.match(gen.attributes['langfuse.observation.input'], /Fixture task/)
        assert.match(gen.attributes['langfuse.observation.output'], /Fixture response \[REDACTED\]/)
        assert.equal(JSON.parse(gen.attributes['langfuse.observation.cost_details']).total, 0.123)
        assert.equal(gen.startTime[0], 2); assert.equal(gen.endTime[0], 3)
        assert(rows.some(row => row.id === gen.parentId && row.traceId === gen.traceId))
      }
    }
    assert.equal(new Set(h.rows.map(row => row.id)).size, h.rows.length)
  } finally { await h.hooks.dispose() }
})
test('actual skill loading binds buffered initial generations; mentions do not route', async () => {
  const h = await harness()
  const skill = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-loaded-skill-'))
  fs.writeFileSync(path.join(skill, 'SKILL.md'), 'Loaded fixture skill content')
  try {
    await h.chat('a', 'build', 'a-user', 'Discuss "uxd-prototype-create" and a Jira URL')
    await h.generation('a')
    assert.equal(h.rows.length, 0)
    await h.hooks['tool.execute.before']({ sessionID: 'a', tool: 'skill', callID: 'skill-a' }, { args: { name: 'uxd-prototype-create' } })
    await h.hooks['tool.execute.after']({ sessionID: 'a', tool: 'skill', callID: 'skill-a', args: { name: 'uxd-prototype-create' } }, {
      title: 'Loaded skill', output: 'Loaded fixture skill content', metadata: { name: 'uxd-prototype-create', dir: skill },
    })
    assert.match(h.snapshot('a').loadedSkills['uxd-prototype-create'], /^[a-f0-9]{64}$/)
    await h.event('session.idle', { sessionID: 'a' })
    assert(h.rows.every(row => row.destination === 'creator'))
    assert.equal(h.rows.filter(row => row.name === 'opencode.generation').length, 1)
    await h.chat('b', 'build', 'b-user', 'Quoted example: Use uxd-prototype-evaluate')
    await h.generation('b'); await h.event('session.idle', { sessionID: 'b' })
    assert(h.rows.filter(row => row.attributes['session.id'] === 'b').every(row => row.destination === 'generic'))
  } finally { await h.hooks.dispose(); fs.rmSync(skill, { recursive: true, force: true }) }
})
test('wrong component keys block before selected workflow generation and never fall back', async () => {
  const h = await harness({ invalid: ['creator'] })
  try {
    await assert.rejects(h.chat('a', 'uxd-creator'), /Invalid creator/)
    assert.equal(h.rows.length, 0)
    await h.chat('b')
    await h.generation('b')
    await assert.rejects(h.hooks['tool.execute.before']({ sessionID: 'b', tool: 'skill' }, { args: { name: 'uxd-prototype-create' } }), /Invalid creator/)
    await h.event('session.idle', { sessionID: 'b' })
    assert.equal(h.rows.length, 0)
    assert.equal(h.store.load('b').receipts.at(-1).exportStatus, 'blocked_or_failed')
  } finally { await h.hooks.dispose() }
})
test('concurrent sessions and child support skills retain their owner; mixed primary workflows are rejected', async () => {
  const h = await harness()
  try {
    await Promise.all([h.chat('a', 'uxd-creator'), h.chat('b', 'uxd-evaluator')])
    await h.hooks['tool.execute.before']({ sessionID: 'a', tool: 'task', callID: 'task-a' }, { args: { prompt: 'Support task' } })
    h.ancestry.set('child', 'a')
    const registered = h.event('session.created', { info: { id: 'child', parentID: 'a' } })
    await h.chat('child', 'general'); await registered
    await h.hooks['tool.execute.before']({ sessionID: 'child', tool: 'skill', callID: 'child-skill' }, { args: { name: 'uxd-consistency-check' } })
    await h.generation('child'); await h.event('session.idle', { sessionID: 'child' })
    assert.equal(h.store.load('a').receipts.length, 0)
    await h.generation('a'); await h.generation('b')
    await Promise.all([h.event('session.idle', { sessionID: 'a' }), h.event('session.idle', { sessionID: 'b' })])
    assert(h.rows.filter(row => row.attributes['session.id'] === 'a').every(row => row.destination === 'creator'))
    assert(h.rows.filter(row => row.attributes['session.id'] === 'b').every(row => row.destination === 'evaluator'))
    await assert.rejects(h.chat('a', 'uxd-evaluator', 'new-workflow'), /fresh conversation/)
    await assert.rejects(h.hooks['tool.execute.before']({ sessionID: 'b', tool: 'skill' }, { args: { name: 'uxd-prototype-create' } }), /fresh conversation/)
    await assert.rejects(h.hooks['tool.execute.before']({ sessionID: 'b', tool: 'bash' }, { args: { command: 'python langfuse-trace-pipeline.py --approve-estimate' } }), /estimate wrapper/)
  } finally { await h.hooks.dispose() }
})
test('sticky state survives restart and completed message replays do not duplicate generation cost', async () => {
  const store = memoryStore(), h = await harness({ store })
  await h.chat('a', 'uxd-creator'); const info = await h.generation('a')
  await h.event('session.idle', { sessionID: 'a' })
  await h.event('message.updated', { info })
  assert.equal(h.rows.filter(row => row.name === 'opencode.generation').length, 1)
  await h.hooks.dispose()
  const resumed = await harness({ store })
  try {
    await resumed.chat('a', 'build', 'followup')
    await resumed.event('message.updated', { info })
    await resumed.generation('a', 'new-generation', { parentID: 'followup' })
    await resumed.event('session.idle', { sessionID: 'a' })
    assert.equal(resumed.rows.filter(row => row.name === 'opencode.generation').length, 1)
    assert(resumed.rows.every(row => row.destination === 'creator'))
  } finally { await resumed.hooks.dispose() }
})
test('idle reconciles only the current persisted completion and preserves zero/unknown provenance', async () => {
  const h = await harness()
  try {
    await h.chat('a', 'uxd-creator')
    await h.generation('a', 'zero', { cost: 0, reconcileOnly: true })
    await h.generation('a', 'unknown', { cost: undefined, reconcileOnly: true })
    // Explicit undefined requires overriding the helper default.
    h.messages.get('a').find(m => m.info.id === 'unknown').info.cost = undefined
    await h.event('session.idle', { sessionID: 'a' })
    const gens = h.rows.filter(row => row.name === 'opencode.generation')
    assert.equal(gens.length, 2)
    assert.equal(gens[0].attributes['langfuse.observation.metadata.billing_source'], 'opencode-reported-zero-unvalidated')
    assert.equal(gens[1].attributes['langfuse.observation.metadata.billing_source'], 'unavailable')
    assert.equal(h.store.load('a').receipts[0].expected.filter(e => e.type === 'generation').length, 2)
  } finally { await h.hooks.dispose() }
})
test('buffer overflow, disposal before binding and export failures never use the generic exporter', async () => {
  const overflow = await harness({ limit: 100 })
  await overflow.chat('a')
  await assert.rejects(overflow.hooks['chat.params']({ sessionID: 'a', agent: 'build', message: { agent: 'build' } }, {}), /buffer limit/)
  await overflow.hooks.dispose(); assert.equal(overflow.rows.length, 0)
  const provisional = await harness()
  await provisional.chat('a', 'build', 'a-user', 'Unconsented activity', { consent: false })
  await provisional.generation('a'); await provisional.hooks.dispose()
  assert.equal(provisional.rows.length, 0)
  const failed = await harness({ delivery: { batches_failed: 1, pending_batches: 0 } })
  await failed.chat('a', 'uxd-creator'); await failed.generation('a'); await failed.event('session.idle', { sessionID: 'a' })
  assert.equal(failed.store.load('a').receipts[0].exportStatus, 'blocked_or_failed')
  assert(failed.rows.every(row => row.destination === 'creator'))
  await failed.hooks.dispose()
  const thrown = await harness({ failExport: true })
  await thrown.chat('a', 'uxd-creator'); await thrown.event('session.idle', { sessionID: 'a' }); await thrown.hooks.dispose()
  assert.equal(thrown.rows.length, 0)
  assert(!JSON.stringify(thrown.store.saved.get('a')).includes('fixture-secret-value'))
})
test('adapter fails closed on upstream drift and global provider is untouched', () => {
  const provider = trace.getTracerProvider()
  assert.throws(() => adaptRecorder('unexpected upstream source'), /hash differs/)
  assert.equal(trace.getTracerProvider(), provider)
})
