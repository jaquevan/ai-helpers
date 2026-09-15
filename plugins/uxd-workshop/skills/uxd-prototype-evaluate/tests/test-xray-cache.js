#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const cache = require('../scripts/xray-cache');
const { validateDirectory } = require('../scripts/validate-canonical-artifacts');

const fixture = path.join(__dirname, 'fixtures', 'canonical', 'v1', 'valid');
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-xray-cache-'));
try {
  const cacheRoot = path.join(root, 'cache');
  const stored = cache.store(cacheRoot, fixture);
  assert.equal(stored.status, 'stored');
  const state = JSON.parse(fs.readFileSync(path.join(fixture, 'state.json'), 'utf8'));
  const identity = state.identity;
  const hit = cache.lookup(cacheRoot, identity);
  assert.equal(hit.decision, 'hit');
  assert.deepEqual(hit.invalidated_by, ['none']);

  const destination = path.join(root, 'restored');
  const restored = cache.restore(cacheRoot, identity, destination);
  assert.equal(restored.decision, 'hit');
  assert.deepEqual(new Set(restored.restored_artifacts), new Set(cache.CANONICAL_FILES));
  assert.deepEqual(validateDirectory(destination), { valid: true, errors: [] });
  assert.throws(() => cache.restore(cacheRoot, identity, destination), /not empty/);

  const changed = { ...identity, build_key: `sha256:${'f'.repeat(64)}` };
  delete changed.compound_key;
  const miss = cache.lookup(cacheRoot, changed, identity);
  assert.equal(miss.decision, 'miss');
  assert.deepEqual(miss.invalidated_by, ['build']);

  fs.appendFileSync(path.join(hit.directory, 'evaluation.json'), '\n');
  const invalid = cache.lookup(cacheRoot, identity);
  assert.equal(invalid.decision, 'invalid');
  assert.equal(invalid.reason, 'checksum_evaluation.json');

  console.log('PASS');
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
