#!/usr/bin/env node
'use strict';

/** Merge bounded provider outputs into the canonical five-file evaluation set. */

const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { parseAcceptanceRows } = require('./assemble-phase-a-canonical');
const { validateDirectory } = require('./validate-canonical-artifacts');
const { store } = require('./xray-cache');

const FILES = ['brief.json', 'evaluation.json', 'evidence.json', 'actions.json', 'state.json'];
const PORTABLE_PATH = /^(?!\/)(?![A-Za-z]:[\\/])(?!.*(?:^|\/)\.\.(?:\/|$))[A-Za-z0-9._+@=-]+(?:\/[A-Za-z0-9._+@=-]+)*$/;

function readJson(file) { return JSON.parse(fs.readFileSync(file, 'utf8')); }
function sha256(value) { return `sha256:${crypto.createHash('sha256').update(value).digest('hex')}`; }
function bounded(value, max, fallback) { return (String(value || '').trim() || fallback).slice(0, max); }
function identifier(value, prefix) {
  let slug = String(value || '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
  if (!slug.includes('-')) slug = `${prefix}-${slug || sha256(String(value)).slice(7, 15)}`;
  if (!/^[a-z]/.test(slug)) slug = `${prefix}-${slug}`;
  return slug.slice(0, 160).replace(/-+$/, '');
}
function portable(value) { const item = String(value || '').replace(/^\.\//, '').replace(/\\/g, '/'); return PORTABLE_PATH.test(item) ? item : ''; }
function timestamp(value) { const date = new Date(value || Date.now()); return Number.isNaN(date.getTime()) ? new Date().toISOString() : date.toISOString(); }

function imageDimensions(buffer, fallback) {
  if (buffer.length >= 24 && buffer.toString('ascii', 1, 4) === 'PNG') return { width: buffer.readUInt32BE(16), height: buffer.readUInt32BE(20) };
  return fallback;
}

function verdictCounts(records) {
  const result = { pass: 0, fail: 0, flagged: 0, not_run: 0, total: records.length };
  records.forEach(record => { const key = String(record.verdict).toLowerCase(); if (key in result) result[key] += 1; });
  return result;
}

function modelPhase(name, provider, model, at, status = 'completed') {
  return {
    name, status, model_invoked: status === 'completed', provider: status === 'completed' ? provider : 'none', model: status === 'completed' ? model : '',
    started_at: at, ended_at: at, duration_ms: 0, input_files: 0, input_bytes: 0, output_bytes: 0,
    token_usage: { input: 0, cached_input: 0, output: 0, reasoning_tokens: 0 }, llm_cost_usd: 0,
  };
}

function loadDocuments(directory) { return Object.fromEntries(FILES.map(name => [name, readJson(path.join(directory, name))])); }
function writeDocuments(directory, documents) {
  fs.mkdirSync(directory, { recursive: true });
  FILES.forEach(name => fs.writeFileSync(path.join(directory, name), `${JSON.stringify(documents[name], null, 2)}\n`));
}

function sync(directory, { provider, model }) {
  const documents = loadDocuments(directory);
  const brief = documents['brief.json'];
  const evaluation = documents['evaluation.json'];
  const evidence = documents['evidence.json'];
  const actions = documents['actions.json'];
  const state = documents['state.json'];
  const journey = readJson(path.join(directory, 'journey-log.json'));
  const resultBySource = new Map((journey.criterion_results || []).map(result => [result.criterion_id, result]));
  const csvPath = path.join(directory, 'evaluation-report.csv');
  const rows = fs.existsSync(csvPath)
    ? parseAcceptanceRows(csvPath)
    : brief.intent.acceptance_criteria.map(ac => {
      const existing = evaluation.ac_results.find(result => result.ac_id === ac.id);
      const update = resultBySource.get(ac.source_id) || {};
      return {
        criterion_id: ac.source_id, source: ac.source, tier: ac.tier, criterion_text: ac.text,
        verdict: update.verdict || (existing.verdict === 'NOT_RUN' ? '' : existing.verdict),
        rationale: update.rationale || existing.rationale,
        evidence: update.evidence || '', fix_action: update.fix_action || '', fix_file: update.fix_file || '',
        human_action: update.human_action || '',
      };
    });
  const consistency = readJson(path.join(directory, 'consistency-report.json'));
  const personaResults = fs.existsSync(path.join(directory, 'persona-results.json')) ? readJson(path.join(directory, 'persona-results.json')) : [];
  const acBySource = new Map(brief.intent.acceptance_criteria.map(ac => [ac.source_id, ac]));
  const taskByAc = new Map();
  brief.intent.tasks.forEach(task => task.ac_ids.forEach(acId => { if (!taskByAc.has(acId)) taskByAc.set(acId, task); }));
  const personaByLegacy = new Map();
  brief.intent.personas.forEach(persona => {
    personaByLegacy.set(persona.id, persona);
    personaByLegacy.set(persona.id.replace(/^persona-/, '').replace(/-(junior|senior|mixed)$/, '+$1'), persona);
    personaByLegacy.set(persona.id.replace(/^persona-/, '').replace(/-(junior|senior|mixed)$/, ''), persona);
  });
  const fallbackCapture = evidence.captures[0];
  if (!fallbackCapture) throw new Error('Canonical evidence has no baseline capture');
  const evidenceByPath = new Map(evidence.items.filter(item => item.image?.path).map(item => [item.image.path, item]));
  const routes = readJson(path.resolve(__dirname, '..', 'config', 'phase-routing.json'));
  const phaseModel = name => model === 'phase-routed'
    ? routes.phases[`eval-${name}`]?.models?.[provider] || model
    : model;

  function ensureEvidence(rawPath, purpose) {
    const relative = portable(rawPath);
    if (!relative) return null;
    if (evidenceByPath.has(relative)) return evidenceByPath.get(relative).id;
    const absolute = path.resolve(directory, relative);
    if (absolute !== directory && !absolute.startsWith(`${directory}${path.sep}`)) return null;
    let image;
    if (fs.existsSync(absolute)) {
      const buffer = fs.readFileSync(absolute);
      const dimensions = imageDimensions(buffer, fallbackCapture.viewport);
      image = { path: relative, ...dimensions, sha256: sha256(buffer) };
    } else if (fallbackCapture.raw_image?.path === relative) {
      image = fallbackCapture.raw_image;
    } else {
      return null;
    }
    const id = identifier(`evidence-${purpose}-${sha256(relative).slice(7, 23)}`, 'evidence');
    const item = { id, capture_id: fallbackCapture.id, kind: 'full-page', purpose, subject: { role: 'region', name: bounded(relative, 280, 'Rendered evidence'), locator: 'body' }, image };
    evidence.items.push(item); evidenceByPath.set(relative, item); return id;
  }

  const actionByKey = new Map(actions.actions.map(action => [`${action.kind}|${action.source.ac_id || ''}|${action.source.finding_id || ''}`, action]));
  const resultByAc = new Map(evaluation.ac_results.map(result => [result.ac_id, result]));
  for (const row of rows) {
    const ac = acBySource.get(row.criterion_id);
    if (!ac) throw new Error(`Unknown classified AC: ${row.criterion_id}`);
    const result = resultByAc.get(ac.id);
    result.verdict = ['PASS', 'FAIL', 'FLAGGED'].includes(row.verdict) ? row.verdict : 'NOT_RUN';
    result.rationale = bounded(row.rationale, 280, result.verdict === 'NOT_RUN' ? 'Pending evaluation.' : 'Evaluation result.');
    const evidenceId = ensureEvidence(row.evidence, 'ac');
    result.evidence_ids = evidenceId ? [evidenceId] : [];
    for (const [kind, recommendation] of [['fix', row.fix_action], ['human-followup', row.human_action]]) {
      if (!recommendation) continue;
      const key = `${kind}|${ac.id}|`;
      let action = actionByKey.get(key);
      if (!action) {
        action = {
          id: identifier(`action-${kind}-${ac.id}`, 'action'), kind, status: 'proposed', priority: result.verdict === 'FAIL' ? 'high' : 'normal', confidence: 'medium',
          source: { ac_id: ac.id, finding_id: null, evidence_ids: result.evidence_ids },
          ...(row.fix_file && portable(row.fix_file) ? { target: { file: portable(row.fix_file) } } : {}),
          recommendation: bounded(recommendation, 500, 'Review the evaluation result.'), result: { changed_files: [] },
          handoff: { requires_user_invocation: kind === 'human-followup', skill: kind === 'human-followup' ? 'uxd-prototype-evaluate' : '', payload: {} },
        };
        actions.actions.push(action); actionByKey.set(key, action);
      }
      if (!result.action_ids.includes(action.id)) result.action_ids.push(action.id);
    }
    result.updated_at = timestamp(journey.evaluated_at);
  }

  const actionKind = value => {
    const text = String(value || '').toLowerCase();
    if (text.includes('navigate') || text.includes('open')) return 'navigate';
    if (text.includes('click')) return 'click';
    if (text.includes('type') || text.includes('enter') || text.includes('fill')) return 'input';
    if (text.includes('select')) return 'select';
    if (text.includes('verify') || text.includes('confirm') || text.includes('check')) return 'verify';
    return 'observe';
  };
  evaluation.journeys = (journey.journeys || []).map((item, journeyIndex) => {
    const acIds = (item.ac_ids || []).map(id => acBySource.get(id)?.id).filter(Boolean);
    const task = acIds.map(id => taskByAc.get(id)).find(Boolean) || brief.intent.tasks[0];
    const persona = personaByLegacy.get(item.persona) || brief.intent.personas[0];
    return {
      id: identifier(item.id || `journey-${journeyIndex + 1}`, 'journey'), task_id: task.id, persona_id: persona.id, ac_ids: acIds,
      source: bounded(item.source, 280, 'Prototype journey evaluation'), verdict: ['PASS', 'FAIL', 'FLAGGED'].includes(item.verdict) ? item.verdict : 'NOT_RUN',
      steps: (item.steps || []).map((step, stepIndex) => {
        const evidenceId = ensureEvidence(step.screenshot, 'journey');
        const outcome = step.result === 'success' ? 'success' : step.result === 'fail' ? 'failure' : step.result === 'blocked' ? 'blocked' : 'partial';
        return { id: identifier(`step-${journeyIndex + 1}-${step.step || stepIndex + 1}`, 'step'), sequence: Number(step.step || stepIndex + 1), action: actionKind(step.action), target: bounded(step.action, 280, 'Rendered interface'), outcome, evidence_ids: evidenceId ? [evidenceId] : [], note: bounded(step.narration, 280, 'Observed rendered result.') };
      }),
    };
  });

  const rawUsability = journey.usability_dimensions;
  const usability = Array.isArray(rawUsability) ? {
    dimensions: rawUsability,
    overall_score: journey.overall_score,
    max_score: journey.max_score,
    personas_evaluated: journey.personas_evaluated || [],
    persona_overlays: journey.persona_overlays || [],
  } : rawUsability;
  if (usability && Array.isArray(usability.dimensions) && usability.dimensions.length) {
    evaluation.usability = {
      status: 'completed',
      dimensions: usability.dimensions.map(dimension => {
        const rawScores = dimension.scores || {};
        const personaScores = Object.entries(rawScores).map(([legacyId, value]) => ({ persona_id: (personaByLegacy.get(legacyId) || brief.intent.personas[0]).id, score: Number(value.score ?? value) }));
        if (!personaScores.length) {
          const overlays = (usability.persona_overlays || []).filter(item => item.dimension_id === dimension.id);
          overlays.forEach(item => personaScores.push({ persona_id: (personaByLegacy.get(item.persona) || brief.intent.personas[0]).id, score: Number(item.score || 0) }));
        }
        const evidenceIds = [];
        for (const result of personaResults) for (const image of result.screenshots || []) { const id = ensureEvidence(image, 'usability'); if (id && !evidenceIds.includes(id)) evidenceIds.push(id); }
        return { id: identifier(dimension.id, 'dimension'), label: bounded(dimension.name, 280, dimension.id), score: Number(dimension.composite_score || 0), max_score: 3, confidence: String(dimension.confidence || 'medium').toLowerCase() === 'high' ? 'high' : String(dimension.confidence || '').toLowerCase() === 'low' ? 'low' : 'medium', persona_scores: personaScores, evidence_ids: evidenceIds.slice(0, 24) };
      }),
      score: 0, max_score: 0,
    };
    evaluation.usability.score = evaluation.usability.dimensions.reduce((sum, item) => sum + item.score, 0);
    evaluation.usability.max_score = evaluation.usability.dimensions.reduce((sum, item) => sum + item.max_score, 0);
  }

  function consistencyFinding(item, origin) {
    const paths = origin === 'visual' ? [...new Set([item.screenshot, ...(item.seen_on || [])].filter(Boolean))] : [];
    const evidenceIds = paths.map(image => ensureEvidence(image, 'consistency')).filter(Boolean);
    const candidate = origin === 'visual' && item.verdict === 'FLAGGED' || Boolean(item.review_candidate);
    const digest = sha256(JSON.stringify([origin, item.guideline_id, item.file, item.line, paths])).slice(7, 31);
    return {
      id: `finding-${digest}`, origin, guideline_id: identifier(item.guideline_id || 'unknown-guideline', 'guideline'),
      guideline_title: bounded(item.guideline_title, 280, 'PatternFly guideline'), category: bounded(item.category, 80, 'foundations'),
      severity: candidate ? 'warning' : item.severity === 'error' ? 'error' : 'warning', verdict: candidate ? 'FLAGGED' : item.verdict === 'VIOLATION' ? 'VIOLATION' : 'FLAGGED',
      confidence: candidate ? 'low' : ['high', 'medium', 'low'].includes(item.confidence) ? item.confidence : 'medium',
      property: bounded(item.property, 280, origin === 'visual' ? 'rendered-pattern' : 'source'), value: bounded(item.value, 1000, paths.join(';') || 'source match'),
      check_method: origin === 'visual' ? 'visual' : candidate ? 'automated_candidate' : item.check_method === 'automated' ? 'automated' : 'automated_candidate',
      ...(origin === 'source' ? { file: portable(item.file) || 'unknown-source', line: Number.isInteger(item.line) && item.line > 0 ? item.line : null } : {}),
      evidence_ids: evidenceIds, description: bounded(item.description, 280, 'PatternFly consistency finding'), recommendation: bounded(item.suggestion, 500, 'Use the matching PatternFly component or token.'),
      pf_doc_url: /^https?:\/\//.test(String(item.pf_doc_url || '')) ? item.pf_doc_url : 'https://www.patternfly.org/', review_candidate: candidate,
    };
  }
  const sourceFindings = (consistency.source_mode?.violations || []).map(item => consistencyFinding(item, 'source'));
  const visualFindings = (consistency.visual_mode?.findings || []).map(item => consistencyFinding(item, 'visual'));
  evaluation.consistency.findings = [...sourceFindings, ...visualFindings];
  const findingIds = new Set(evaluation.consistency.findings.map(finding => finding.id));
  actions.actions = actions.actions.filter(action => !action.source.finding_id || findingIds.has(action.source.finding_id));
  const retainedActionIds = new Set(actions.actions.map(action => action.id));
  evaluation.ac_results.forEach(result => { result.action_ids = result.action_ids.filter(id => retainedActionIds.has(id)); });
  evaluation.consistency.source_checked = consistency.source_mode?.ran === true;
  evaluation.consistency.visual_checked = consistency.visual_mode?.ran === true;
  evaluation.consistency.screenshots_checked = Number(consistency.visual_mode?.screenshots_checked || 0);
  evaluation.consistency.guidelines_checked = Number(consistency.summary?.total_guidelines_checked || 0);
  const consistencyCounts = { error: 0, warning: 0, info: 0, total: evaluation.consistency.findings.length };
  evaluation.consistency.findings.forEach(finding => { consistencyCounts[finding.severity] += 1; });
  evaluation.consistency.status = consistency.degraded ? 'degraded' : consistencyCounts.error ? 'failed' : consistencyCounts.total ? 'flagged' : 'passed';

  evaluation.summary = { ac_counts: verdictCounts(evaluation.ac_results), consistency_counts: consistencyCounts, journey_counts: verdictCounts(evaluation.journeys) };
  const attention = evaluation.summary.ac_counts.fail || evaluation.summary.ac_counts.flagged || consistencyCounts.error || consistencyCounts.warning || evaluation.summary.journey_counts.fail || evaluation.summary.journey_counts.flagged;
  evaluation.status = attention ? 'needs-attention' : evaluation.usability.status === 'completed' ? 'passed' : 'running';
  const at = timestamp(journey.evaluated_at || consistency.checked_at);
  state.lifecycle = {
    status: evaluation.status === 'running' ? 'running' : 'completed', current_phase: 'report', iteration: 1,
    max_iterations: state.lifecycle.max_iterations, exit_reason: 'no-fix',
    iterations: [
      { iteration: 1, phase: 'a', timestamp: at, ac_results: evaluation.ac_results.map(result => ({ ac_id: result.ac_id, verdict: result.verdict })) },
      { iteration: 1, phase: 'b', timestamp: at, ac_results: [], usability_score: evaluation.usability.score, persona_ids: brief.intent.personas.map(persona => persona.id) },
    ],
  };
  state.phases = state.phases.filter(phase => !['journey', 'consistency-visual', 'usability'].includes(phase.name));
  state.phases.push(
    modelPhase('journey', provider, phaseModel('journey'), at, evaluation.journeys.length ? 'completed' : 'skipped'),
    modelPhase('consistency-visual', provider, phaseModel('consistency-visual'), at, evaluation.consistency.visual_checked ? 'completed' : 'skipped'),
    modelPhase('usability', provider, phaseModel('usability'), at, evaluation.usability.status === 'completed' ? 'completed' : 'skipped'),
  );
  return documents;
}

function install(stage, directory) {
  const backups = [];
  const installed = [];
  try {
    for (const name of FILES) {
      const destination = path.join(directory, name);
      const backup = path.join(directory, `.${name}.phase-b-backup-${process.pid}`);
      fs.renameSync(destination, backup); backups.push([backup, destination]);
      fs.renameSync(path.join(stage, name), destination); installed.push(destination);
    }
    backups.forEach(([backup]) => fs.rmSync(backup, { force: true }));
  } catch (error) {
    installed.forEach(file => fs.rmSync(file, { force: true }));
    backups.forEach(([backup, destination]) => { if (fs.existsSync(backup)) fs.renameSync(backup, destination); });
    throw error;
  }
}

function main() {
  const args = process.argv.slice(2);
  const directoryArg = args.find(arg => !arg.startsWith('--'));
  if (!directoryArg) throw new Error('Usage: sync-phase-b-canonical.js <artifacts-dir> --provider <openai|anthropic-compatible> --model <name> [--json]');
  const option = name => { const index = args.indexOf(name); return index >= 0 ? args[index + 1] : ''; };
  const provider = option('--provider'); const model = option('--model');
  if (!['openai', 'anthropic-compatible'].includes(provider) || !model) throw new Error('A supported provider and model are required');
  const directory = path.resolve(directoryArg);
  const before = validateDirectory(directory);
  if (!before.valid) throw new Error(`Cannot synchronize invalid Phase A canonical files: ${JSON.stringify(before.errors)}`);
  const documents = sync(directory, { provider, model });
  const stage = fs.mkdtempSync(path.join(path.dirname(directory), '.phase-b-stage-'));
  try {
    writeDocuments(stage, documents);
    const validation = validateDirectory(stage);
    if (!validation.valid) throw new Error(`Phase B canonical validation failed: ${JSON.stringify(validation.errors)}`);
    store(path.join(path.dirname(directory), 'cache', 'full-v1'), stage);
    install(stage, directory);
    const result = { status: 'completed', model_invoked: false, canonical_files: [...FILES], ac_counts: documents['evaluation.json'].summary.ac_counts, journey_counts: documents['evaluation.json'].summary.journey_counts, usability_score: documents['evaluation.json'].usability.score, consistency_counts: documents['evaluation.json'].summary.consistency_counts };
    process.stdout.write(args.includes('--json') ? `${JSON.stringify(result)}\n` : 'Synchronized final canonical evaluation.\n');
  } finally { fs.rmSync(stage, { recursive: true, force: true }); }
}

if (require.main === module) { try { main(); } catch (error) { process.stderr.write(`${error.message}\n`); process.exitCode = 1; } }
module.exports = { sync };
