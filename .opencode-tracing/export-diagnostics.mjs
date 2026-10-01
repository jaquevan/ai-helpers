import { OTLPTraceExporter } from '@opentelemetry/exporter-trace-otlp-http'
import { LANGFUSE_SDK_VERSION } from '@langfuse/core'

// This adapter observes the native exporter's result callback. It never retries
// model work, replays old spans, logs payloads, or changes SDK transport retries.
export function observeExports(exporter, { writeRecord, now = Date.now }) {
  let started = 0, acknowledged = 0, failed = 0, failedSpans = 0, journalWriteFailed = false
  const pending = new Set()
  const record = value => {
    try { writeRecord({ recorded_at: new Date(now()).toISOString(), ...value }) }
    catch { journalWriteFailed = true }
  }
  const errorSummary = error => {
    const code = error?.code
    const message = String(error?.message || '').toLowerCase()
    const status = Number.isInteger(code) && code >= 100 && code <= 599 ? code : null
    const knownCodes = new Set(['ECONNRESET', 'ECONNREFUSED', 'ETIMEDOUT', 'ENOTFOUND', 'EAI_AGAIN', 'EPIPE'])
    return {
      http_status: status,
      transport_code: knownCodes.has(code) ? code : null,
      category: /timeout|timed out/.test(message) || code === 'ETIMEDOUT' ? 'timeout'
        : status ? 'http_error' : knownCodes.has(code) ? 'transport_error' : 'export_error',
    }
  }
  return {
    export(spans, callback) {
      const batchID = ++started
      pending.add(batchID)
      const ids = spans.map(span => ({ trace_id: span.spanContext().traceId, span_id: span.spanContext().spanId }))
      record({ event: 'batch_started', batch_id: batchID, observations: ids })
      let finished = false
      const finish = result => {
        if (finished) return
        finished = true
        pending.delete(batchID)
        if (result.code === 0) acknowledged++
        else { failed++; failedSpans += spans.length }
        record({ event: result.code === 0 ? 'batch_acknowledged' : 'batch_failed', batch_id: batchID,
          observation_count: spans.length, ...(result.code === 0 ? {} : errorSummary(result.error)) })
        callback(result)
      }
      try { exporter.export(spans, finish) }
      catch (error) { finish({ code: 1, error }) }
    },
    forceFlush: () => exporter.forceFlush?.() ?? Promise.resolve(),
    shutdown: () => exporter.shutdown(),
    snapshot: () => ({ batches_started: started, batches_acknowledged: acknowledged, batches_failed: failed,
      failed_span_exports: failedSpans, pending_batches: pending.size, journal_write_failed: journalWriteFailed }),
  }
}

export function createDiagnosticExporter(env, writeRecord) {
  // Match the installed Langfuse SDK's default exporter configuration. A
  // successful OTLP response is only acknowledgement; the v4 API reconciliation
  // remains the authoritative check for observation presence.
  const exporter = new OTLPTraceExporter({
    url: `${env.LANGFUSE_BASE_URL}/api/public/otel/v1/traces`,
    headers: {
      Authorization: `Basic ${Buffer.from(`${env.LANGFUSE_PUBLIC_KEY}:${env.LANGFUSE_SECRET_KEY}`).toString('base64')}`,
      'x-langfuse-sdk-name': 'javascript',
      'x-langfuse-sdk-version': LANGFUSE_SDK_VERSION,
      'x-langfuse-public-key': env.LANGFUSE_PUBLIC_KEY,
    },
    timeoutMillis: Number(env.LANGFUSE_TIMEOUT ?? 5) * 1000,
  })
  return observeExports(exporter, { writeRecord })
}
