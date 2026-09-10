#!/usr/bin/env node
/**
 * validate-classify.js
 *
 * Validates tier-overrides.json schema and cross-references against
 * extract-state.json AC list for the eval-classify subskill.
 *
 * Usage:
 *   node validate-classify.js <artifacts-dir> [--json]
 *
 * Exit codes:
 *   0 = all checks pass
 *   1 = one or more checks failed
 */

const { readFileSync, existsSync } = require('fs');
const { join, resolve } = require('path');
const { parseCSVLine } = require('./csv-utils');

const jsonMode = process.argv.includes('--json');
const artifactsDir = process.argv.filter(a => a !== '--json')[2];
if (!artifactsDir) {
  console.error('Usage: node validate-classify.js <artifacts-dir> [--json]');
  process.exit(1);
}

const abs = resolve(artifactsDir);
const results = [];

function log(...args) { if (!jsonMode) console.log(...args); }

function check(name, pass, msg) {
  results.push({ name, pass, msg });
  if (!jsonMode) {
    const prefix = pass ? 'PASS' : 'FAIL';
    console.log(`  [${prefix}] ${name}: ${msg}`);
  }
}

function readJson(filename) {
  const p = join(abs, filename);
  if (!existsSync(p)) return null;
  try { return JSON.parse(readFileSync(p, 'utf8')); } catch { return null; }
}

log('\ntier-overrides.json:');

const overrides = readJson('tier-overrides.json');
const extractState = readJson('extract-state.json');

if (!overrides) {
  check('tier-overrides exists', false, 'file not found or invalid JSON');
} else {
  check('tier-overrides exists', true, 'file found');

  const entries = overrides.overrides || overrides;
  const isArray = Array.isArray(entries);
  check('overrides is array', isArray, isArray ? `${entries.length} entries` : `got ${typeof entries}`);

  if (isArray && entries.length > 0) {
    const VALID_TIERS = new Set(['T1', 'T2', 'T3']);
    let allFieldsOk = true;
    let allTiersOk = true;
    const seenIds = new Set();
    let hasDupes = false;

    const getId = (e) => e.ac_id || e.criterion_id;
    const getReason = (e) => e.reasoning || e.reason;

    for (const entry of entries) {
      if (!getId(entry)) allFieldsOk = false;
      if (!('forced_tier' in entry)) allFieldsOk = false;
      if (!getReason(entry)) allFieldsOk = false;
      if (entry.forced_tier && !VALID_TIERS.has(entry.forced_tier)) allTiersOk = false;
      const id = getId(entry);
      if (id) {
        if (seenIds.has(id)) hasDupes = true;
        seenIds.add(id);
      }
    }

    check('override entries have required fields', allFieldsOk,
      allFieldsOk ? `all ${entries.length} have id, forced_tier, reasoning`
        : 'missing fields detected');

    check('forced_tier values valid', allTiersOk,
      allTiersOk ? 'all T1/T2/T3' : 'invalid tier value found');

    check('no duplicate ac_id entries', !hasDupes,
      hasDupes ? 'duplicate ac_id found' : `${seenIds.size} unique IDs`);

    if (extractState && extractState.ac_list) {
      const acIds = new Set(extractState.ac_list.map(ac => ac.id || ac.criterion_id));
      const orphans = entries.filter(e => {
        const id = getId(e);
        return id && !acIds.has(id);
      });
      check('overrides reference valid ACs', orphans.length === 0,
        orphans.length === 0
          ? `all ${entries.length} override ACs exist in ac_list`
          : `${orphans.length} orphan(s): ${orphans.map(o => getId(o)).join(', ')}`);

      check('override count within bounds', entries.length <= acIds.size,
        entries.length <= acIds.size
          ? `${entries.length} overrides for ${acIds.size} ACs`
          : `${entries.length} overrides exceeds ${acIds.size} total ACs`);
    } else {
      log('  [SKIP] extract-state.json not found — skipping cross-reference checks');
    }
  }
}

log('\nevaluation-report.csv:');
const reportPath = join(abs, 'evaluation-report.csv');
if (!existsSync(reportPath)) {
  log('  [SKIP] evaluation-report.csv not found — tier override validation only');
} else {
  const requiredHeaders = [
    'criterion_id', 'source', 'tier', 'criterion_text', 'verdict',
    'rationale', 'evidence', 'fix_action', 'fix_file', 'human_action',
  ];
  const lines = readFileSync(reportPath, 'utf8').split(/\r?\n/);
  const headerIndex = lines.findIndex(line => line.trim() === requiredHeaders.join(','));
  check('AC header present', headerIndex >= 0,
    headerIndex >= 0 ? 'all 10 required columns present' : 'missing exact acceptance-criteria header');

  if (headerIndex >= 0) {
    const rows = [];
    for (const line of lines.slice(headerIndex + 1)) {
      if (!line.trim() || line.startsWith('#')) break;
      rows.push(parseCSVLine(line));
    }
    check('one classification per AC', Boolean(extractState?.ac_list) && rows.length === extractState.ac_list.length,
      extractState?.ac_list
        ? `${rows.length} rows for ${extractState.ac_list.length} ACs`
        : 'extract-state.json missing or invalid');

    const widthOk = rows.every(row => row.length === requiredHeaders.length);
    check('classification rows have 10 columns', widthOk,
      widthOk ? `${rows.length} rows are schema-aligned` : 'one or more rows have the wrong column count');

    const records = rows.filter(row => row.length === requiredHeaders.length).map(row =>
      Object.fromEntries(requiredHeaders.map((header, index) => [header, row[index]]))
    );
    const validTiers = new Set(['T1', 'T2', 'T3', 'T4']);
    const tiersOk = records.every(record => validTiers.has(record.tier));
    check('all criteria use T1-T4', tiersOk,
      tiersOk ? 'all tier values valid' : 'invalid or missing tier value found');

    const ids = records.map(record => record.criterion_id);
    const uniqueIds = new Set(ids);
    check('criterion IDs are unique', uniqueIds.size === ids.length,
      `${uniqueIds.size} unique IDs across ${ids.length} rows`);

    if (extractState?.ac_list) {
      const expectedIds = extractState.ac_list.map((ac, index) =>
        ac.criterion_id || ac.id || `AC-${index + 1}`
      );
      const idsMatch = expectedIds.length === ids.length && expectedIds.every(id => uniqueIds.has(id));
      check('criterion IDs match extract-state', idsMatch,
        idsMatch ? 'all extracted criteria classified' : 'CSV criteria differ from extract-state.json');
    }

    const t3Ok = records
      .filter(record => record.tier === 'T3')
      .every(record => record.verdict === 'PASS' && record.rationale.includes('Backend-only'));
    check('T3 criteria auto-pass with rationale', t3Ok,
      t3Ok ? 'all backend-only criteria are noted' : 'T3 rows require PASS and backend-only rationale');

    const t4Ok = records
      .filter(record => record.tier === 'T4')
      .every(record => Boolean(record.human_action));
    check('T4 criteria include human action', t4Ok,
      t4Ok ? 'all subjective criteria have review instructions' : 'T4 row missing human_action');
  }
}

const passCount = results.filter(r => r.pass).length;
const failCount = results.filter(r => !r.pass).length;

if (jsonMode) {
  console.log(JSON.stringify({
    results: results.map(r => ({ scorer: r.name, pass: r.pass, detail: r.msg })),
    pass_count: passCount,
    fail_count: failCount,
    all_pass: failCount === 0,
  }, null, 2));
} else {
  log(`\n${'─'.repeat(50)}`);
  log(`Classify validation: ${passCount} passed, ${failCount} failed`);
  if (failCount > 0) {
    log('\nFailing checks:');
    for (const r of results.filter(r => !r.pass)) {
      log(`  - ${r.name}: ${r.msg}`);
    }
  }
}

if (failCount > 0) process.exit(1);
