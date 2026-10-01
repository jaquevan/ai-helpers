import assert from 'node:assert/strict'
import test from 'node:test'
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

test('short preset runner always launches estimate-only and rejects paid approval flags', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'trace-smoke-preset-'))
  try {
    for (const name of ['scripts', 'tmp', '.opencode-tracing']) fs.mkdirSync(path.join(root, name))
    const source = fileURLToPath(new URL('../../scripts/trace-evaluator-smoke.mjs', import.meta.url))
    const runner = path.join(root, 'scripts/trace-evaluator-smoke.mjs')
    fs.copyFileSync(source, runner)
    fs.writeFileSync(path.join(root, '.opencode-tracing/launcher.mjs'), 'console.log(JSON.stringify(process.argv.slice(2)))')
    fs.writeFileSync(path.join(root, 'tmp/evaluator-smoke.json'), JSON.stringify({ workspace: root, prototype_url: 'http://127.0.0.1:8765/', model: 'test/model', scenario: 'Estimate the welcome screen.' }))
    const dry = spawnSync(process.execPath, [runner, '--dry-run'], { encoding: 'utf8' })
    assert.equal(dry.status, 0, dry.stderr)
    const args = JSON.parse(dry.stdout)
    assert.equal(args[0], 'evaluator')
    assert.equal(args[args.indexOf('--ticket') + 1], 'none')
    assert.equal(args[args.indexOf('--run-kind') + 1], 'manual-smoke')
    assert.ok(args.includes('--dry-run'))
    assert.ok(!args.includes('--approve-estimate'))
    const paid = spawnSync(process.execPath, [runner, '--approve-estimate'], { encoding: 'utf8' })
    assert.equal(paid.status, 2)
    assert.equal(paid.stdout, '')
    assert.match(paid.stderr, /paid approval flags are not accepted/)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
