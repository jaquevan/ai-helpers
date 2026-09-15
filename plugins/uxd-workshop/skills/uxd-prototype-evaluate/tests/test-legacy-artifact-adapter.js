#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const { spawnSync } = require('child_process');
const { parseCSVLine } = require('../scripts/csv-utils');
const { validateDirectory } = require('../scripts/validate-canonical-artifacts');

const SKILL_DIR = path.resolve(__dirname, '..');
const VALID_DIR = path.join(__dirname, 'fixtures', 'canonical', 'v1', 'valid');
const CANONICAL_FILES = ['brief.json', 'evaluation.json', 'evidence.json', 'actions.json', 'state.json'];
const ADAPTER = path.join(SKILL_DIR, 'scripts', 'materialize-legacy-eval-artifacts.js');

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function writeDocuments(directory, documents) {
  fs.mkdirSync(directory, { recursive: true });
  for (const [filename, document] of Object.entries(documents)) {
    fs.writeFileSync(path.join(directory, filename), `${JSON.stringify(document, null, 2)}\n`);
  }
}

function loadDocuments() {
  return Object.fromEntries(CANONICAL_FILES.map(filename => [filename, readJson(path.join(VALID_DIR, filename))]));
}

function action(id, kind, acId, recommendation, target) {
  return {
    id,
    kind,
    status: 'proposed',
    priority: kind === 'fix' ? 'blocking' : 'normal',
    confidence: kind === 'fix' ? 'high' : 'low',
    source: { ac_id: acId, finding_id: null, evidence_ids: [] },
    ...(target ? { target: { file: target, line: 12 } } : {}),
    recommendation,
    result: { changed_files: [] },
    handoff: {
      requires_user_invocation: kind === 'human-followup',
      skill: '',
      payload: {},
    },
  };
}

function buildAdapterFixture() {
  const documents = loadDocuments();
  const brief = documents['brief.json'];
  const evaluation = documents['evaluation.json'];
  const actions = documents['actions.json'];
  const state = documents['state.json'];
  const baseCriterion = brief.intent.acceptance_criteria[0];

  brief.intent.acceptance_criteria = [
    { ...clone(baseCriterion), id: 'ac-one', source_id: 'AC-1', source: 'jira', text: 'The table displays a status, including "Queued".' },
    { ...clone(baseCriterion), id: 'ac-two', source_id: 'AC-2', source: 'derived', text: 'The disabled state is visible.', requires_human_followup: false },
    { ...clone(baseCriterion), id: 'ac-three', source_id: 'AC-3', source: 'user', text: 'The control placement follows the approved design.', tier: 'T2' },
    { ...clone(baseCriterion), id: 'ac-four', source_id: 'AC-4', source: 'jira', text: 'Research approval is documented.', verification_mode: 'design-process', tier: 'T4', requires_human_followup: true },
  ];
  brief.intent.tasks[0].ac_ids = ['ac-one', 'ac-two', 'ac-three', 'ac-four'];

  actions.actions = [
    action('action-fix-two', 'fix', 'ac-two', 'Add a visible disabled state.', 'src/Experiment.tsx'),
    action('action-human-three', 'human-followup', 'ac-three', 'Confirm the control placement with the designer.'),
    action('action-human-four', 'human-followup', 'ac-four', 'Confirm the design-process deliverable outside the prototype: research approval.'),
  ];

  const baseResult = evaluation.ac_results[0];
  evaluation.ac_results = [
    { ...clone(baseResult), ac_id: 'ac-one', verdict: 'PASS', rationale: 'The status is visible.', action_ids: [] },
    { ...clone(baseResult), ac_id: 'ac-two', verdict: 'FAIL', rationale: 'The disabled state is missing.', action_ids: ['action-fix-two'] },
    { ...clone(baseResult), ac_id: 'ac-three', verdict: 'FLAGGED', rationale: 'Placement needs design review.', evidence_ids: [], action_ids: ['action-human-three'], evaluated_by: 'human' },
    { ...clone(baseResult), ac_id: 'ac-four', verdict: 'FLAGGED', rationale: 'External evidence is required.', evidence_ids: [], action_ids: ['action-human-four'], evaluated_by: 'human' },
  ];
  evaluation.journeys[0].ac_ids = ['ac-two'];
  evaluation.journeys[0].verdict = 'FAIL';
  evaluation.summary.ac_counts = { pass: 1, fail: 1, flagged: 2, not_run: 0, total: 4 };
  evaluation.summary.journey_counts = { pass: 0, fail: 1, flagged: 0, not_run: 0, total: 1 };
  evaluation.status = 'needs-attention';

  const finding = evaluation.consistency.findings[0];
  Object.assign(finding, {
    origin: 'source',
    file: 'src/Experiment.tsx',
    line: 42,
    evidence_ids: [],
    check_method: 'automated',
  });
  evaluation.consistency.source_checked = true;
  evaluation.consistency.visual_checked = false;
  evaluation.consistency.screenshots_checked = 0;

  state.lifecycle.iterations[0].ac_results = evaluation.ac_results.map(result => ({ ac_id: result.ac_id, verdict: result.verdict }));
  return documents;
}

function run(command, args, options = {}) {
  return spawnSync(command, args, { encoding: 'utf8', ...options });
}

function runAdapter(canonicalDir, outputDir, extra = []) {
  return run(process.execPath, [
    ADAPTER,
    '--canonical-dir', canonicalDir,
    '--output-dir', outputDir,
    '--targets', 'csv,summary,consistency,extract,evidence,journey,actions,state',
    '--json',
    ...extra,
  ]);
}

function acceptanceRows(csv) {
  const lines = csv.split(/\r?\n/);
  const headerIndex = lines.indexOf('criterion_id,source,tier,criterion_text,verdict,rationale,evidence,fix_action,fix_file,human_action');
  const headers = parseCSVLine(lines[headerIndex]);
  const rows = [];
  for (const line of lines.slice(headerIndex + 1)) {
    if (!line || line.startsWith('#')) break;
    const values = parseCSVLine(line);
    rows.push(Object.fromEntries(headers.map((header, index) => [header, values[index]])));
  }
  return rows;
}

function main() {
  const tempRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-legacy-adapter-'));
  try {
    const canonicalDir = path.join(tempRoot, 'canonical');
    const outputDir = path.join(tempRoot, 'compatibility-shadow');
    const documents = buildAdapterFixture();
    writeDocuments(canonicalDir, documents);
    assert.deepStrictEqual(validateDirectory(canonicalDir), { valid: true, errors: [] });

    const first = runAdapter(canonicalDir, outputDir);
    assert.strictEqual(first.status, 0, first.stderr || first.stdout);
    const metrics = JSON.parse(first.stdout);
    assert.strictEqual(metrics.semantic_parity, true);
    assert.strictEqual(metrics.model_invoked, false);
    assert.strictEqual(metrics.external_side_effects, false);
    assert.strictEqual(metrics.files.length, 10);
    assert.strictEqual(fs.existsSync(path.join(outputDir, 'persona-results.json')), false);

    const csv = fs.readFileSync(path.join(outputDir, 'evaluation-report.csv'), 'utf8');
    const rows = acceptanceRows(csv);
    assert.strictEqual(rows.length, 4);
    assert.strictEqual(rows[0].criterion_text, 'The table displays a status, including "Queued".');
    assert.strictEqual(rows[1].source, 'inferred');
    assert.strictEqual(rows[1].verdict, 'FAIL');
    assert.strictEqual(rows[1].fix_file, 'src/Experiment.tsx');
    assert.match(rows[3].human_action, /^Confirm the design-process deliverable outside the prototype:/);
    assert.strictEqual(csv.includes(',FAIL,'), true, 'legacy publish FAIL gate must still block');

    fs.writeFileSync(path.join(outputDir, 'tier-overrides.json'), '[]\n');
    const classify = run(process.execPath, [path.join(SKILL_DIR, 'scripts', 'validate-classify.js'), outputDir, '--json']);
    assert.strictEqual(classify.status, 0, classify.stdout || classify.stderr);
    fs.unlinkSync(path.join(outputDir, 'tier-overrides.json'));
    const consistency = run(process.execPath, [path.join(SKILL_DIR, 'scripts', 'validate-consistency.js'), outputDir, '--json']);
    assert.strictEqual(consistency.status, 0, consistency.stdout || consistency.stderr);
    const verdicts = run(process.execPath, [path.join(SKILL_DIR, 'scripts', 'validate-verdicts.js'), outputDir]);
    assert.strictEqual(verdicts.status, 0, verdicts.stdout || verdicts.stderr);

    const collision = runAdapter(canonicalDir, outputDir);
    assert.strictEqual(collision.status, 1);
    assert.strictEqual(JSON.parse(collision.stdout).code, 'output_collision');
    const replaced = runAdapter(canonicalDir, outputDir, ['--replace']);
    assert.strictEqual(replaced.status, 0, replaced.stderr || replaced.stdout);

    fs.writeFileSync(path.join(outputDir, 'do-not-touch.txt'), 'owner data\n');
    const unsafeReplace = runAdapter(canonicalDir, outputDir, ['--replace']);
    assert.strictEqual(unsafeReplace.status, 1);
    assert.strictEqual(JSON.parse(unsafeReplace.stdout).code, 'unsafe_replace');
    assert.strictEqual(fs.readFileSync(path.join(outputDir, 'do-not-touch.txt'), 'utf8'), 'owner data\n');
    fs.unlinkSync(path.join(outputDir, 'do-not-touch.txt'));

    const expectedCounts = clone(readJson(path.join(outputDir, 'evaluation-summary.json')).counts);
    const render = run(process.execPath, [path.join(SKILL_DIR, 'scripts', 'render-report.js'), outputDir]);
    assert.strictEqual(render.status, 0, render.stdout || render.stderr);
    assert.deepStrictEqual(readJson(path.join(outputDir, 'evaluation-summary.json')).counts, {
      ...expectedCounts,
      prototype_testable: 3,
      external_evidence_required: 1,
    });
    assert.strictEqual(fs.existsSync(path.join(outputDir, 'evaluation-report.html')), true);

    const keyRoot = path.join(tempRoot, 'PROJ-123');
    const evalDir = path.join(keyRoot, 'eval');
    fs.mkdirSync(evalDir, { recursive: true });
    fs.copyFileSync(path.join(outputDir, 'evaluation-report.html'), path.join(evalDir, 'evaluation-report.html'));
    fs.copyFileSync(path.join(outputDir, 'evaluation-report.csv'), path.join(evalDir, 'evaluation-report.csv'));
    const pagesRoot = path.join(tempRoot, 'public');
    const copyScript = path.resolve(SKILL_DIR, '..', 'uxd-prototype-export', 'scripts', 'copy-eval-for-pages.sh');
    const copied = run('bash', [copyScript, '--artifacts', keyRoot, '--pages-root', pagesRoot]);
    assert.strictEqual(copied.status, 0, copied.stdout || copied.stderr);
    assert.strictEqual(fs.existsSync(path.join(pagesRoot, 'evals', 'PROJ-123', 'index.html')), true);

    const exportSmoke = run(process.execPath, [path.resolve(SKILL_DIR, '..', 'uxd-prototype-export', 'scripts', 'export-pf-spec.js')]);
    assert.strictEqual(exportSmoke.status, 0, exportSmoke.stdout || exportSmoke.stderr);

    const invalidDir = path.join(tempRoot, 'invalid-canonical');
    const invalidDocuments = buildAdapterFixture();
    delete invalidDocuments['brief.json'].intent.acceptance_criteria[0].source;
    writeDocuments(invalidDir, invalidDocuments);
    const invalidOutput = path.join(tempRoot, 'invalid-output');
    const invalid = runAdapter(invalidDir, invalidOutput);
    assert.strictEqual(invalid.status, 1);
    assert.strictEqual(JSON.parse(invalid.stdout).code, 'invalid_canonical_input');
    assert.strictEqual(fs.existsSync(invalidOutput), false);

    const live = runAdapter(canonicalDir, path.join(tempRoot, 'eval'));
    assert.strictEqual(live.status, 1);
    assert.strictEqual(JSON.parse(live.stdout).code, 'live_output_forbidden');

    console.log('PASS');
  } finally {
    fs.rmSync(tempRoot, { recursive: true, force: true });
  }
}

main();
