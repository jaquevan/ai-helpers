#!/usr/bin/env node
// A dedicated wrapper for consent-launcher calls. No .env.local fallback.
import { spawn } from 'node:child_process'
import fs from 'node:fs'
import { readAssignments } from '../.opencode-tracing/runtime.mjs'
try {
  if (process.env.OPENCODE_DEDICATED_TRACE !== '1' || !process.env.UXD_EVAL_ENV_FILE) throw new Error('Use the consent launcher for traced evaluator execution.')
  if (!/^[a-f0-9]{32}$/.test(process.env.LANGFUSE_TRACE_ID || '') || !/^[a-f0-9]{16}$/.test(process.env.LANGFUSE_PARENT_SPAN_ID || '')) throw new Error('Missing evaluator trace bridge. Stop; do not start a separate trace or paid phase.')
  const args = process.argv.slice(2)
  if (!args.length) throw new Error('Usage: node scripts/trace-eval-run.mjs <python> <pipeline> [args...]')
  const approved = process.env.UXD_TRACE_ESTIMATE_APPROVED === 'true'
  if (approved ? !args.includes('--approve-estimate') || args.includes('--estimate-only') : !args.includes('--estimate-only') || args.includes('--approve-estimate')) throw new Error('Evaluator flags must match this launcher invocation: estimate-only, or separately approved execution. No model started.')
  const credentials = readAssignments(process.env.UXD_EVAL_ENV_FILE)
  if (!process.env.UXD_TRACE_PIPELINE_RESULT) throw new Error('Missing launcher result path.')
  try { fs.closeSync(fs.openSync(`${process.env.UXD_TRACE_PIPELINE_RESULT}.started`, 'wx', 0o600)) }
  catch { throw new Error('This session already attempted its evaluator pipeline. Stop; do not retry.') }
  // Preserve launcher identity/bridge rather than allowing an env file to reset it.
  const env = { ...process.env, OPENAI_API_KEY: credentials.OPENAI_API_KEY, LANGFUSE_ENABLED: '1' }
  const child = spawn(args[0], args.slice(1), { env, stdio: 'inherit' })
  child.on('error', () => { console.error('Unable to start evaluator interpreter.'); process.exitCode = 2 })
  child.on('exit', (code, signal) => {
    process.exitCode = code ?? (signal ? 130 : 1)
    const target = env.UXD_TRACE_PIPELINE_RESULT
    if (target && !fs.existsSync(target)) {
      fs.writeFileSync(target, JSON.stringify({ run_id: env.UXD_TRACE_RUN_ID, trace_id: env.LANGFUSE_TRACE_ID, status: 'failed', exit_code: process.exitCode, cost_usd: null, known_usage_cost_usd: null, usage_known: false, billing_source: 'unavailable', reason: 'Pipeline exited without a structured result' }, null, 2), { mode: 0o600 })
    }
  })
} catch (error) { console.error(error.message); process.exitCode = 2 }
