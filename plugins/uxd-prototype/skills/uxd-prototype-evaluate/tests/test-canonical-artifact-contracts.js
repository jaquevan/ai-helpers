#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { validateDirectory } = require('../scripts/validate-canonical-artifacts');

const FIXTURE_ROOT = path.join(__dirname, 'fixtures', 'canonical', 'v1');
const VALID_DIR = path.join(FIXTURE_ROOT, 'valid');
const INVALID_CASES = JSON.parse(fs.readFileSync(path.join(FIXTURE_ROOT, 'invalid', 'cases.json'), 'utf8')).cases;
const ARTIFACT_FILES = ['brief.json', 'evaluation.json', 'evidence.json', 'actions.json', 'state.json'];

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function loadFixture() {
  return Object.fromEntries(ARTIFACT_FILES.map(filename => [
    filename,
    JSON.parse(fs.readFileSync(path.join(VALID_DIR, filename), 'utf8')),
  ]));
}

function withFixture(mutator) {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-canonical-contract-'));
  try {
    const documents = loadFixture();
    if (mutator) mutator(documents);
    for (const [filename, document] of Object.entries(documents)) {
      fs.writeFileSync(path.join(tempDir, filename), `${JSON.stringify(document, null, 2)}\n`);
    }
    return validateDirectory(tempDir);
  } finally {
    fs.rmSync(tempDir, { recursive: true, force: true });
  }
}

function assertInvalid(name, expectedCode, mutator) {
  const result = withFixture(mutator);
  assert.strictEqual(result.valid, false, `${name} unexpectedly passed`);
  assert(result.errors.some(error => error.code === expectedCode), `${name} expected ${expectedCode}, received ${JSON.stringify(result.errors)}`);
}

function main() {
  const valid = withFixture();
  assert.deepStrictEqual(valid, { valid: true, errors: [] }, JSON.stringify(valid.errors));

  const expected = new Map(INVALID_CASES.map(entry => [entry.name, entry.expected_code]));
  assertInvalid('unknown property', expected.get('unknown property'), documents => {
    documents['brief.json'].intent.unexpected = true;
  });
  assertInvalid('forbidden reasoning field', expected.get('forbidden reasoning field'), documents => {
    documents['evaluation.json'].ac_results[0].reasoning = 'verbose private trace';
  });
  assertInvalid('dangling evidence', expected.get('dangling evidence'), documents => {
    documents['evaluation.json'].ac_results[0].evidence_ids = ['evidence-missing'];
  });
  assertInvalid('dangling journey AC', 'dangling_reference', documents => {
    documents['evaluation.json'].journeys[0].ac_ids = ['ac-missing'];
  });
  assertInvalid('duplicate iteration', 'duplicate_iteration', documents => {
    documents['state.json'].lifecycle.iterations.push(clone(documents['state.json'].lifecycle.iterations[0]));
  });
  assertInvalid('incorrect derived count', expected.get('incorrect derived count'), documents => {
    documents['evaluation.json'].summary.ac_counts.total = 0;
  });
  assertInvalid('unsafe publish action', expected.get('unsafe publish action'), documents => {
    const action = documents['actions.json'].actions[0];
    action.kind = 'publish';
    action.status = 'applied';
  });
  assertInvalid('crop outside source bounds', expected.get('crop outside source bounds'), documents => {
    documents['evidence.json'].items[0].crop.x = 1300;
  });
  assertInvalid('crop output dimensions', 'crop_image_dimensions', documents => {
    documents['evidence.json'].items[0].image.width = 280;
  });
  assertInvalid('cache key mismatch', expected.get('cache key mismatch'), documents => {
    documents['state.json'].identity.compound_key = 'sha256:dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd';
    documents['state.json'].cache.entry_key = documents['state.json'].identity.compound_key;
  });
  assertInvalid('complete brief requires criteria', 'schema_minItems', documents => {
    documents['brief.json'].intent.acceptance_criteria = [];
  });

  const sourceOnly = withFixture(documents => {
    documents['evaluation.json'].journeys = [];
    documents['evaluation.json'].usability = { status: 'not-run', score: 0, max_score: 0, dimensions: [] };
    documents['evaluation.json'].consistency = {
      status: 'passed',
      guidelines_version: 'test',
      guidelines_checked: 1,
      screenshots_checked: 0,
      source_checked: true,
      visual_checked: false,
      findings: [],
    };
    documents['evaluation.json'].summary = {
      ac_counts: { pass: 0, fail: 0, flagged: 1, not_run: 0, total: 1 },
      consistency_counts: { error: 0, warning: 0, info: 0, total: 0 },
      journey_counts: { pass: 0, fail: 0, flagged: 0, not_run: 0, total: 0 },
    };
    documents['actions.json'].actions = [];
    documents['evidence.json'].captures = [];
    documents['evidence.json'].items = [];
    documents['evaluation.json'].ac_results[0].evidence_ids = [];
    documents['evaluation.json'].ac_results[0].action_ids = [];
    documents['evaluation.json'].ac_results[0].evaluated_by = 'source';
  });
  assert.deepStrictEqual(sourceOnly, { valid: true, errors: [] }, JSON.stringify(sourceOnly.errors));

  const consistencyStage = withFixture(documents => {
    documents['brief.json'].intent.stage = 'consistency-source';
    documents['brief.json'].intent.acceptance_criteria = [];
    documents['brief.json'].intent.tasks = [];
    documents['brief.json'].intent.personas = [];
    documents['evaluation.json'].status = 'passed';
    documents['evaluation.json'].ac_results = [];
    documents['evaluation.json'].journeys = [];
    documents['evaluation.json'].usability = { status: 'not-run', score: 0, max_score: 0, dimensions: [] };
    documents['evaluation.json'].consistency = {
      status: 'passed',
      guidelines_version: 'test',
      guidelines_checked: 1,
      screenshots_checked: 0,
      source_checked: true,
      visual_checked: false,
      findings: [],
    };
    documents['evaluation.json'].summary = {
      ac_counts: { pass: 0, fail: 0, flagged: 0, not_run: 0, total: 0 },
      consistency_counts: { error: 0, warning: 0, info: 0, total: 0 },
      journey_counts: { pass: 0, fail: 0, flagged: 0, not_run: 0, total: 0 },
    };
    documents['evidence.json'].captures = [];
    documents['evidence.json'].items = [];
    documents['actions.json'].actions = [];
    documents['state.json'].lifecycle.iteration = 0;
    documents['state.json'].lifecycle.iterations = [];
  });
  assert.deepStrictEqual(consistencyStage, { valid: true, errors: [] }, JSON.stringify(consistencyStage.errors));

  console.log('PASS');
}

main();
