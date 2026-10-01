import fs from 'node:fs'
import path from 'node:path'
import { traceURL } from '../runtime.mjs'

export const rootNameFor = (component, runID) => `${component}/${runID}`
export const hasTraceCredentials = env => env.OPENCODE_DEDICATED_TRACE === '1' && ['LANGFUSE_PUBLIC_KEY', 'LANGFUSE_SECRET_KEY', 'LANGFUSE_BASE_URL', 'LANGFUSE_PROJECT_ID', 'UXD_TRACE_COMPONENT', 'UXD_TRACE_RUN_ID', 'UXD_TRACE_RECEIPT'].every(k => Boolean(env[k]))

export function redactor(env) {
  const secrets = Object.entries(env).filter(([k, v]) => /(?:KEY|TOKEN|SECRET|PASSWORD)$/.test(k) && typeof v === 'string' && v.length >= 8).map(([, v]) => v)
  return function redact(value) {
    if (typeof value === 'string') {
      for (const secret of secrets) value = value.split(secret).join('[REDACTED]')
      return value.replace(/data:[^;\s]+;base64,[a-zA-Z0-9+/=]+/g, '[BINARY_ATTACHMENT_OMITTED]')
        .replace(/\b(?:sk|pk)-[a-zA-Z0-9_-]{12,}/g, '[REDACTED]')
        .replace(/(Bearer\s+)[\w.+/=-]+/gi, '$1[REDACTED]')
        .replace(/((?:api[_-]?key|secret|password|access[_-]?token)\s*[=:]\s*)[^\s,;]+/gi, '$1[REDACTED]')
    }
    if (Array.isArray(value)) return value.map(redact)
    if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, /^(?:authorization|api[_-]?key|secret|password|access[_-]?token)$/i.test(k) ? '[REDACTED]' : /encrypted/i.test(k) ? '[OPAQUE_CONTENT_OMITTED]' : redact(v)]))
    return value
  }
}
export function usageDetails(tokens = {}) {
  // OpenCode input/output are exclusive of cache/reasoning (processor.ts getUsage).
  const fields = { input: tokens.input, output: tokens.output, reasoning: tokens.reasoning, cache_read_input_tokens: tokens.cache?.read ?? tokens.cache_read, cache_write_input_tokens: tokens.cache?.write ?? tokens.cache_write }
  return Object.fromEntries(Object.entries(fields).filter(([, v]) => Number.isFinite(v) && v >= 0))
}
export function generationAttributes(info) {
  const known = Number.isFinite(info.cost) && info.cost > 0
  return {
    'langfuse.observation.type': 'generation',
    'langfuse.observation.model.name': info.modelID || 'unknown',
    'langfuse.observation.usage_details': JSON.stringify(usageDetails(info.tokens)),
    ...(known ? { 'langfuse.observation.cost_details': JSON.stringify({ total: info.cost }) } : {}),
    'langfuse.observation.metadata': JSON.stringify({ provider: info.providerID, model: info.modelID, agent: info.agent, finish: info.finish, billing_source: known ? 'opencode-model-price-card' : 'unavailable', input_scope: 'available_conversation_context', model_invoked: true }),
  }
}
const wildcard = pattern => new RegExp(`^${pattern.replace(/[.+^${}()|[\]\\]/g, '\\$&').replace(/\*/g, '.*').replace(/\?/g, '.')}$`)
export function scopeWorkspace(config, workspace) {
  if (!workspace) throw new Error('Missing trace workspace.')
  const check = permission => {
    if (permission === 'deny' || permission?.['*'] === 'deny' || permission?.external_directory === 'deny') throw new Error('Existing external-directory deny prevents this trace workspace. Review the policy in a plain terminal.')
    const rules = permission?.external_directory
    if (rules && typeof rules === 'object') for (const [pattern, action] of Object.entries(rules)) {
      const expanded = pattern.replace(/^~(?=\/)/, process.env.HOME || '~')
      if (action === 'deny' && (wildcard(expanded).test(workspace) || wildcard(expanded).test(`${workspace}/`) || expanded.startsWith(`${workspace}/`))) throw new Error('An existing external-directory deny overlaps the trace workspace. It will not be overridden.')
    }
  }
  check(config.permission)
  for (const agent of Object.values(config.agent || {})) check(agent.permission)
  const permission = typeof config.permission === 'string' ? { '*': config.permission } : { ...config.permission }
  const rules = permission.external_directory
  const existing = typeof rules === 'string' ? { '*': rules } : rules || {}
  // Keep even wildcard denies that intersect only a deeper subtree last.
  const denies = Object.fromEntries(Object.entries(existing).filter(([, action]) => action === 'deny'))
  const other = Object.fromEntries(Object.entries(existing).filter(([, action]) => action !== 'deny'))
  permission.external_directory = { ...other, [workspace]: 'allow', [`${workspace}/**`]: 'allow', ...denies }
  config.permission = permission
}
export function artifactManifest(env, finalText = '') {
  const base = path.join(env.UXD_TRACE_WORKSPACE, '.artifacts', env.UXD_TRACE_TICKET, 'eval')
  const artifacts = []
  const contained = file => {
    try {
      const relative = path.relative(fs.realpathSync(env.UXD_TRACE_WORKSPACE), fs.realpathSync(file))
      return relative !== '..' && !relative.startsWith(`..${path.sep}`) && !path.isAbsolute(relative)
    } catch { return false }
  }
  const addFile = (file, kind, ownership) => {
    if (!path.isAbsolute(file) || !contained(file)) return
    const existing = artifacts.find(a => a.path === file)
    if (existing) { if (ownership === 'session_reported') existing.run_ownership = ownership; return }
    artifacts.push({ kind, path: file, access: 'local', run_ownership: ownership })
  }
  for (const name of ['evaluation-report.html', 'journey-log.json', 'screenshots', 'runs', 'cost-ledger.jsonl']) {
    const file = path.join(base, name)
    addFile(file, name, 'workspace_latest_not_verified')
  }
  const urlFile = path.join(base, 'report-url.txt')
  if (contained(urlFile) && fs.statSync(urlFile).size <= 2048) {
    const url = fs.readFileSync(urlFile, 'utf8').trim()
    if (/^https?:\/\/\S+$/.test(url)) artifacts.push({ kind: 'published_report', url, access: 'hosted_access_not_verified', run_ownership: 'workspace_latest_not_verified' })
  }
  // Creator smoke keys are workspace-derived, not literally "none". Consume
  // explicit scorecard references instead of guessing or scanning all artifacts.
  const scorecard = finalText.slice(Math.max(0, finalText.lastIndexOf('[UXD-SCORECARD]')))
  const declaredPaths = scorecard.match(/^report_artifact:\s*(.+)$/im)?.[1] || ''
  for (const value of declaredPaths.split(';')) {
    const file = value.trim().replace(/^[`'"]|[`'"]$/g, '')
    addFile(file, 'reported_artifact', 'session_reported')
    if (path.isAbsolute(file)) addFile(path.join(path.dirname(file), `scorecard-${env.UXD_TRACE_RUN_ID}.md`), 'scorecard', 'session_reported')
  }
  const prototypeURL = scorecard.match(/^prototype_url:\s*(https?:\/\/\S+)\s*$/im)?.[1] || env.UXD_TRACE_PROTOTYPE_URL
  if (/^https?:\/\/\S+$/.test(prototypeURL || '')) artifacts.push({ kind: 'prototype', url: prototypeURL, access: /\/\/(?:localhost|127\.0\.0\.1|\[::1\])(?::|\/)/.test(prototypeURL) ? 'local_server' : 'hosted_access_not_verified', run_ownership: 'session_reported' })
  return artifacts
}

// Lifecycle is independent of the exporter so event-order, dedup and flush tests
// exercise the real implementation without exporting synthetic traces.
export function createSessionHooks({ env, root, startSpan, flush, shutdown, client, writeReceipt, getExportDiagnostics = () => null, log = console.error }) {
  const redact = redactor(env)
  const json = value => JSON.stringify(redact(value))
  const runID = env.UXD_TRACE_RUN_ID
  const traceID = root.spanContext().traceId
  const url = traceURL(env.LANGFUSE_BASE_URL, env.LANGFUSE_PROJECT_ID, traceID)
  const sessions = new Set(), turns = new Map(), tools = new Map(), parts = new Map(), completed = new Set(), pending = new Set(), failedTools = new Set()
  const userInputs = new Map(), taskParents = new Map()
  let owner, closing, closed = false, failure = false, permissionDenied = false, finalText = ''
  const started = Date.now()
  const stats = { user_turns: 0, generations: 0, tool_calls: 0, tool_failures: 0, known_session_cost_usd: 0, unpriced_generations: 0, tokens: {} }
  const receipt = { run_id: runID, component: env.UXD_TRACE_COMPONENT, trace_id: traceID, trace_name: rootNameFor(env.UXD_TRACE_COMPONENT, runID), trace_url: url, input_fingerprint: env.UXD_TRACE_INPUT_FINGERPRINT, source_revision: env.UXD_TRACE_SOURCE_REVISION, source_dirty: env.UXD_TRACE_SOURCE_DIRTY === 'true', export_status: 'pending', remote_ingestion: 'not_verified' }
  receipt.expected_observations = [{ id: root.spanContext().spanId, name: receipt.trace_name, type: 'SPAN' }]
  receipt.source_context = env.UXD_TRACE_CONTEXT_FILE ? { path: env.UXD_TRACE_CONTEXT_FILE, sha256: env.UXD_TRACE_CONTEXT_SHA256, atlassian_access: env.UXD_TRACE_OFFLINE_ATLASSIAN === 'true' ? 'offline_snapshot_only' : 'default' } : null
  const common = () => ({ 'user.id': env.LANGFUSE_USER_ID, 'session.id': runID, 'langfuse.trace.name': receipt.trace_name, 'langfuse.trace.tags': ['team:uxd', `component:${env.UXD_TRACE_COMPONENT}`, `run_kind:${env.UXD_TRACE_RUN_KIND}`] })
  const child = (name, attributes, parent = root, times = {}) => {
    const span = startSpan(name, { ...common(), ...attributes }, parent, times)
    receipt.expected_observations.push({ id: span.spanContext().spanId, name, type: String(attributes['langfuse.observation.type']).toUpperCase() })
    return span
  }
  const error = (span, message) => { span.setStatus({ code: 2, message: redact(message) }); span.setAttribute('langfuse.observation.level', 'ERROR') }
  function save(extra = {}) { Object.assign(receipt, extra); writeReceipt(redact(receipt)) }
  save()
  log(`Hosted trace: ${url} (ingestion pending)\nRun receipt: ${env.UXD_TRACE_RECEIPT}`)
  async function finishMessage(info) {
    const key = `${info.sessionID}/${info.id}`
    if (closed || completed.has(key) || !sessions.has(info.sessionID)) return
    completed.add(key)
    let messages = [], output = [...(parts.get(key)?.values() || [])], input = userInputs.get(info.sessionID) || []
    let contextAvailable = false
    try {
      const response = await client?.session.messages({ path: { id: info.sessionID } })
      messages = response?.data || []
      const index = messages.findIndex(m => m.info.id === info.id)
      if (index >= 0) {
        output = messages[index].parts
        input = messages.slice(0, index).map(m => ({ role: m.info.role, parts: m.parts }))
        contextAvailable = true
      }
    } catch { /* buffered parts and user input remain explicit fallbacks */ }
    const span = child('opencode.generation', {
      ...generationAttributes(info),
      'langfuse.observation.input': json({ scope: contextAvailable ? 'available_conversation_context_not_wire_prompt' : 'buffered_user_input_only', messages: input }),
      'langfuse.observation.output': json({ parts: output, message_id: info.id, finish: info.finish, error: info.error || null }),
    }, turns.get(info.sessionID) || taskParents.get(info.sessionID) || root, { startTime: new Date(info.time.created) })
    if (info.error) { error(span, info.error.name || 'Model failed'); failure = true }
    span.end(new Date(info.time.completed))
    parts.delete(key)
    stats.generations++
    if (Number.isFinite(info.cost) && info.cost > 0) stats.known_session_cost_usd += info.cost
    else stats.unpriced_generations++
    for (const [field, count] of Object.entries(usageDetails(info.tokens))) stats.tokens[field] = (stats.tokens[field] || 0) + count
    if (info.sessionID === owner) finalText = output.filter(p => p.type === 'text').map(p => p.text).join('\n')
  }
  function close(status = 'ended') {
    if (closing) return closing
    closing = (async () => {
      // Idle can precede the final assistant completion event on error paths.
      // Reconcile persisted messages once before finalizing accounting.
      await new Promise(resolve => setTimeout(resolve, 100))
      if (owner && client?.session.messages) {
        try {
          const response = await client.session.messages({ path: { id: owner } })
          for (const message of response.data || []) if (message.info.role === 'assistant' && message.info.time?.completed) await finishMessage(message.info)
        } catch { /* receipt remains explicit about captured, not billed totals */ }
      }
      await Promise.allSettled([...pending])
      closed = true
      for (const { span } of tools.values()) { error(span, 'Tool did not report completion'); span.end(); stats.tool_failures++ }
      for (const span of turns.values()) span.end()
      tools.clear(); turns.clear()
      let pipeline = null
      try {
        const result = JSON.parse(fs.readFileSync(env.UXD_TRACE_PIPELINE_RESULT, 'utf8'))
        if (result.run_id === runID && result.trace_id === traceID) pipeline = result
      } catch { /* no direct pipeline ran, or no structured result was produced */ }
      const declared = finalText.match(/^outcome_status:\s*(completed|blocked|failed)\s*$/im)?.[1]
      const taskOutcome = status === 'failed' || failure || pipeline?.status === 'failed' || pipeline?.cost_ledger_status?.startsWith('failed') ? 'failed' : permissionDenied || pipeline?.status === 'blocked' ? 'blocked' : declared || 'unconfirmed'
      const summary = { ...stats, duration_ms: Date.now() - started, session_cost_complete: stats.unpriced_generations === 0 && stats.generations > 0, direct_pipeline: pipeline, task_outcome: taskOutcome, session_status: status, artifacts: artifactManifest(env, finalText) }
      root.setAttribute('langfuse.observation.output', json({ final_response: finalText, ...summary }))
      root.setAttribute('langfuse.observation.metadata', json({ component: env.UXD_TRACE_COMPONENT, run_id: runID, ticket: env.UXD_TRACE_TICKET, run_kind: env.UXD_TRACE_RUN_KIND, input_fingerprint: env.UXD_TRACE_INPUT_FINGERPRINT, source_revision: env.UXD_TRACE_SOURCE_REVISION, trace_scope: 'full_session', telemetry: 'full_raw_secret_redacted', consent: 'typed_TRACE_confirmation', evaluator_paid_approval: env.UXD_TRACE_ESTIMATE_APPROVED, ...summary }))
      if (taskOutcome === 'failed' || taskOutcome === 'blocked') error(root, taskOutcome)
      root.end()
      save({ ...summary, export_status: 'flushing' })
      try {
        await flush(); await shutdown()
        const delivery = getExportDiagnostics()
        const deliveryIssue = delivery && (delivery.batches_failed > 0 || delivery.pending_batches > 0)
        save({ export_status: deliveryIssue ? 'flush_completed_with_export_errors' : 'flush_completed', export_delivery: delivery })
        if (deliveryIssue) log('Earlier or unfinished span exports were recorded; inspect export_delivery and the remote verification. Do not rerun model work.')
      }
      catch { save({ export_status: 'flush_failed', export_delivery: getExportDiagnostics() }); log('Langfuse export failed; consult the run receipt. Remote ingestion is unverified.') }
    })()
    return closing
  }
  return {
    config: async cfg => {
      scopeWorkspace(cfg, env.UXD_TRACE_WORKSPACE)
      if (env.UXD_TRACE_OFFLINE_ATLASSIAN === 'true') {
        // Apply after config merging so inherited inline config cannot re-enable
        // the known Atlassian server for a snapshot-only session.
        cfg.mcp = { ...cfg.mcp, atlassian: { enabled: false } }
        for (const name of Object.keys(cfg.mcp)) if (/atlassian|jira|confluence/i.test(name)) cfg.mcp[name] = { enabled: false }
      }
    },
    'chat.message': async (input, output) => {
      if (closed || closing) return
      if (!owner) { owner = input.sessionID; sessions.add(owner); save({ opencode_session_id: owner }) }
      if (!sessions.has(input.sessionID)) return
      turns.get(input.sessionID)?.end()
      const turn = child('opencode.turn', { 'langfuse.observation.type': 'agent', 'langfuse.observation.input': json(output.parts), 'langfuse.observation.metadata': json({ opencode_session_id: input.sessionID }) }, taskParents.get(input.sessionID) || root)
      turns.set(input.sessionID, turn)
      userInputs.set(input.sessionID, output.parts)
      stats.user_turns++
    },
    'tool.execute.before': async (input, output) => {
      if (closed || closing || !sessions.has(input.sessionID) || tools.has(input.callID)) return
      const span = child(input.tool, { 'langfuse.observation.type': 'tool', 'langfuse.observation.input': json(output.args) }, turns.get(input.sessionID) || root)
      tools.set(input.callID, { span, sessionID: input.sessionID, tool: input.tool })
      stats.tool_calls++
    },
    'tool.execute.after': async (input, output) => {
      const tool = tools.get(input.callID)
      if (!tool) return
      tool.span.setAttribute('langfuse.observation.output', json({ title: output.title, output: output.output, metadata: output.metadata }))
      const exit = output.metadata?.exit ?? output.metadata?.exitCode ?? output.metadata?.exit_code
      if (typeof exit === 'number' && exit !== 0 || output.metadata?.timeout === true) {
        error(tool.span, output.metadata?.timeout ? 'Tool timed out' : `Tool exited ${exit}`)
        if (!failedTools.has(input.callID)) { failedTools.add(input.callID); stats.tool_failures++ }
      }
      tool.span.end(); tools.delete(input.callID)
    },
    'shell.env': async (input, output) => {
      output.env.UXD_TRACE_RUN_ID = runID
      output.env.UXD_TRACE_RECEIPT = env.UXD_TRACE_RECEIPT
      const tool = tools.get(input.callID)
      if (!tool) return
      output.env.LANGFUSE_TRACE_ID = traceID
      output.env.LANGFUSE_PARENT_SPAN_ID = tool.span.spanContext().spanId
    },
    event: async ({ event }) => {
      if (closed) return
      const props = event.properties || {}
      if (event.type === 'session.created' && sessions.has(props.info?.parentID)) {
        sessions.add(props.info.id)
        const candidates = [...tools.values()].filter(t => t.sessionID === props.info.parentID && t.tool === 'task')
        if (candidates.length === 1) taskParents.set(props.info.id, candidates[0].span)
      }
      if (event.type === 'permission.replied' && sessions.has(props.sessionID) && props.reply === 'reject') permissionDenied = true
      if (event.type === 'message.part.updated') {
        const part = props.part
        if (!part || !sessions.has(part.sessionID)) return
        const key = `${part.sessionID}/${part.messageID}`
        if (!completed.has(key)) { if (!parts.has(key)) parts.set(key, new Map()); parts.get(key).set(part.id, part) }
        if (part.type === 'tool' && part.state?.status === 'error' && !failedTools.has(part.callID)) {
          failedTools.add(part.callID)
          stats.tool_failures++
          const tool = tools.get(part.callID)
          if (tool) {
            error(tool.span, part.state.error); tool.span.setAttribute('langfuse.observation.output', json(part.state)); tool.span.end(); tools.delete(part.callID)
          }
          if (/permission|reject|denied/i.test(part.state.error || '')) permissionDenied = true
        }
      }
      if (event.type === 'message.updated' && props.info?.role === 'assistant' && props.info.time?.completed) {
        const promise = finishMessage(props.info)
        pending.add(promise)
        try { await promise } finally { pending.delete(promise) }
      }
      if (props.sessionID !== owner) return
      if (event.type === 'session.error') { failure = true; return }
      if (event.type === 'session.idle' || event.type === 'session.status' && props.status?.type === 'idle') return close()
    },
    dispose: () => close('disposed'),
  }
}
