import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

test('refinement helper routes through consent launcher with offline Atlassian snapshot', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-refinement-'))
  try {
    for (const dir of ['scripts', 'tmp', '.opencode-tracing']) fs.mkdirSync(path.join(root, dir))
    const runner = path.join(root, 'scripts/trace-local-refinement.mjs')
    fs.copyFileSync(fileURLToPath(new URL('../../scripts/trace-local-refinement.mjs', import.meta.url)), runner)
    fs.writeFileSync(path.join(root, '.opencode-tracing/launcher.mjs'), 'console.log(JSON.stringify(process.argv.slice(2)))')
    fs.writeFileSync(path.join(root, 'tmp/refinement.json'), JSON.stringify({ ticket: 'TEST-1', workspace: root, prototype_url: 'http://127.0.0.1:9001/', model: 'test/model', scenario: 'Refine the existing mock', context_file: path.join(root, 'context.md') }))
    const dry = spawnSync(process.execPath, [runner, '--dry-run'], { encoding: 'utf8' })
    assert.equal(dry.status, 0, dry.stderr)
    const args = JSON.parse(dry.stdout)
    assert.equal(args[0], 'creator')
    assert.ok(args.includes('--offline-atlassian'))
    assert.ok(args.includes('--context-file'))
    assert.equal(args[args.indexOf('--ticket') + 1], 'TEST-1')
    const bypass = spawnSync(process.execPath, [runner, '--approve-estimate'], { encoding: 'utf8' })
    assert.equal(bypass.status, 2)
    assert.equal(bypass.stdout, '')
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
