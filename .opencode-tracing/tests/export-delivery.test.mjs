import assert from 'node:assert/strict'
import test from 'node:test'
import { LangfuseSpanProcessor } from '@langfuse/otel'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { ROOT_CONTEXT, trace } from '@opentelemetry/api'
import { observeExports } from '../export-diagnostics.mjs'

test('native SDK final flush can succeed after an earlier batch was rejected', async () => {
  const attempts = [], accepted = []
  let firstAttempt
  const first = new Promise(resolve => { firstAttempt = resolve })
  const exporter = {
    export(spans, callback) {
      attempts.push(spans.map(s => s.name))
      if (attempts.length === 1) {
        callback({ code: 1, error: new Error('Synthetic transport failure; no network request made') })
        firstAttempt()
      } else {
        accepted.push(...spans.map(s => s.name))
        callback({ code: 0 })
      }
    },
    shutdown: async () => {},
    forceFlush: async () => {},
  }
  const journal = []
  const diagnosticExporter = observeExports(exporter, { writeRecord: record => journal.push(record) })
  const processor = new LangfuseSpanProcessor({ exporter: diagnosticExporter, publicKey: 'fixture-public', secretKey: 'fixture-secret', mediaUploadEnabled: false, flushAt: 2, shouldExportSpan: () => true })
  const provider = new NodeTracerProvider({ spanProcessors: [processor] })
  try {
    const tracer = provider.getTracer('offline-delivery-reproduction')
    const root = tracer.startSpan('root', {}, ROOT_CONTEXT)
    const context = trace.setSpan(ROOT_CONTEXT, root)
    tracer.startSpan('apply_patch', {}, context).end()
    tracer.startSpan('opencode.generation', {}, context).end()
    await Promise.race([first, new Promise((_, reject) => { const t = setTimeout(() => reject(new Error('Synthetic export did not run')), 1000); t.unref() })])
    await new Promise(resolve => setImmediate(resolve))
    root.end()
    await provider.forceFlush()
    assert.deepEqual(attempts, [['apply_patch', 'opencode.generation'], ['root']])
    assert.deepEqual(accepted, ['root'])
    assert.equal(diagnosticExporter.snapshot().failed_span_exports, 2)
    assert.equal(journal.filter(record => record.event === 'batch_failed').length, 1)
  } finally { await provider.shutdown() }
})

test('export diagnostics retain an earlier failure without exposing error bodies or replaying spans', async () => {
  const journal = [], results = []
  let calls = 0
  const native = {
    export(_spans, callback) {
      calls++
      callback(calls === 1 ? { code: 1, error: Object.assign(new Error('fixture-private-credential: request timed out'), { code: 'ETIMEDOUT' }) } : { code: 0 })
    },
    forceFlush: async () => {}, shutdown: async () => {},
  }
  const observed = observeExports(native, { writeRecord: record => journal.push(record) })
  const span = id => ({ spanContext: () => ({ traceId: 'a'.repeat(32), spanId: id.repeat(16) }) })
  observed.export([span('1'), span('2')], result => results.push(result.code))
  observed.export([span('3')], result => results.push(result.code))
  await observed.forceFlush(); await observed.shutdown()
  assert.deepEqual(results, [1, 0])
  assert.equal(calls, 2)
  assert.equal(observed.snapshot().batches_failed, 1)
  assert.equal(observed.snapshot().failed_span_exports, 2)
  assert.equal(journal[1].category, 'timeout')
  assert.doesNotMatch(JSON.stringify(journal), /fixture-private-credential/)
  assert.equal(journal[0].observations.length, 2)
})

test('diagnostic write failures do not prevent export and are visible in the receipt snapshot', () => {
  let delivered = 0
  const observed = observeExports({ export: (_spans, done) => done({ code: 0 }), shutdown: async () => {} }, { writeRecord: () => { throw new Error('disk unavailable') } })
  observed.export([], () => delivered++)
  assert.equal(delivered, 1)
  assert.equal(observed.snapshot().journal_write_failed, true)
})
