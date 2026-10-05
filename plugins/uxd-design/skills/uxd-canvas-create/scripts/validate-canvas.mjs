#!/usr/bin/env node

import fs from 'node:fs';
import path from 'node:path';

const args = process.argv.slice(2);
const strict = args.includes('--strict');
const input = args.find((arg) => !arg.startsWith('--'));

if (!input) {
  console.error('Usage: validate-canvas.mjs <canvas.json> [--strict]');
  process.exit(2);
}

const errors = [];
const warnings = [];
const allowedTypes = new Set(['text', 'file', 'link', 'group', 'jira', 'task']);
const allowedSides = new Set(['top', 'right', 'bottom', 'left']);
const allowedLineStyles = new Set(['solid', 'dashed', 'dotted']);
const allowedEnds = new Set(['none', 'arrow', 'diamond', 'circle']);

let canvas;
try {
  canvas = JSON.parse(fs.readFileSync(path.resolve(input), 'utf8'));
} catch (error) {
  console.error(`ERROR: Could not read valid JSON from ${input}: ${error.message}`);
  process.exit(1);
}

if (!canvas || typeof canvas !== 'object' || Array.isArray(canvas)) {
  errors.push('Root must be an object.');
}
if (!Array.isArray(canvas.nodes)) errors.push('Root field "nodes" must be an array.');
if (!Array.isArray(canvas.edges)) errors.push('Root field "edges" must be an array.');

const nodes = Array.isArray(canvas.nodes) ? canvas.nodes : [];
const edges = Array.isArray(canvas.edges) ? canvas.edges : [];
const nodeIds = new Set();
const edgeIds = new Set();
const miroIds = new Set();

function finiteNumber(value) {
  return typeof value === 'number' && Number.isFinite(value);
}

function recordMiroId(miroId, label) {
  if (typeof miroId !== 'string' || !miroId.trim()) {
    errors.push(`${label} miroId must be a non-empty string.`);
    return;
  }
  if (miroIds.has(miroId)) warnings.push(`${label} reuses miroId "${miroId}".`);
  else miroIds.add(miroId);
}

function addUniqueId(item, ids, kind, index) {
  if (typeof item.id !== 'string' || !item.id.trim()) {
    errors.push(`${kind}[${index}] requires a non-empty string id.`);
  } else if (ids.has(item.id)) {
    errors.push(`Duplicate ${kind.toLowerCase()} id "${item.id}".`);
  } else {
    ids.add(item.id);
  }
}

nodes.forEach((node, index) => {
  if (!node || typeof node !== 'object' || Array.isArray(node)) {
    errors.push(`Node[${index}] must be an object.`);
    return;
  }
  addUniqueId(node, nodeIds, 'Node', index);
  if (!allowedTypes.has(node.type)) warnings.push(`Node "${node.id || index}" uses non-portable type "${node.type}".`);
  for (const field of ['x', 'y', 'width', 'height']) {
    if (!finiteNumber(node[field])) errors.push(`Node "${node.id || index}" requires numeric ${field}.`);
  }
  if (finiteNumber(node.width) && node.width <= 0) errors.push(`Node "${node.id || index}" width must be positive.`);
  if (finiteNumber(node.height) && node.height <= 0) errors.push(`Node "${node.id || index}" height must be positive.`);
  if (node.type === 'text' && node.subtype !== 'drawing' && typeof node.text !== 'string') errors.push(`Text node "${node.id || index}" requires text.`);
  if (node.miroId !== undefined) recordMiroId(node.miroId, `Node "${node.id || index}"`);
  if (node.type === 'file' && typeof node.file !== 'string') errors.push(`File node "${node.id || index}" requires file.`);
  if (node.type === 'link' && typeof node.url !== 'string') errors.push(`Link node "${node.id || index}" requires url.`);
  if (node.colorOpacity !== undefined && (!finiteNumber(node.colorOpacity) || node.colorOpacity < 0 || node.colorOpacity > 100)) {
    errors.push(`Node "${node.id || index}" colorOpacity must be between 0 and 100.`);
  }

  if (typeof node.text === 'string' && finiteNumber(node.width) && finiteNumber(node.height)) {
    const plainText = node.text.replace(/[#*_`>[\]()!-]/g, '').trim();
    const charactersPerLine = Math.max(12, Math.floor((node.width - 24) / 7));
    const visibleLines = Math.max(1, Math.floor((node.height - 24) / 21));
    const capacity = charactersPerLine * visibleLines;
    if (plainText.length > capacity * 1.15) {
      warnings.push(`Node "${node.id || index}" may scroll: ${plainText.length} characters for roughly ${capacity} visible characters.`);
    }
  }
});

edges.forEach((edge, index) => {
  if (!edge || typeof edge !== 'object' || Array.isArray(edge)) {
    errors.push(`Edge[${index}] must be an object.`);
    return;
  }
  addUniqueId(edge, edgeIds, 'Edge', index);
  for (const field of ['fromNode', 'toNode']) {
    if (typeof edge[field] !== 'string' || !edge[field]) errors.push(`Edge "${edge.id || index}" requires ${field}.`);
    else if (!nodeIds.has(edge[field])) errors.push(`Edge "${edge.id || index}" references missing node "${edge[field]}".`);
  }
  for (const field of ['fromSide', 'toSide']) {
    if (edge[field] !== undefined && !allowedSides.has(edge[field])) errors.push(`Edge "${edge.id || index}" has invalid ${field} "${edge[field]}".`);
  }
  if (edge.lineStyle !== undefined && !allowedLineStyles.has(edge.lineStyle)) errors.push(`Edge "${edge.id || index}" has invalid lineStyle "${edge.lineStyle}".`);
  for (const field of ['fromEnd', 'toEnd']) {
    if (edge[field] !== undefined && !allowedEnds.has(edge[field])) errors.push(`Edge "${edge.id || index}" has invalid ${field} "${edge[field]}".`);
  }
  if (edge.miroId !== undefined) recordMiroId(edge.miroId, `Edge "${edge.id || index}"`);
});

const ordinaryNodes = nodes.filter((node) => node && node.type !== 'group' && [node.x, node.y, node.width, node.height].every(finiteNumber));
for (let i = 0; i < ordinaryNodes.length; i += 1) {
  for (let j = i + 1; j < ordinaryNodes.length; j += 1) {
    const a = ordinaryNodes[i];
    const b = ordinaryNodes[j];
    const overlapX = Math.min(a.x + a.width, b.x + b.width) - Math.max(a.x, b.x);
    const overlapY = Math.min(a.y + a.height, b.y + b.height) - Math.max(a.y, b.y);
    if (overlapX > 8 && overlapY > 8) warnings.push(`Nodes "${a.id}" and "${b.id}" overlap by ${Math.round(overlapX)}×${Math.round(overlapY)}.`);
  }
}

errors.forEach((message) => console.error(`ERROR: ${message}`));
warnings.forEach((message) => console.warn(`WARN: ${message}`));
console.log(`${nodes.length} nodes, ${edges.length} edges, ${errors.length} errors, ${warnings.length} warnings`);

process.exit(errors.length || (strict && warnings.length) ? 1 : 0);
