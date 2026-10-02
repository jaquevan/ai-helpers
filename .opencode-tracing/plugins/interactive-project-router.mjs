import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { ROOT_CONTEXT } from '@opentelemetry/api'
import { LangfuseSpanProcessor } from '@langfuse/otel'
import { NodeTracerProvider } from '@opentelemetry/sdk-trace-node'
import { createDiagnosticExporter } from '../export-diagnostics.mjs'
import { loadRoutingConfig, credentialManager, bindingStore, privateFile } from '../interactive-project-config.mjs'
import { createInteractiveRouting } from '../interactive-routing-core.mjs'

const ownerKey = Symbol.for('uxd.interactive.project-router.v1')
const runtimeRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export default async function InteractiveProjectRouter(input, options = {}) {
  if (process.env.OPENCODE_DEDICATED_TRACE === '1' || process.env.UXD_TRACE_COMPONENT || process.env.UXD_TRACE_RUN_ID) return {}
  const workspace = fs.realpathSync(input.directory)
  const ownerID = `${input.project?.id || 'workspace'}:${workspace}`
  globalThis[ownerKey] ||= new Map()
  if (globalThis[ownerKey].has(ownerID)) return {} // Never return the same hooks twice.
  globalThis[ownerKey].set(ownerID, 'initializing')
  try {
    const config = loadRoutingConfig(options.configFile || path.join(os.homedir(), '.config/opencode/langfuse/interactive-routing.json'))
    const version = spawnSync('opencode', ['--version'], { encoding: 'utf8' })
    if (version.status !== 0 || version.stdout.trim() !== '1.18.31') throw new Error('Revalidate the interactive router for this OpenCode version')
    const { default: makeRecorder } = await import('../generated/interactive-recorder.mjs')
    const credentials = credentialManager(config)
    const verify = credentials.verify.bind(credentials)
    const store = bindingStore(config.stateDirectory, ownerID)
    const destinations = new Map()
    const ensure = async component => {
      const env = await verify(component)
      if (!destinations.has(component)) {
        const journal = path.join(store.directory, `${component}-exports.jsonl`)
        const exporter = createDiagnosticExporter(env, entry => {
          if (fs.existsSync(journal)) privateFile(journal)
          fs.appendFileSync(journal, `${JSON.stringify(entry)}\n`, { mode: 0o600 })
        })
        const processor = new LangfuseSpanProcessor({
          exporter, publicKey: env.LANGFUSE_PUBLIC_KEY, secretKey: env.LANGFUSE_SECRET_KEY, baseUrl: env.LANGFUSE_BASE_URL,
          environment: env.LANGFUSE_ENVIRONMENT || 'development', mediaUploadEnabled: false,
          shouldExportSpan: ({ otelSpan }) => otelSpan.instrumentationScope.name === 'opencode-langfuse-plugin',
        })
        destinations.set(component, { processor, exporter, env })
      } else {
        const existing = destinations.get(component).env
        if (existing.LANGFUSE_PUBLIC_KEY !== env.LANGFUSE_PUBLIC_KEY || existing.LANGFUSE_SECRET_KEY !== env.LANGFUSE_SECRET_KEY) throw new Error('Destination credentials changed; restart the backend before continuing')
      }
      return destinations.get(component)
    }
    // Wrap verification to construct the destination only after ownership succeeds.
    credentials.verify = async component => {
      return (await ensure(component)).env
    }
    let routing
    const provider = new NodeTracerProvider({ spanProcessors: [{
      onStart() {}, onEnd: span => routing.onEnd(span), forceFlush: async () => {}, shutdown: async () => {},
    }] })
    const privateTracer = provider.getTracer('opencode-langfuse-plugin', '0.4.0')
    // Context-manager-independent: pass explicit parent contexts to private spans.
    // The upstream recorder's context.with calls need a context manager. Rather
    // than registering a global provider/manager, use a scoped local ALS below.
    const { AsyncLocalStorage } = await import('node:async_hooks')
    const parentContext = new AsyncLocalStorage()
    const recorderTracer = { startSpan: (name, options, supplied) => {
      const current = supplied || parentContext.getStore() || ROOT_CONTEXT
      return privateTracer.startSpan(name, options, current)
    } }
    // Build-time adapter accepts a local context facade; no global ALS changes.
    const recorder = await makeRecorder({ client: input.client }, {
      tracer: recorderTracer, baseUrl: config.host, forceFlush: async () => {}, shutdown: async () => {},
      context: { active: () => parentContext.getStore() || ROOT_CONTEXT, with: (ctx, fn) => parentContext.run(ctx, fn) },
    })
    const revision = spawnSync('git', ['-C', path.join(runtimeRoot, '..'), 'rev-parse', 'HEAD'], { encoding: 'utf8' })
    const dirty = spawnSync('git', ['-C', path.join(runtimeRoot, '..'), 'status', '--porcelain'], { encoding: 'utf8' })
    const skillFiles = {
      creator: 'plugins/uxd-prototype/skills/uxd-prototype-create/SKILL.md',
      consistency: 'plugins/uxd-prototype/skills/uxd-consistency-check/SKILL.md',
      evaluator: 'plugins/uxd-prototype/skills/uxd-prototype-evaluate/SKILL.md',
    }
    const source = { runtime_revision: revision.status === 0 ? revision.stdout.trim() : 'unavailable',
      runtime_dirty: dirty.status !== 0 || Boolean(dirty.stdout.trim()), recorder_version: '0.4.0',
      router_sha256: crypto.createHash('sha256').update(['plugins/interactive-project-router.mjs', 'interactive-routing-core.mjs', 'interactive-project-config.mjs', 'generated/interactive-recorder.mjs'].map(file => fs.readFileSync(path.join(runtimeRoot, file), 'utf8')).join('\n')).digest('hex'),
      workspace_identity: crypto.createHash('sha256').update(workspace).digest('hex').slice(0, 24),
      ...Object.fromEntries(Object.entries(skillFiles).map(([component, file]) => [`expected_${component}_skill_sha256`, crypto.createHash('sha256').update(fs.readFileSync(path.join(runtimeRoot, '..', file))).digest('hex')])),
    }
    routing = createInteractiveRouting({ recorder, projects: config.projects, credentials, store, client: input.client, source, host: config.host,
      bufferLimitBytes: config.bufferLimitBytes,
      notify: async notice => {
        await input.client.app.log({ body: { service: 'uxd-routing', level: notice.error ? 'error' : 'info',
          message: notice.error || `Verified destination: ${notice.destination} / ${notice.projectId}; hosted ingestion not yet verified`,
          extra: { sessionID: notice.sessionID } } })
        try { await input.client.tui?.showToast({ body: { title: 'Langfuse routing', message: notice.error || `Verified ${notice.destination} project. Ingestion pending.`, variant: notice.error ? 'error' : 'info' } }) } catch { /* Backend logs and receipt remain available for GUI clients. */ }
      },
      deliver: (component, span) => {
        const target = destinations.get(component)
        if (!target) throw new Error('No verified destination exporter')
        span.attributes['langfuse.environment'] = target.env.LANGFUSE_ENVIRONMENT || 'development'
        span.attributes['langfuse.user.id'] = target.env.LANGFUSE_USER_ID
        target.processor.onEnd(span)
      },
      flush: async component => {
        const target = destinations.get(component)
        await target.processor.forceFlush()
        return target.exporter.snapshot()
      },
      shutdown: async () => {
        await Promise.all([...destinations.values()].map(target => target.processor.shutdown()))
        await provider.shutdown()
      },
    })
    let configurationError
    const hooks = { ...routing.hooks,
      config: async cfg => {
        if (cfg.experimental?.openTelemetry !== true) configurationError = 'Interactive tracing requires experimental.openTelemetry=true'
        const entries = (cfg.plugin || []).map(p => Array.isArray(p) ? p[0] : p)
        if (entries.some(p => typeof p === 'string' && p.includes('@langfuse/opencode-observability-plugin'))) configurationError = 'Remove the separate upstream Langfuse plugin before using the interactive router'
      },
      'chat.message': async (i, o) => {
        if (configurationError) throw new Error(configurationError)
        await routing.hooks['chat.message'](i, o)
      },
      'chat.params': async (i, o) => {
        if (configurationError) throw new Error(configurationError)
        await routing.hooks['chat.params'](i, o)
      },
      dispose: async () => { try { await routing.hooks.dispose() } finally { globalThis[ownerKey].delete(ownerID) } },
    }
    globalThis[ownerKey].set(ownerID, hooks)
    return hooks
  } catch {
    globalThis[ownerKey].delete(ownerID)
    // OpenCode swallows plugin-initialization failures. Install a blocking hook
    // instead of silently leaving component workflows untraced.
    const blocked = async () => { throw new Error('Interactive routing initialization failed. Check secure config, generated recorder and dependency pins; restart the backend. No workflow fallback permitted') }
    return { 'chat.message': blocked, 'chat.params': blocked, 'command.execute.before': blocked, 'tool.execute.before': blocked }
  }
}
