#!/usr/bin/env node
'use strict';

/** Live persona runner. The model receives browser functions only—never shell or files. */

const fs = require('fs');
const path = require('path');
const { chromium } = require('@playwright/test');
const { escapeCSVField } = require('./csv-utils');

const DIMENSIONS = [
  ['workflow_continuity', 'Workflow Continuity & Integrity'],
  ['cross_persona_handoffs', 'Cross-Persona Context & Handoffs'],
  ['scalability_progressive_complexity', 'Scalability & Progressive Complexity'],
  ['system_status_trust', 'System Status, Observability & Trust'],
  ['technical_abstraction', 'Technical Abstraction & Signal-to-Noise'],
  ['mental_model_fidelity', 'Mental Model Fidelity'],
  ['accessibility_inclusion', 'Accessibility & Inclusion'],
];

class LiveUsabilityError extends Error {
  constructor(message, { usage: responseUsage, turns } = {}) {
    super(message);
    this.name = 'LiveUsabilityError';
    this.usage = responseUsage;
    this.turns = turns;
  }
}

function objectSchema(properties, required = Object.keys(properties)) {
  return { type: 'object', properties, required, additionalProperties: false };
}

function browserTools() {
  const tool = (name, description, properties, required = Object.keys(properties)) => ({
    type: 'function', name, description,
    parameters: objectSchema(properties, required), strict: true,
  });
  return [
    tool('browser_observe', 'Inspect the currently rendered page and capture a screenshot.', {}),
    tool('browser_click', 'Click one visible control by its accessible label or visible text.', { target: { type: 'string' } }),
    tool('browser_type', 'Fill a visible field identified by label or placeholder.', { target: { type: 'string' }, text: { type: 'string' } }),
    tool('browser_navigate', 'Navigate to a same-origin path within the prototype.', { path: { type: 'string' } }),
    tool('browser_press', 'Press an allowed keyboard key on a visible field or the page.', { target: { type: 'string' }, key: { type: 'string', enum: ['Enter', 'Escape', 'Tab', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'] } }),
  ];
}

function personaSchema(personaId, taskIndex, acIds) {
  const string = { type: 'string' };
  const score = objectSchema({
    id: { type: 'string', enum: DIMENSIONS.map(([id]) => id) },
    score: { type: 'integer', minimum: 0, maximum: 3 },
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    evidence: string,
  });
  const trace = objectSchema({
    step: { type: 'integer', minimum: 1 }, what_i_see: string,
    what_im_thinking: string, action: string,
    confidence: { type: 'string', enum: ['low', 'medium', 'high'] },
    patience: { type: 'integer', minimum: 0, maximum: 100 },
    evidence_for_acs: { type: 'array', items: { type: 'string', enum: acIds.length ? acIds : ['none'] } },
    screenshots: { type: 'array', items: string },
  });
  return objectSchema({
    persona: { type: 'string', enum: [personaId] }, persona_name: string,
    task_index: { type: 'integer', enum: [taskIndex] }, task: string,
    outcome: { type: 'string', enum: ['completed', 'abandoned', 'blocked'] },
    would_complete: { type: 'boolean' }, abandoned: { type: 'boolean' },
    confusion_events: { type: 'integer', minimum: 0 },
    patience_start: { type: 'integer', minimum: 0, maximum: 100 },
    patience_end: { type: 'integer', minimum: 0, maximum: 100 },
    screenshots: { type: 'array', items: string },
    trace: { type: 'array', items: trace, minItems: 1 },
    dimension_scores: { type: 'array', items: score, minItems: 7, maxItems: 7 },
  });
}

function outputText(response) {
  if (typeof response.output_text === 'string') return response.output_text;
  return (response.output || []).filter(i => i.type === 'message')
    .flatMap(i => i.content || []).filter(c => c.type === 'output_text').map(c => c.text || '').join('');
}

function validateSchema(value, schema, at = '$') {
  if (schema.type === 'object') {
    if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${at} must be an object`);
    for (const key of schema.required || []) if (!(key in value)) throw new Error(`${at}.${key} is required`);
    if (schema.additionalProperties === false) for (const key of Object.keys(value)) if (!(key in schema.properties)) throw new Error(`${at}.${key} is unexpected`);
    for (const [key, child] of Object.entries(schema.properties || {})) if (key in value) validateSchema(value[key], child, `${at}.${key}`);
  } else if (schema.type === 'array') {
    if (!Array.isArray(value)) throw new Error(`${at} must be an array`);
    if (schema.minItems !== undefined && value.length < schema.minItems) throw new Error(`${at} has too few items`);
    if (schema.maxItems !== undefined && value.length > schema.maxItems) throw new Error(`${at} has too many items`);
    value.forEach((item, index) => validateSchema(item, schema.items, `${at}[${index}]`));
  } else if (schema.type === 'string') {
    if (typeof value !== 'string') throw new Error(`${at} must be a string`);
    if (schema.enum && !schema.enum.includes(value)) throw new Error(`${at} has an unsupported value`);
  } else if (schema.type === 'integer') {
    if (!Number.isInteger(value)) throw new Error(`${at} must be an integer`);
    if (schema.minimum !== undefined && value < schema.minimum) throw new Error(`${at} is below minimum`);
    if (schema.maximum !== undefined && value > schema.maximum) throw new Error(`${at} is above maximum`);
  } else if (schema.type === 'boolean' && typeof value !== 'boolean') throw new Error(`${at} must be boolean`);
}

function usage(response) {
  const u = response.usage || {}, input = Number(u.input_tokens || 0), output = Number(u.output_tokens || 0);
  return { input_tokens: input, output_tokens: output, total_tokens: Number(u.total_tokens || input + output), cached_input_tokens: Number((u.input_tokens_details || {}).cached_tokens || 0), reasoning_tokens: Number((u.output_tokens_details || {}).reasoning_tokens || 0) };
}

function addUsage(total, next) { for (const key of Object.keys(total)) total[key] += next[key] || 0; }

async function requestOpenAI(payload) {
  if (!process.env.OPENAI_API_KEY) throw new Error('OPENAI_API_KEY is required');
  const base = (process.env.OPENAI_BASE_URL || 'https://api.openai.com/v1').replace(/\/$/, '');
  const endpoint = base.endsWith('/responses') ? base : `${base}/responses`;
  const headers = { Authorization: `Bearer ${process.env.OPENAI_API_KEY}`, 'Content-Type': 'application/json' };
  if (process.env.OPENAI_ORG_ID) headers['OpenAI-Organization'] = process.env.OPENAI_ORG_ID;
  if (process.env.OPENAI_PROJECT_ID) headers['OpenAI-Project'] = process.env.OPENAI_PROJECT_ID;
  const response = await fetch(endpoint, { method: 'POST', headers, body: JSON.stringify(payload) });
  if (!response.ok) throw new Error(`OpenAI Responses API error ${response.status}: ${(await response.text()).slice(0, 1200)}`);
  return response.json();
}

function imageContent(file) {
  return { type: 'input_image', image_url: `data:image/png;base64,${fs.readFileSync(file).toString('base64')}`, detail: 'high' };
}

async function pageState(page) {
  return page.evaluate(() => ({
    url: location.href, title: document.title,
    text: (document.body?.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 12000),
    headings: [...document.querySelectorAll('h1,h2,h3')].slice(0, 30).map(el => ({ level: el.tagName, text: (el.innerText || '').trim() })),
    controls: [...document.querySelectorAll('button,a,input,textarea,select,[role]')].filter(el => {
      const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0;
    }).slice(0, 100).map(el => ({ tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '', name: (el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.innerText || el.getAttribute('name') || '').trim().slice(0, 180) })),
  }));
}

async function locatorFor(page, target) {
  const candidates = [
    page.getByRole('button', { name: target, exact: true }), page.getByRole('link', { name: target, exact: true }),
    page.getByRole('tab', { name: target, exact: true }), page.getByLabel(target, { exact: true }),
    page.getByPlaceholder(target, { exact: true }), page.getByText(target, { exact: true }),
  ];
  for (const candidate of candidates) if (await candidate.count()) return candidate.first();
  throw new Error(`No visible browser target matched: ${target}`);
}

async function executeBrowserTool(page, call, origin) {
  const args = JSON.parse(call.arguments || '{}');
  if (call.name === 'browser_observe') return;
  if (call.name === 'browser_click') return (await locatorFor(page, args.target)).click();
  if (call.name === 'browser_type') return (await locatorFor(page, args.target)).fill(String(args.text).slice(0, 2000));
  if (call.name === 'browser_press') return args.target ? (await locatorFor(page, args.target)).press(args.key) : page.keyboard.press(args.key);
  if (call.name === 'browser_navigate') {
    const destination = new URL(args.path, origin);
    if (destination.origin !== origin) throw new Error('Cross-origin navigation is not allowed');
    return page.goto(destination.href, { waitUntil: 'networkidle' });
  }
  throw new Error(`Unsupported browser tool: ${call.name}`);
}

function validatePersonaResult(result, { personaId, taskIndex, acIds, screenshots }) {
  validateSchema(result, personaSchema(personaId, taskIndex, acIds));
  if (result.persona !== personaId || result.task_index !== taskIndex) throw new Error('Persona result identity mismatch');
  const expectedDims = new Set(DIMENSIONS.map(([id]) => id));
  if (!Array.isArray(result.dimension_scores) || new Set(result.dimension_scores.map(d => d.id)).size !== 7 || result.dimension_scores.some(d => !expectedDims.has(d.id))) throw new Error('Persona result must score each canonical dimension exactly once');
  const allowed = new Set(acIds.length ? acIds : ['none']);
  for (const step of result.trace || []) {
    if ((step.evidence_for_acs || []).some(id => !allowed.has(id))) throw new Error('Persona trace contains unknown AC ID');
    if ((step.screenshots || []).some(file => !screenshots.has(file))) throw new Error('Persona trace references an uncaptured screenshot');
  }
  if ((result.screenshots || []).some(file => !screenshots.has(file))) throw new Error('Persona result references an uncaptured screenshot');
}

async function runPersonaSession({ page, artifactsDir, prototypeUrl, persona, task, taskIndex, acIds, model, reasoningEffort, maxTurns, requestFn = requestOpenAI, traceStream }) {
  const slug = persona.id.replace(/[^a-z0-9_-]/gi, '-');
  const screenshots = new Set(); let shot = 0; let actions = 0;
  const capture = async () => {
    shot += 1; const relative = `screenshots/persona-${slug}-task-${taskIndex}-step-${shot}.png`;
    const target = path.join(artifactsDir, relative); fs.mkdirSync(path.dirname(target), { recursive: true });
    await page.screenshot({ path: target, fullPage: true }); screenshots.add(relative);
    return { relative, target, state: await pageState(page) };
  };
  await page.goto(prototypeUrl, { waitUntil: 'networkidle' });
  const origin = new URL(prototypeUrl).origin; let current = await capture();
  const system = `Act as this usability-test participant, not as a developer or evaluator.\n\nPERSONA\n${persona.profile}\n\nGOAL\n${task}\n\nUse only the browser functions. Judge only what the rendered interface reveals. Do not infer or request source code, files, shell access, Jira, or implementation details. Think and act from the persona's experience level. Use at most ${Math.max(1, maxTurns - 1)} browser actions. After the last allowed browser action, return the strict result immediately. If the UI still does not expose needed information after inspecting the most relevant control, record the task as blocked or abandoned with rendered evidence; do not repeat toggles or keep searching.`;
  const schema = personaSchema(persona.id, taskIndex, acIds);
  let payload = {
    model, instructions: system,
    input: [{ role: 'user', content: [{ type: 'input_text', text: `Acceptance criteria relevant to this task: ${JSON.stringify(acIds)}\nInitial rendered UI: ${JSON.stringify(current.state)}` }, imageContent(current.target)] }],
    tools: browserTools(), tool_choice: 'required', parallel_tool_calls: false,
    reasoning: { effort: reasoningEffort }, text: { format: { type: 'json_schema', name: 'uxd_live_persona_result', strict: true, schema }, verbosity: 'low' },
    max_output_tokens: 5000, store: false, include: ['reasoning.encrypted_content'],
  };
  const total = { input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_input_tokens: 0, reasoning_tokens: 0 };
  for (let turn = 1; turn <= maxTurns; turn += 1) {
    try {
      const response = await requestFn(payload); addUsage(total, usage(response));
      if (response.status && response.status !== 'completed') throw new Error(`OpenAI persona response status was ${response.status}`);
      if (traceStream) fs.appendFileSync(traceStream, JSON.stringify(response) + '\n');
      const calls = (response.output || []).filter(item => item.type === 'function_call');
      if (!calls.length) {
        if (!actions) throw new Error('Persona returned a result without interacting with the browser');
        const text = outputText(response); if (!text) throw new Error('Persona response contained neither browser calls nor structured output');
        const result = JSON.parse(text); validatePersonaResult(result, { personaId: persona.id, taskIndex, acIds, screenshots });
        return { result, usage: total, turns: turn, outputText: text };
      }
      if (turn >= maxTurns) throw new Error('Persona used reserved final-result turn for browser actions');
      const outputs = [...(response.output || [])];
      for (const call of calls) {
        let result;
        try { await executeBrowserTool(page, call, origin); actions += 1; await page.waitForTimeout(150); current = await capture(); result = { ok: true, screenshot: current.relative, page: current.state }; }
        catch (error) { current = await capture(); result = { ok: false, error: String(error.message || error), screenshot: current.relative, page: current.state }; }
        outputs.push({ type: 'function_call_output', call_id: call.call_id, output: JSON.stringify(result) });
      }
      outputs.push({ role: 'user', content: [{ type: 'input_text', text: `Current rendered UI after browser action: ${JSON.stringify(current.state)}` }, imageContent(current.target)] });
      payload = { model, instructions: system, input: outputs, tools: browserTools(), tool_choice: turn >= maxTurns - 1 ? 'none' : 'auto', parallel_tool_calls: false, reasoning: { effort: reasoningEffort }, text: { format: { type: 'json_schema', name: 'uxd_live_persona_result', strict: true, schema }, verbosity: 'low' }, max_output_tokens: 5000, store: false, include: ['reasoning.encrypted_content'] };
    } catch (error) {
      if (error instanceof LiveUsabilityError) throw error;
      throw new LiveUsabilityError(String(error.message || error), { usage: total, turns: turn });
    }
  }
  throw new LiveUsabilityError(`Persona exceeded its ${maxTurns}-turn browser limit`, { usage: total, turns: maxTurns });
}

function loadPersona(skillDir, selectedId) {
  const [role, overlay = ''] = selectedId.split('+');
  const knowledge = path.resolve(skillDir, '..', '..', 'knowledge', 'personas');
  const card = path.join(knowledge, `${role}.md`);
  if (!fs.existsSync(card)) throw new Error(`Bundled persona card not found: ${role}`);
  let profile = fs.readFileSync(card, 'utf8');
  if (overlay) {
    const overlayCard = path.join(knowledge, 'overlays', 'experience.md');
    profile += `\n\nSelected experience overlay: ${overlay}\n${fs.readFileSync(overlayCard, 'utf8')}`;
  }
  return { id: selectedId, profile: profile.slice(0, 9000) };
}

function aggregateArtifacts(artifactsDir, results) {
  const journeyPath = path.join(artifactsDir, 'journey-log.json');
  const journey = JSON.parse(fs.readFileSync(journeyPath, 'utf8'));
  const dimensions = DIMENSIONS.map(([id, name]) => {
    const scores = {}; const relevant = results.map(r => ({ persona: r.persona, value: r.dimension_scores.find(d => d.id === id) }));
    for (const item of relevant) scores[item.persona] = { score: item.value.score, finding: item.value.evidence };
    const composite = relevant.reduce((sum, item) => sum + item.value.score, 0) / relevant.length;
    return { id, name, composite_score: Math.round(composite * 100) / 100, confidence: relevant.every(i => i.value.confidence === 'high') ? 'high' : 'medium', evidence: relevant.map(i => `${i.persona}: ${i.value.evidence}`).join(' '), scores };
  });
  journey.usability_dimensions = {
    overall_score: Math.round(dimensions.reduce((sum, d) => sum + d.composite_score, 0) * 100) / 100,
    max_score: 21, personas_evaluated: [...new Set(results.map(r => r.persona))], dimensions,
    persona_overlays: results.map(r => ({ persona: r.persona, persona_name: r.persona_name, task_index: r.task_index, patience_start: r.patience_start, patience_end: r.patience_end, abandoned: r.abandoned, confusion_events: r.confusion_events, cli_escapes: 0 })),
    think_aloud: { traces: results.flatMap(r => r.trace.map(t => ({ persona: r.persona, task_index: r.task_index, ...t }))) },
  };
  const csvPath = path.join(artifactsDir, 'evaluation-report.csv');
  const original = fs.readFileSync(csvPath, 'utf8').split(/\n# USABILITY DIMENSIONS\n/)[0].trimEnd();
  const rows = dimensions.map(d => [d.id, d.name, d.composite_score, d.confidence, d.evidence, Object.entries(d.scores).map(([p, s]) => `${p}:${s.score}`).join(';')].map(escapeCSVField).join(','));
  const csv = `${original}\n\n# USABILITY DIMENSIONS\ndimension_id,dimension_name,score,confidence,evidence,persona_scores\n${rows.join('\n')}\n`;
  const writes = [[path.join(artifactsDir, 'persona-results.json'), JSON.stringify(results, null, 2) + '\n'], [journeyPath, JSON.stringify(journey, null, 2) + '\n'], [csvPath, csv]];
  for (const [target, text] of writes) fs.writeFileSync(`${target}.tmp`, text);
  for (const [target] of writes) fs.renameSync(`${target}.tmp`, target);
}

async function runLiveUsability({ artifactsDir, prototypeUrl, skillDir, model, reasoningEffort = 'low', maxTurns = 12, requestFn = requestOpenAI, traceStream }) {
  const extract = JSON.parse(fs.readFileSync(path.join(artifactsDir, 'extract-state.json'), 'utf8'));
  const selected = (extract.persona_selection || {}).selected || [];
  const tasks = extract.tasks_to_be_done || [];
  if (!selected.length || !tasks.length) throw new Error('Usability requires selected personas and tasks');
  const browser = await chromium.launch({ headless: true }); const results = [];
  const total = { input_tokens: 0, output_tokens: 0, total_tokens: 0, cached_input_tokens: 0, reasoning_tokens: 0 };
  let turns = 0;
  try {
    for (const personaId of selected) for (let index = 0; index < tasks.length; index += 1) {
      const remainingSessions = (selected.length * tasks.length) - results.length;
      const remainingTurns = maxTurns - turns;
      if (remainingTurns < remainingSessions * 2) throw new Error('Shared browser turn budget cannot give every persona-task at least two turns');
      const context = await browser.newContext({ viewport: { width: 1440, height: 900 } }); const page = await context.newPage();
      const task = typeof tasks[index] === 'string' ? tasks[index] : (tasks[index].task || tasks[index].goal || JSON.stringify(tasks[index]));
      const acIds = typeof tasks[index] === 'object' ? (tasks[index].covers_acs || []) : [];
      try {
        const session = await runPersonaSession({ page, artifactsDir, prototypeUrl, persona: loadPersona(skillDir, personaId), task, taskIndex: index + 1, acIds, model, reasoningEffort, maxTurns: Math.min(6, remainingTurns - ((remainingSessions - 1) * 2)), requestFn, traceStream });
        turns += session.turns; addUsage(total, session.usage); results.push(session.result);
      } catch (error) {
        if (error instanceof LiveUsabilityError) {
          turns += error.turns || 0; addUsage(total, error.usage || {});
          throw new LiveUsabilityError(error.message, { usage: total, turns });
        }
        throw error;
      } finally { await context.close(); }
    }
  } finally { await browser.close(); }
  aggregateArtifacts(artifactsDir, results);
  return { results, token_usage: total, turns_used: turns };
}

async function main() {
  const args = process.argv.slice(2); const get = flag => args[args.indexOf(flag) + 1];
  const artifactsDir = path.resolve(get('--artifacts-dir')); const started = Date.now();
  try {
    const result = await runLiveUsability({ artifactsDir, prototypeUrl: get('--url'), skillDir: path.resolve(__dirname, '..'), model: get('--model'), reasoningEffort: get('--reasoning-effort') || 'low', maxTurns: Number(get('--max-turns') || 12), traceStream: get('--trace') });
    process.stdout.write(JSON.stringify({ provider: 'openai', model: get('--model'), agent: 'responses-api-live-browser-personas', duration_s: Math.round((Date.now() - started) / 10) / 100, exit_code: 0, status: 'completed', output_text: JSON.stringify({ persona_runs: result.results }), token_usage: result.token_usage, cost_usd: null, billing_source: 'aggregated_by_pipeline', turns_used: result.turns_used, turn_limit_reached: false }));
  } catch (error) {
    process.stdout.write(JSON.stringify({ provider: 'openai', model: get('--model'), agent: 'responses-api-live-browser-personas', duration_s: Math.round((Date.now() - started) / 10) / 100, exit_code: 2, status: 'failed', output_text: String(error.message || error), token_usage: error.usage || {}, cost_usd: null, billing_source: 'aggregated_by_pipeline', turns_used: error.turns || 0, turn_limit_reached: false }));
    process.exitCode = 2;
  }
}

module.exports = { DIMENSIONS, LiveUsabilityError, browserTools, personaSchema, validateSchema, validatePersonaResult, runPersonaSession, runLiveUsability, loadPersona };
if (require.main === module) main().catch(error => { console.error(error.stack || error); process.exit(2); });
