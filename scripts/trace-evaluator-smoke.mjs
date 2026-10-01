#!/usr/bin/env node
// Convenience preset: still uses the terminal consent launcher, estimate-only.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
try {
  const options = process.argv.slice(2)
  if (options.length && (options.length !== 1 || options[0] !== '--dry-run')) throw new Error('Usage: eval-smoke [--dry-run]. This helper only supports estimate-only runs; paid approval flags are not accepted.')
  const file = path.join(root, 'tmp/evaluator-smoke.json')
  if (!fs.existsSync(file)) throw new Error('Prepare the local preset tmp/evaluator-smoke.json with workspace, prototype_url, model and scenario. See the tracing setup README.')
  const preset = JSON.parse(fs.readFileSync(file, 'utf8'))
  const names = ['workspace', 'prototype_url', 'model', 'scenario']
  if (!preset || typeof preset !== 'object' || Object.keys(preset).some(k => !names.includes(k)) || names.some(k => typeof preset[k] !== 'string' || !preset[k])) throw new Error('Smoke preset must contain only nonempty workspace, prototype_url, model and scenario strings.')
  const result = spawnSync(process.execPath, [path.join(root, '.opencode-tracing/launcher.mjs'),
    'evaluator', '--ticket', 'none', '--run-kind', 'manual-smoke',
    '--workspace', preset.workspace, '--prototype-url', preset.prototype_url,
    '--model', preset.model, '--scenario', preset.scenario, ...options,
  ], { cwd: root, stdio: 'inherit' })
  if (result.error) throw new Error('Unable to start the consent launcher.')
  process.exitCode = result.status ?? 2
} catch (error) { console.error(error.message); process.exitCode = 2 }
