#!/usr/bin/env node
'use strict';

/**
 * Append one cost-ledger row to .artifacts/<KEY>/eval/cost-ledger.jsonl
 *
 * Usage:
 *   node log-cost-ledger.js --artifacts-dir .artifacts/RHAISTRAT-1492/eval --payload-file row.json
 *   echo '{"eval_run_id":"..."}' | node log-cost-ledger.js --artifacts-dir .artifacts/RHAISTRAT-1492/eval
 */

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const { resolveProjectRoot } = require('./resolve-root');

function parseArgs(argv) {
  const out = { artifactsDir: null, payloadFile: null };
  for (let i = 2; i < argv.length; i++) {
    if (argv[i].startsWith('--artifacts-dir=')) {
      out.artifactsDir = argv[i].slice('--artifacts-dir='.length);
    } else if (argv[i] === '--artifacts-dir') {
      out.artifactsDir = argv[++i];
    } else if (argv[i].startsWith('--payload-file=')) {
      out.payloadFile = argv[i].slice('--payload-file='.length);
    } else if (argv[i] === '--payload-file') {
      out.payloadFile = argv[++i];
    }
  }
  return out;
}

function readJson(filePath) {
  return JSON.parse(fs.readFileSync(filePath, 'utf8'));
}

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = '';
    process.stdin.setEncoding('utf8');
    process.stdin.on('data', (chunk) => { data += chunk; });
    process.stdin.on('end', () => resolve(data));
    process.stdin.on('error', reject);
  });
}

function parseIterateFlags(flags) {
  const parts = (flags || '').split(/\s+/).filter(Boolean);
  return {
    run_mode: parts.includes('--fresh') ? 'fresh' : 'incremental',
    fix_mode: parts.includes('--no-fix') ? 'no_fix' : 'iterate',
    iterate_flags: (flags || '').trim(),
  };
}

function inferModelTier(model, invocation) {
  if (invocation === 'cursor' && model && /grok/i.test(model)) return 'cursor_grok';
  if (!model) return 'premium';
  const m = String(model).toLowerCase();
  if (m.includes('haiku')) return 'budget';
  if (m.includes('sonnet')) return 'standard';
  if (m.includes('opus')) return 'premium';
  return 'standard';
}

function hashUser(username) {
  if (!username) return 'anonymous';
  return crypto.createHash('sha256').update(username).digest('hex').slice(0, 16);
}

function readQualityFromArtifacts(artifactsDir) {
  const quality = {
    ac_pass: 0,
    ac_fail: 0,
    ac_flagged: 0,
    usability: null,
    golden_verdict: 'pending_human_review',
  };

  try {
    const csv = fs.readFileSync(path.join(artifactsDir, 'evaluation-report.csv'), 'utf8');
    for (const line of csv.trim().split('\n').slice(1)) {
      if (line.includes(',PASS,')) quality.ac_pass++;
      else if (line.includes(',FAIL,')) quality.ac_fail++;
      else if (line.includes(',FLAGGED,')) quality.ac_flagged++;
    }
  } catch { /* optional */ }

  try {
    const summary = readJson(path.join(artifactsDir, 'evaluation-summary.json'));
    if (summary.usability && typeof summary.usability.total_score === 'number') {
      quality.usability = summary.usability.total_score;
    }
  } catch { /* optional */ }

  return quality;
}

function appendIndex(projectRoot, row) {
  const indexPath = path.join(projectRoot, '.artifacts', 'eval', 'cost-ledger-index.jsonl');
  fs.mkdirSync(path.dirname(indexPath), { recursive: true });
  const indexRow = {
    date: row.date,
    eval_run_id: row.eval_run_id,
    prototype_key: row.prototype_key,
    experiment: row.experiment,
    llm_cost_usd: row.totals?.llm_cost_usd ?? 0,
    langfuse_trace_url: row.langfuse_trace_url || '',
    run_mode: row.run_mode,
    fix_mode: row.fix_mode,
  };
  fs.appendFileSync(indexPath, JSON.stringify(indexRow) + '\n');
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.artifactsDir) {
    console.error('Usage: node log-cost-ledger.js --artifacts-dir <dir> [--payload-file row.json]');
    process.exit(1);
  }

  const artifactsDir = path.resolve(args.artifactsDir);
  const projectRoot = resolveProjectRoot();
  let payload;

  if (args.payloadFile) {
    payload = readJson(path.resolve(args.payloadFile));
  } else if (!process.stdin.isTTY) {
    const raw = await readStdin();
    payload = JSON.parse(raw);
  } else {
    console.error('Provide --payload-file or pipe JSON on stdin');
    process.exit(1);
  }

  const prototypeKey = payload.prototype_key
    || path.basename(path.dirname(artifactsDir));
  const iterateFlags = payload.iterate_flags || '';
  const dims = parseIterateFlags(iterateFlags);
  const invocation = payload.invocation || 'cli';
  const model = payload.model || null;

  const row = {
    date: payload.date || new Date().toISOString().slice(0, 10),
    eval_run_id: payload.eval_run_id,
    prototype_key: prototypeKey,
    experiment: payload.experiment || 'eval-run',
    hypothesis: payload.hypothesis || '',
    depth_tier: payload.depth_tier || 'standard',
    run_mode: payload.run_mode || dims.run_mode,
    fix_mode: payload.fix_mode || dims.fix_mode,
    model_tier: payload.model_tier || inferModelTier(model, invocation),
    model_overrides: payload.model_overrides || {},
    invocation,
    iterate_flags: dims.iterate_flags,
    phases: payload.phases || [],
    totals: {
      llm_cost_usd: payload.totals?.llm_cost_usd ?? payload.llm_cost_usd ?? 0,
      observability_cost_usd: payload.totals?.observability_cost_usd ?? 0,
      total_tokens: payload.totals?.total_tokens ?? 0,
    },
    quality: payload.quality || readQualityFromArtifacts(artifactsDir),
    langfuse_trace_url: payload.langfuse_trace_url || '',
    mlflow_run_id: payload.mlflow_run_id || '',
    privacy_mode: 'metadata_only',
    retention_days: 30,
    designer_id_hash: hashUser(payload.designer || process.env.USER || process.env.USERNAME),
    notes: payload.notes || '',
  };

  const ledgerPath = path.join(artifactsDir, 'cost-ledger.jsonl');
  fs.mkdirSync(artifactsDir, { recursive: true });
  fs.appendFileSync(ledgerPath, JSON.stringify(row) + '\n');
  appendIndex(projectRoot, row);

  console.log(JSON.stringify({ ledger_path: ledgerPath, eval_run_id: row.eval_run_id }));
}

main().catch((err) => {
  console.error(err.message);
  process.exit(1);
});
