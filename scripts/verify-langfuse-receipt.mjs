#!/usr/bin/env node
// Read-only remote reconciliation; writes only a new local verification sidecar.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { readAssignments } from '../.opencode-tracing/runtime.mjs'
import { verifyRemote } from '../.opencode-tracing/remote-verification.mjs'
try {
  const file = process.argv[2]
  if (!file) throw new Error('Usage: node scripts/verify-langfuse-receipt.mjs /absolute/path/to/receipt.json')
  const receipt = JSON.parse(fs.readFileSync(file, 'utf8'))
  if (!['creator', 'consistency', 'evaluator'].includes(receipt.component)) throw new Error('Invalid receipt component.')
  const credentials = readAssignments(path.join(os.homedir(), '.config/opencode/langfuse', `${receipt.component}.env`))
  const result = await verifyRemote(receipt, credentials)
  const target = path.join(path.dirname(file), `remote-verification-${Date.now()}.json`)
  fs.writeFileSync(target, JSON.stringify(result, null, 2), { mode: 0o600, flag: 'wx' })
  console.log(JSON.stringify({ ...result, verification_file: target }, null, 2))
  if (result.status !== 'verified') process.exitCode = 2
} catch (error) { console.error(error.message); process.exitCode = 2 }
