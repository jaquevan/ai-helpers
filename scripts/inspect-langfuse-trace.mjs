#!/usr/bin/env node
// Read-only v4 inspection. Output omits raw I/O and credentials.
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { readAssignments, traceURL } from '../.opencode-tracing/runtime.mjs'

try {
  const [component, option, value] = process.argv.slice(2)
  if (!['creator', 'consistency', 'evaluator'].includes(component) || !['--trace', '--recent', '--run-id'].includes(option)) throw new Error('Usage: node scripts/inspect-langfuse-trace.mjs <component> --trace TRACE_ID | --recent | --run-id RUN_ID')
  if (option === '--trace' && !/^[a-f0-9]{32}$/.test(value || '')) throw new Error('Invalid trace ID')
  const credentials = readAssignments(path.join(os.homedir(), '.config/opencode/langfuse', `${component}.env`))
  const host = (credentials.LANGFUSE_BASE_URL || credentials.LANGFUSE_HOST || '').replace(/\/$/, '')
  if (!host.startsWith('https://')) throw new Error('Expected an HTTPS Langfuse host.')
  const auth = Buffer.from(`${credentials.LANGFUSE_PUBLIC_KEY}:${credentials.LANGFUSE_SECRET_KEY}`).toString('base64')
  const query = new URLSearchParams({ limit: '100', fields: 'basic,metadata,model,usage,metrics,trace_context,io', expandMetadata: 'run_id,eval_run_id,status,billing_source,estimated_cost_usd,known_usage_cost_usd,usage_known,output_tokens' })
  if (option === '--trace') query.set('traceId', value)
  if (option === '--recent') { query.set('isRootObservation', 'true'); query.set('fromStartTime', new Date(Date.now() - 7 * 86400000).toISOString()) }
  if (option === '--run-id') query.set('filter', JSON.stringify([{ type: 'stringObject', column: 'metadata', key: 'eval_run_id', operator: '=', value }]))
  const observations = []
  let cursor
  do {
    if (cursor) query.set('cursor', cursor)
    const result = spawnSync('curl', ['--config', '-', '--fail', '--silent', '--show-error', '--max-time', '30', `${host}/api/public/v2/observations?${query}`], { input: `header = "Authorization: Basic ${auth}"\n`, encoding: 'utf8', maxBuffer: 32 * 1024 * 1024 })
    if (result.status !== 0) throw new Error('Read-only observations request failed; check network and component credentials.')
    const response = JSON.parse(result.stdout)
    for (const item of response.data || []) observations.push({
      id: item.id, name: item.name, type: item.type, trace_id: item.traceId,
      start_time: item.startTime, end_time: item.endTime,
      parent_id: item.parentObservationId, is_root: item.isRootObservation,
      user_id: item.userId, session_id: item.sessionId, model: item.model,
      level: item.level, metadata: Object.fromEntries(Object.entries(item.metadata || {}).filter(([key]) => ['component', 'run_id', 'eval_run_id', 'status', 'task_outcome', 'billing_source', 'estimated_cost_usd', 'known_usage_cost_usd', 'usage_known', 'output_tokens', 'cost_complete'].includes(key))),
      input_present: Boolean(item.input && item.input !== 'null'), output_present: Boolean(item.output && item.output !== 'null'),
      usage: item.usageDetails, cost: item.costDetails, total_cost: item.totalCost,
      trace_url: traceURL(host, credentials.LANGFUSE_PROJECT_ID, item.traceId),
    })
    cursor = response.meta?.cursor
  } while (cursor)
  console.log(JSON.stringify({ component, observations, count: observations.length }, null, 2))
} catch (error) { console.error(error.message); process.exitCode = 2 }
