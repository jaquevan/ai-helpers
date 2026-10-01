import fs from 'node:fs'
import path from 'node:path'
import { context, trace, ROOT_CONTEXT } from '@opentelemetry/api'
import { LangfuseSpanProcessor } from '@langfuse/otel'
import { resourceFromAttributes } from '@opentelemetry/resources'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { createSessionHooks, hasTraceCredentials, rootNameFor } from './session-root-core.mjs'
import { createDiagnosticExporter } from '../export-diagnostics.mjs'

const ownerKey = Symbol.for('uxd.traced-session.owner.v2')
export default async function LangfuseSessionRoot({ client }) {
  const env = process.env
  if (!hasTraceCredentials(env)) return {}
  if (globalThis[ownerKey]) return globalThis[ownerKey].runID === env.UXD_TRACE_RUN_ID ? globalThis[ownerKey].promise : {}
  const promise = (async () => {
    const scope = 'opencode-langfuse-fork'
    const exportJournal = path.join(path.dirname(env.UXD_TRACE_RECEIPT), 'export-journal.jsonl')
    const exporter = createDiagnosticExporter(env, record => fs.appendFileSync(exportJournal, `${JSON.stringify(record)}\n`, { mode: 0o600 }))
    const provider = new NodeTracerProvider({
      resource: resourceFromAttributes({ 'service.name': scope }),
      spanProcessors: [new LangfuseSpanProcessor({
        exporter,
        publicKey: env.LANGFUSE_PUBLIC_KEY, secretKey: env.LANGFUSE_SECRET_KEY,
        baseUrl: env.LANGFUSE_BASE_URL, environment: env.LANGFUSE_ENVIRONMENT,
        mediaUploadEnabled: false,
        shouldExportSpan: ({ otelSpan }) => otelSpan.instrumentationScope.name === scope,
      })],
    })
    // Use a private provider; do not replace OpenCode's global OTel provider.
    const tracer = provider.getTracer(scope, '0.2.0')
    const root = tracer.startSpan(rootNameFor(env.UXD_TRACE_COMPONENT, env.UXD_TRACE_RUN_ID), { attributes: {
      'langfuse.observation.type': 'span', 'langfuse.internal.is_app_root': true,
      'user.id': env.LANGFUSE_USER_ID, 'session.id': env.UXD_TRACE_RUN_ID,
      'langfuse.trace.name': rootNameFor(env.UXD_TRACE_COMPONENT, env.UXD_TRACE_RUN_ID),
    } }, ROOT_CONTEXT)
    const hooks = createSessionHooks({ env, root, client,
      getExportDiagnostics: () => ({ ...exporter.snapshot(), journal_path: exportJournal }),
      startSpan: (name, attributes, parent, times) => tracer.startSpan(name, { attributes, ...times }, trace.setSpan(context.active(), parent)),
      flush: () => provider.forceFlush(), shutdown: () => provider.shutdown(),
      writeReceipt: receipt => {
        const temporary = `${env.UXD_TRACE_RECEIPT}.tmp`
        fs.writeFileSync(temporary, JSON.stringify(receipt, null, 2), { mode: 0o600 })
        fs.renameSync(temporary, env.UXD_TRACE_RECEIPT)
      },
    })
    process.once('beforeExit', () => hooks.dispose())
    return hooks
  })()
  globalThis[ownerKey] = { runID: env.UXD_TRACE_RUN_ID, promise }
  return promise
}
