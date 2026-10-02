#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import os from 'node:os'
import { createRequire } from 'node:module'
import { spawnSync } from 'node:child_process'
import { loadRoutingConfig, credentialManager, privateFile, components } from '../.opencode-tracing/interactive-project-config.mjs'
import { compareInteractiveObservations } from '../.opencode-tracing/interactive-verification.mjs'

try {
  const args = process.argv.slice(2)
  if (args.length !== 1) throw new Error('Usage: node scripts/verify-interactive-langfuse.mjs /absolute/path/to/session-state.json')
  const config = loadRoutingConfig(path.join(os.homedir(), '.config/opencode/langfuse/interactive-routing.json'))
  const stateFile = path.resolve(args[0])
  const relative = path.relative(config.stateDirectory, stateFile)
  if (relative.startsWith('..') || path.isAbsolute(relative)) throw new Error('Select a session receipt inside the configured private state directory')
  const state = JSON.parse(fs.readFileSync(privateFile(stateFile), 'utf8'))
  if (!components.includes(state.destination) || state.projectId !== config.projects[state.destination].projectId || !Array.isArray(state.receipts)) throw new Error('Receipt destination does not match configured project')
  const manager = credentialManager(config)
  const require = createRequire(new URL('../.opencode-tracing/package.json', import.meta.url))
  const cli = path.join(path.dirname(require.resolve('@langfuse/cli/package.json')), 'bin/langfuse.mjs')
  const traces = [...new Set(state.receipts.flatMap(r => r.expected || []).map(o => o.traceId))]
  if (!traces.length) throw new Error('Receipt has no exported observations to verify')
  if (traces.some(id => !/^[a-f0-9]{32}$/.test(id))) throw new Error('Receipt contains invalid trace IDs')
  const perProject = {}
  for (const component of components) {
    const c = await manager.verify(component)
    perProject[component] = []
    for (const trace of traces) {
      const response = spawnSync(process.execPath, [cli, 'api', 'observations', 'list', '--trace-id', trace,
        '--fields', 'core,basic,metadata,model,usage,io', '--all', '--max-items', '20000', '--json'], {
        env: { ...process.env, ...c, LANGFUSE_HOST: c.LANGFUSE_BASE_URL }, encoding: 'utf8', timeout: 60000, maxBuffer: 32 * 1024 * 1024,
      })
      if (response.status !== 0) throw new Error('Read-only observation lookup unavailable; raw CLI output withheld')
      let rows, body
      try { body = JSON.parse(response.stdout).body; rows = body?.data } catch { throw new Error('Invalid CLI response; raw output withheld') }
      if (!Array.isArray(rows)) throw new Error('Unexpected CLI observation response')
      if (body.meta?.truncated) throw new Error('Observation lookup truncated; project exclusivity cannot be verified')
      perProject[component].push(...rows)
    }
  }
  const { [state.destination]: intended, ...others } = perProject
  const verification = compareInteractiveObservations(state, intended, others)
  verification.session_url = `${config.host}/project/${encodeURIComponent(state.projectId)}/sessions/${encodeURIComponent(state.sessionID)}`
  verification.trace_urls = traces.map(id => `${config.host}/project/${encodeURIComponent(state.projectId)}/traces/${id}`)
  const target = `${stateFile}.verification-${Date.now()}.json`
  fs.writeFileSync(target, JSON.stringify(verification, null, 2), { flag: 'wx', mode: 0o600 })
  console.log(JSON.stringify({ ...verification, verification_file: target }, null, 2))
  if (verification.status !== 'verified') process.exitCode = 1
} catch { console.error('Independent verification unavailable or incomplete. Check secure config, state file and project access. No model was run and no trace was modified.'); process.exitCode = 2 }
