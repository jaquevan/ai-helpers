#!/usr/bin/env node
// Interactive estimates only. Paid execution needs a separately reviewed bridge
// and approval/cap integration; this wrapper never interprets chat as approval.
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import crypto from 'node:crypto'
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { loadRoutingConfig, credentialManager, privateDirectory } from '../.opencode-tracing/interactive-project-config.mjs'

try {
  const args = process.argv.slice(2)
  if (process.env.UXD_INTERACTIVE_COMPONENT !== 'evaluator' || !process.env.UXD_INTERACTIVE_SESSION_ID) throw new Error()
  if (!args.includes('--estimate-only') || args.some(a => /approve|standalone|trace-id|parent-span/i.test(a)) || args.length < 2) throw new Error()
  const runtime = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
  if (fs.realpathSync(args[0]) !== fs.realpathSync(path.join(runtime, '.venv/bin/python')) ||
    fs.realpathSync(args[1]) !== fs.realpathSync(path.join(runtime, 'plugins/uxd-prototype/skills/uxd-prototype-evaluate/scripts/langfuse-trace-pipeline.py')) ||
    !args.includes('--personal-run')) throw new Error()
  const config = loadRoutingConfig(path.join(os.homedir(), '.config/opencode/langfuse/interactive-routing.json'))
  const c = await credentialManager(config).verify('evaluator')
  if (!c.OPENAI_API_KEY) throw new Error()
  const runID = `interactive-estimate-${crypto.randomUUID()}`
  const dir = path.join(config.stateDirectory, 'evaluator-estimates', runID)
  privateDirectory(dir)
  fs.writeFileSync(path.join(dir, 'link.json'), JSON.stringify({ run_id: runID, opencode_session_id: process.env.UXD_INTERACTIVE_SESSION_ID,
    project_id: c.LANGFUSE_PROJECT_ID, relationship: 'same_project_separate_trace', parent_span: null, direct_paid_approval: false }), { mode: 0o600 })
  const env = { ...process.env, ...c, LANGFUSE_ENABLED: '1', UXD_TRACE_RUN_ID: runID,
    UXD_TRACE_PIPELINE_RESULT: path.join(dir, 'result.json'), UXD_TRACE_ESTIMATE_APPROVED: 'false' }
  for (const key of ['OPENCODE_DEDICATED_TRACE', 'UXD_TRACE_COMPONENT', 'LANGFUSE_TRACE_ID', 'LANGFUSE_PARENT_SPAN_ID']) delete env[key]
  const child = spawn(args[0], args.slice(1), { env, stdio: 'inherit' })
  child.on('error', () => { console.error('Estimator could not start. No retries permitted.'); process.exitCode = 2 })
  child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 130 : 1) })
} catch { console.error('Interactive evaluator estimate refused. Use a verified evaluator session, --estimate-only and local evaluator credentials. Paid approval is not supported by this wrapper.'); process.exitCode = 2 }
