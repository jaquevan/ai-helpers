#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { validateDirectory } = require('../scripts/validate-canonical-artifacts');

const SKILL = path.resolve(__dirname, '..');
const SCRIPT = path.join(SKILL, 'scripts', 'sync-phase-b-canonical.js');
const FIXTURE = path.join(SKILL, 'tests', 'fixtures', 'canonical', 'v1', 'valid');
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAFgwJ/lVbJ6wAAAABJRU5ErkJggg==', 'base64');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'phase-b-canonical-'));
try {
  const directory = path.join(root, 'PROJ-123', 'eval');
  fs.mkdirSync(path.join(directory, 'screenshots'), { recursive: true });
  for (const name of ['brief.json', 'evaluation.json', 'evidence.json', 'actions.json', 'state.json']) fs.copyFileSync(path.join(FIXTURE, name), path.join(directory, name));
  fs.writeFileSync(path.join(directory, 'screenshots', 'journey-final.png'), PNG);
  fs.writeFileSync(path.join(directory, 'journey-log.json'), JSON.stringify({
    evaluated_at: '2026-09-11T17:00:00Z',
    criterion_results: [{ criterion_id: 'AC-1', verdict: 'PASS', rationale: 'The form saved.', evidence: 'screenshots/journey-final.png', fix_action: '', fix_file: '', human_action: '' }],
    journeys: [{ id: 'journey-1', persona: 'persona-data-scientist-junior', source: 'Jira ACs', verdict: 'PASS', ac_ids: ['AC-1'], steps: [{ step: 1, action: 'Click Save', result: 'success', screenshot: 'screenshots/journey-final.png', narration: 'Saved' }] }],
    usability_dimensions: { dimensions: [{ id: 'workflow-continuity', name: 'Workflow continuity', composite_score: 2.5, confidence: 'high', scores: { 'persona-data-scientist-junior': { score: 3 } } }], overall_score: 2.5, max_score: 3, personas_evaluated: ['persona-data-scientist-junior'], persona_overlays: [] },
  }, null, 2));
  fs.writeFileSync(path.join(directory, 'persona-results.json'), JSON.stringify([{ persona: 'persona-data-scientist-junior', screenshots: ['screenshots/journey-final.png'] }]));
  fs.writeFileSync(path.join(directory, 'consistency-report.json'), JSON.stringify({
    guidelines_version: 'test-version', degraded: false, checked_at: '2026-09-11T17:00:00Z',
    source_mode: { ran: true, violations: [] },
    visual_mode: { ran: true, screenshots_checked: 1, findings: [{ screenshot: 'screenshots/journey-final.png', seen_on: ['screenshots/journey-final.png'], guideline_id: 'button-label', guideline_title: 'Button label', category: 'content', severity: 'warning', verdict: 'FLAGGED', description: 'Review label', suggestion: 'Use a clear action label' }] },
    summary: { total_guidelines_checked: 3, violations: 0, warnings: 1, passes: 2 },
  }, null, 2));

  const result = spawnSync('node', [SCRIPT, directory, '--provider', 'openai', '--model', 'gpt-5.6-luna', '--json'], { encoding: 'utf8' });
  assert.strictEqual(result.status, 0, result.stdout + result.stderr);
  assert.strictEqual(validateDirectory(directory).valid, true);
  const evaluation = JSON.parse(fs.readFileSync(path.join(directory, 'evaluation.json')));
  assert.strictEqual(evaluation.ac_results[0].verdict, 'PASS');
  assert.strictEqual(evaluation.usability.score, 2.5);
  assert.strictEqual(evaluation.consistency.findings[0].origin, 'visual');
  assert.strictEqual(evaluation.consistency.findings[0].evidence_ids.length, 1);
  assert.strictEqual(JSON.parse(fs.readFileSync(path.join(directory, 'state.json'))).lifecycle.status, 'completed');
  assert.ok(fs.existsSync(path.join(root, 'PROJ-123', 'cache', 'full-v1')));

  const before = fs.readFileSync(path.join(directory, 'evaluation.json'), 'utf8');
  const report = JSON.parse(fs.readFileSync(path.join(directory, 'consistency-report.json')));
  report.visual_mode.findings[0].screenshot = 'screenshots/missing.png';
  report.visual_mode.findings[0].seen_on = ['screenshots/missing.png'];
  fs.writeFileSync(path.join(directory, 'consistency-report.json'), JSON.stringify(report));
  const failed = spawnSync('node', [SCRIPT, directory, '--provider', 'openai', '--model', 'gpt-5.6-luna', '--json'], { encoding: 'utf8' });
  assert.notStrictEqual(failed.status, 0);
  assert.strictEqual(fs.readFileSync(path.join(directory, 'evaluation.json'), 'utf8'), before);
} finally { fs.rmSync(root, { recursive: true, force: true }); }

console.log('PASS');
