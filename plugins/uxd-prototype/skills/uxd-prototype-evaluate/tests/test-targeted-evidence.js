#!/usr/bin/env node
'use strict';

const assert = require('assert');
const os = require('os');
const path = require('path');

const { clipForBox, resolvePortable } = require('../scripts/targeted-evidence');

const viewport = { width: 1440, height: 900 };

assert.deepStrictEqual(
  clipForBox({ x: 100, y: 200, width: 280, height: 96 }, viewport, 16),
  {
    crop: { x: 100, y: 200, width: 280, height: 96, padding: 16 },
    clip: { x: 84, y: 184, width: 312, height: 128 },
  },
);

assert.deepStrictEqual(
  clipForBox({ x: 0, y: 0, width: 100, height: 40 }, viewport, 16),
  {
    crop: { x: 0, y: 0, width: 100, height: 40, padding: 16 },
    clip: { x: 0, y: 0, width: 116, height: 56 },
  },
);

assert.deepStrictEqual(
  clipForBox({ x: 1400, y: 880, width: 40, height: 20 }, viewport, 16).clip,
  { x: 1384, y: 864, width: 56, height: 36 },
);

const root = path.join(os.tmpdir(), 'uxd-targeted-evidence');
assert.equal(resolvePortable(root, 'evidence/crops/save.png'), path.join(root, 'evidence', 'crops', 'save.png'));
assert.throws(() => resolvePortable(root, '../escape.png'), /relative and portable/);
assert.throws(() => resolvePortable(root, '/tmp/escape.png'), /relative and portable/);

console.log('PASS');
