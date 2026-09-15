#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');

const { loadReportInputs } = require('../scripts/report-inputs');

const SKILL_DIR = path.resolve(__dirname, '..');
const FIXTURE = path.join(__dirname, 'fixtures', 'canonical', 'v1', 'valid');
const RENDERER = path.join(SKILL_DIR, 'scripts', 'render-report.js');
const PNG = Buffer.from('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000d49444154789c6360f8cff00000040101005fe5c4b90000000049454e44ae426082', 'hex');

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-canonical-report-'));
try {
  const evalDir = path.join(root, 'PROJ-123', 'eval');
  fs.mkdirSync(evalDir, { recursive: true });
  for (const filename of ['brief.json', 'evaluation.json', 'evidence.json', 'actions.json', 'state.json']) {
    fs.copyFileSync(path.join(FIXTURE, filename), path.join(evalDir, filename));
  }
  for (const relative of ['screenshots/capture-1.png', 'evidence/crops/evidence-1.png']) {
    const target = path.join(evalDir, relative);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, PNG);
  }

  const staleCsv = '# ACCEPTANCE CRITERIA\ncriterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action\nAC-OLD,jira,T1,Stale legacy result,FAIL,,,,,\n';
  const staleJourney = '{"marker":"must-not-change"}\n';
  fs.writeFileSync(path.join(evalDir, 'evaluation-report.csv'), staleCsv);
  fs.writeFileSync(path.join(evalDir, 'journey-log.json'), staleJourney);

  const inputs = loadReportInputs(evalDir);
  assert.equal(inputs.mode, 'canonical-v1');
  assert(inputs.imagePaths.includes('evidence/crops/evidence-1.png'));

  const rendered = spawnSync(process.execPath, [RENDERER, evalDir], { encoding: 'utf8', cwd: SKILL_DIR });
  assert.equal(rendered.status, 0, `${rendered.stdout}\n${rendered.stderr}`);
  const html = fs.readFileSync(path.join(evalDir, 'evaluation-report.html'), 'utf8');
  const summary = JSON.parse(fs.readFileSync(path.join(evalDir, 'evaluation-summary.json'), 'utf8'));
  const metrics = JSON.parse(fs.readFileSync(path.join(evalDir, 'render-metrics.json'), 'utf8'));
  assert(html.includes('PatternFly Consistency'));
  assert(html.includes('No Custom CSS'));
  assert(html.includes('Use a PatternFly Button and design tokens.'));
  assert(html.includes('data:image/png;base64,'));
  assert.equal(summary.counts.total, 1);
  assert.equal(summary.counts.flagged, 1);
  assert.equal(summary.counts.fail, 0);
  assert.equal(metrics.input_mode, 'canonical-v1');
  assert.equal(fs.readFileSync(path.join(evalDir, 'evaluation-report.csv'), 'utf8'), staleCsv);
  assert.equal(fs.readFileSync(path.join(evalDir, 'journey-log.json'), 'utf8'), staleJourney);
  assert(!fs.existsSync(path.join(evalDir, 'extract-state.json')));

  const partial = path.join(root, 'partial');
  fs.mkdirSync(partial);
  fs.copyFileSync(path.join(FIXTURE, 'brief.json'), path.join(partial, 'brief.json'));
  assert.throws(() => loadReportInputs(partial), error => error.code === 'partial_canonical_input');

  console.log('PASS');
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
