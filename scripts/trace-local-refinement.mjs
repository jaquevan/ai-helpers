#!/usr/bin/env node
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
try {
  const options = process.argv.slice(2)
  if (options.length && (options.length !== 1 || options[0] !== '--dry-run')) throw new Error('Usage: refine-maas [--dry-run]. This helper starts only a snapshot-backed creator refinement.')
  const file = path.join(root, 'tmp/refinement.json')
  if (!fs.existsSync(file)) throw new Error('Prepare tmp/refinement.json with ticket, workspace, prototype_url, model, scenario and context_file.')
  const preset = JSON.parse(fs.readFileSync(file, 'utf8'))
  const fields = ['ticket', 'workspace', 'prototype_url', 'model', 'scenario', 'context_file']
  if (!preset || typeof preset !== 'object' || Object.keys(preset).some(k => !fields.includes(k)) || fields.some(k => typeof preset[k] !== 'string' || !preset[k])) throw new Error('Invalid refinement preset fields.')
  const result = spawnSync(process.execPath, [path.join(root, '.opencode-tracing/launcher.mjs'),
    'creator', '--ticket', preset.ticket, '--run-kind', 'manual-designer-test',
    '--workspace', preset.workspace, '--prototype-url', preset.prototype_url,
    '--model', preset.model, '--scenario', preset.scenario,
    '--context-file', preset.context_file, '--offline-atlassian', ...options,
  ], { cwd: root, stdio: 'inherit' })
  if (result.error) throw new Error('Unable to start the consent launcher.')
  process.exitCode = result.status ?? 2
} catch (error) { console.error(error.message); process.exitCode = 2 }
