#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { validateDirectory } = require('../scripts/validate-canonical-artifacts');
const { store } = require('../scripts/xray-cache');

const SCRIPT = path.resolve(__dirname, '..', 'scripts', 'assemble-phase-a-canonical.js');
const HASH_A = `sha256:${'a'.repeat(64)}`;
const HASH_B = `sha256:${'b'.repeat(64)}`;

function writeJson(directory, name, value) {
  fs.writeFileSync(path.join(directory, name), `${JSON.stringify(value, null, 2)}\n`);
}

function run(directory) {
  const result = spawnSync('node', [SCRIPT, directory, '--json'], { cwd: os.tmpdir(), encoding: 'utf8' });
  assert.strictEqual(result.status, 0, result.stdout + result.stderr);
  return JSON.parse(result.stdout);
}

function fixture(directory) {
  writeJson(directory, 'extract-state.json', {
    key: 'TEST-1', title: 'Canonical Phase A', extracted_at: '2026-09-11T12:00:00Z',
    ac_list: [
      { criterion_id: 'AC-1', source: 'jira', text: 'A user can save the form.' },
      { criterion_id: 'AC-2', source: 'jira', text: 'The API returns a response.' },
      { criterion_id: 'AC-3', source: 'jira', text: 'The workflow is intuitive.' },
    ],
    feature_context: { background: 'Background', problem_statement: null, user_stories: [], ui_enhancements: null, source_ticket: 'TEST-1' },
    tasks_to_be_done: [{ task: 'Save the form', source: '/form', covers_acs: ['AC-1', 'AC-2', 'AC-3'] }],
    journey_definitions: [{ id: 'journey-1', persona: 'data-scientist', source: 'Jira ACs', ac_ids: ['AC-1', 'AC-2', 'AC-3'] }],
    persona_selection: { selected: ['data-scientist+junior', 'data-scientist+senior'] },
  });
  writeJson(directory, 'mr-delta.json', { changed_files: ['src/Form.tsx'] });
  fs.writeFileSync(path.join(directory, 'evaluation-report.csv'), [
    '# ACCEPTANCE CRITERIA',
    'criterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action',
    'AC-1,jira,T1,A user can save the form.,,,,,,',
    'AC-2,jira,T3,The API returns a response.,PASS,Backend-only — no UI component to evaluate. Noted for engineering.,,,,',
    'AC-3,jira,T4,The workflow is intuitive.,,,,,,Review this qualitative criterion',
    '',
  ].join('\n'));
  writeJson(directory, 'consistency-report.json', {
    source: 'uxd-consistency-check', guidelines_version: '1', checked_at: '2026-09-11T12:00:00Z', degraded: false,
    source_mode: { ran: true, violations: [{
      guideline_id: 'no-custom-css', guideline_title: 'No custom CSS', category: 'foundations', severity: 'error',
      verdict: 'VIOLATION', confidence: 'high', review_candidate: false, file: 'src/Form.tsx', line: 4,
      property: 'style', value: 'color: red', description: 'Custom CSS found', suggestion: 'Use PatternFly tokens', check_method: 'automated',
    }] },
    visual_mode: { ran: false, screenshots_checked: 0, findings: [] },
    summary: { total_guidelines_checked: 2, violations: 1, warnings: 0, passes: 1 },
  });
  writeJson(directory, 'prototype-evidence.json', {
    schema_version: 1, capture_method: 'deterministic-baseline', prototype_url: 'https://example.test/form',
    captured_at: '2026-09-11T12:01:00Z', viewport: { width: 1440, height: 900 },
    screenshots: ['screenshots/journey-baseline.png'], model_screenshots: ['evidence/crops/journey-baseline-1.png'],
    capture: { id: 'capture-journey-baseline', viewport: { width: 1440, height: 900, device_scale_factor: 1 }, raw_image: { path: 'screenshots/journey-baseline.png', width: 1440, height: 900, sha256: HASH_A } },
    crops: [{
      id: 'evidence-journey-baseline-1', capture_id: 'capture-journey-baseline', kind: 'component', purpose: 'journey',
      subject: { role: 'button', name: 'Save', locator: '#save' }, crop: { x: 100, y: 100, width: 100, height: 40, padding: 16 },
      image: { path: 'evidence/crops/journey-baseline-1.png', width: 132, height: 72, sha256: HASH_B },
      dom: { text: 'Save', attributes: { 'aria-label': 'Save' } },
    }],
    input_metrics: { pixel_ratio: 0.01 },
    page: { title: 'Form', body_text: 'Form Save', headings: [{ level: 1, text: 'Form' }], controls: [{ tag: 'button', role: 'button', name: 'Save' }] },
  });
}

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'phase-a-canonical-'));
try {
  const directory = path.join(root, 'TEST-1', 'eval');
  fs.mkdirSync(directory, { recursive: true });
  fixture(directory);

  const first = run(directory);
  assert.strictEqual(first.cache, 'miss');
  assert.deepStrictEqual(first.parity, { ac_rows: 3, source_findings: 1, crop_items: 1 });
  assert.strictEqual(validateDirectory(directory).valid, true);
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(directory, 'evaluation.json'))).ac_results[0].verdict, 'NOT_RUN');
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(directory, 'evaluation.json'))).ac_results[1].verdict, 'PASS');
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(directory, 'actions.json'))).actions[0].kind, 'human-followup');

  const second = run(directory);
  assert.strictEqual(second.cache, 'hit');
  const state = JSON.parse(fs.readFileSync(path.join(directory, 'state.json')));
  assert.strictEqual(state.cache.decision, 'hit');
  assert.ok(state.phases.every(phase => phase.status === 'cached'));
  assert.strictEqual(validateDirectory(directory).valid, true);

  store(path.join(root, 'TEST-1', 'cache', 'full-v1'), directory);
  const full = run(directory);
  assert.strictEqual(full.cache, 'full-hit');
  assert.strictEqual(full.skip_paid_phases, true);

  const before = fs.readFileSync(path.join(directory, 'brief.json'), 'utf8');
  const badEvidence = JSON.parse(fs.readFileSync(path.join(directory, 'prototype-evidence.json')));
  badEvidence.crops[0].crop.x = 1400;
  writeJson(directory, 'prototype-evidence.json', badEvidence);
  const failed = spawnSync('node', [SCRIPT, directory, '--json'], { encoding: 'utf8' });
  assert.notStrictEqual(failed.status, 0);
  assert.strictEqual(fs.readFileSync(path.join(directory, 'brief.json'), 'utf8'), before);
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

console.log('PASS');
