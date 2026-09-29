#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { chromium } = require('@playwright/test');
const runner = require('../scripts/openai-browser-persona.js');

function pngSize(file) {
  const data = fs.readFileSync(file);
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
}

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-persona-'));
  const artifacts = path.join(root, '.artifacts', 'TEST-1', 'eval'); fs.mkdirSync(artifacts, { recursive: true });
  const server = http.createServer((_req, res) => { res.setHeader('content-type', 'text/html'); res.end('<h1>Playground</h1><button onclick="document.querySelector(\'p\').textContent=\'Tool details visible\'">Show tool call</button><p>Hidden</p>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const calls = [];
  const dimensionScores = runner.DIMENSIONS.map(([id]) => ({ id, score: 2, confidence: 'high', evidence: 'Playground tool call is visible.' }));
  const requestFn = async payload => {
    calls.push(payload);
    if (calls.length === 1) return { id: 'r1', output: [{ type: 'function_call', phase: 'commentary', name: 'browser_click', call_id: 'c1', arguments: JSON.stringify({ target: 'Show tool call' }) }], usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 } };
    if (calls.length === 2) return { id: 'r2', output: [{ type: 'function_call', name: 'browser_observe', call_id: 'c2', arguments: '{}' }], usage: { input_tokens: 12, output_tokens: 8, total_tokens: 20 } };
    const result = { persona: 'ml-engineer+junior', persona_name: 'Alex', task_index: 1, task: 'Inspect tool calls', outcome: 'completed', would_complete: true, abandoned: false, confusion_events: 0, patience_start: 100, patience_end: 100, screenshots: ['screenshots/persona-ml-engineer-junior-task-1-step-2.png'], trace: [{ step: 1, what_i_see: 'Tool details visible', what_im_thinking: 'The disclosure worked.', action: 'Opened tool call details', confidence: 'high', patience: 100, evidence_for_acs: ['AC-1'], screenshots: ['screenshots/persona-ml-engineer-junior-task-1-step-2.png'] }], dimension_scores: dimensionScores };
    return { id: 'r3', output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(result) }] }], usage: { input_tokens: 14, output_tokens: 9, total_tokens: 23 } };
  };
  const browser = await chromium.launch({ headless: true }); const page = await browser.newPage();
  try {
    const result = await runner.runPersonaSession({ page, artifactsDir: artifacts, prototypeUrl: url, persona: { id: 'ml-engineer+junior', profile: 'Junior ML engineer who needs clear labels.' }, task: 'Inspect tool calls', taskIndex: 1, acIds: ['AC-1'], model: 'gpt-6-sol', reasoningEffort: 'high', maxTurns: 3, requestFn });
    assert.equal(result.turns, 3); assert.equal(result.usage.total_tokens, 58);
    assert(result.promptCache.static_prefix_sha256.startsWith('sha256:'));
    assert(result.promptCache.static_prefix_bytes > 0);
    assert(result.promptCache.dynamic_input_bytes > 0);
    const names = calls[0].tools.map(tool => tool.name);
    assert.deepEqual(names, ['browser_observe', 'browser_click', 'browser_type', 'browser_navigate', 'browser_press']);
    assert(!names.some(name => /shell|file|grep|search|workspace/.test(name)));
    assert.equal(calls[0].tool_choice, 'required'); assert.equal(calls[0].text.format.type, 'json_schema');
    assert.equal(calls[0].model, 'gpt-6-sol'); assert.equal(calls[0].reasoning.effort, 'high');
    assert.equal(calls[0].max_output_tokens, 4000);
    assert(!('include' in calls[0]));
    assert(calls[0].input[0].content.some(item => item.type === 'input_image'));
    assert(!('previous_response_id' in calls[1]));
    assert.equal(calls[1].input[0].phase, 'commentary');
    assert(calls[1].input.some(item => item.type === 'function_call_output'));
    assert(calls[1].input.at(-1).content.some(item => item.type === 'input_image'));
    assert.equal(calls[2].tool_choice, 'none');
    assert(!JSON.stringify(calls).includes(root));
    const raw = path.join(artifacts, 'screenshots', 'persona-ml-engineer-junior-task-1-step-1.png');
    const crops = fs.readdirSync(path.join(artifacts, 'evidence', 'crops')).filter(file => file.includes('persona-ml-engineer-junior-task-1'));
    assert(crops.length >= 1);
    const rawSize = pngSize(raw);
    const cropSize = pngSize(path.join(artifacts, 'evidence', 'crops', crops[0]));
    assert(cropSize.width < rawSize.width || cropSize.height < rawSize.height);

    const observedStates = new Map([['screenshots/observed.png', {
      title: 'Playground', text: 'Chat with models', headings: [],
      controls: [{ name: 'Chat with models' }],
    }]]);
    const unsupportedClaim = {
      trace: [{ action: 'Clicked Test gen AI models and apps' }],
      dimension_scores: runner.DIMENSIONS.map(([id]) => ({ id, evidence: 'Performance filters and runtime arguments are available.' })),
    };
    assert.throws(
      () => runner.validateEvidenceGrounding(unsupportedClaim, observedStates),
      /not grounded in captured rendered evidence/
    );
    const groundedClaim = {
      trace: [{ action: 'Opened Chat with models' }],
      dimension_scores: runner.DIMENSIONS.map(([id]) => ({ id, evidence: 'Chat with models is visible.' })),
    };
    runner.validateEvidenceGrounding(groundedClaim, observedStates);
    const screenshotGroundedAction = {
      trace: [{ action: 'Compared the generated output before sharing it with a developer.', screenshots: ['screenshots/observed.png'] }],
      dimension_scores: runner.DIMENSIONS.map(([id]) => ({ id, evidence: 'Chat with models is visible.' })),
    };
    runner.validateEvidenceGrounding(screenshotGroundedAction, observedStates);
    runner.validateEvidenceGrounding({
      screenshots: ['screenshots/observed.png'],
      trace: [{ action: 'Open the Playground workflow.', screenshots: [] }],
      dimension_scores: [{ id: 'workflow_continuity', evidence: 'Chat with models is visible.' }],
    }, observedStates);
    runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'No handoff was visible in this interaction.' }],
    }, observedStates);
    runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'Configuration options were visible, but I did not need them for this question.' }],
    }, observedStates);
    runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'The message was readable; I did not test assistive-technology use.' }],
    }, observedStates);
    runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'I could submit the message with Enter; this interaction does not establish accessibility of the remaining controls.' }],
    }, observedStates);
    runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'The screenshot shows View code and Save agent; no handoff is demonstrated in this interaction.' }],
    }, observedStates);
    assert.throws(() => runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'No security audit visible.' }],
    }, observedStates), /not grounded/);
    assert.throws(() => runner.validateEvidenceGrounding({
      trace: [], dimension_scores: [{ evidence: 'A security audit is available in this interaction.' }],
    }, observedStates), /not grounded/);

    fs.writeFileSync(path.join(artifacts, 'extract-state.json'), JSON.stringify({
      persona_selection: { selected: ['ml-engineer+junior', 'ml-engineer+senior'] },
      tasks_to_be_done: [{ task: 'Inspect tool calls', covers_acs: ['AC-1'] }],
    }));
    fs.writeFileSync(path.join(artifacts, 'journey-log.json'), JSON.stringify({ journeys: [] }));
    const live = await runner.runLiveUsability({
      artifactsDir: artifacts, prototypeUrl: url, skillDir: path.resolve(__dirname, '..'),
      model: 'gpt-6-sol', reasoningEffort: 'high', maxTurns: 8,
      requestFn: async payload => {
        assert.equal(payload.max_output_tokens, 4000);
        const personaId = payload.instructions.includes('Selected experience overlay: senior') ? 'ml-engineer+senior' : 'ml-engineer+junior';
        if (payload.tool_choice === 'required') return { usage: { input_tokens: 5, output_tokens: 2 }, output: [{ type: 'function_call', name: 'browser_click', call_id: 'click', arguments: JSON.stringify({ target: 'Show tool call' }) }] };
        const personaResult = {
          persona: personaId, persona_name: personaId, task_index: 1, task: 'Inspect tool calls', outcome: 'completed',
          would_complete: true, abandoned: false, confusion_events: 0, patience_start: 100, patience_end: 100,
          screenshots: [`screenshots/persona-${personaId.replace('+', '-')}-task-1-step-2.png`],
          trace: [{ step: 1, what_i_see: 'Tool details visible', what_im_thinking: 'I found the details.', action: 'Opened tool call details', confidence: 'high', patience: 100, evidence_for_acs: ['AC-1'], screenshots: [`screenshots/persona-${personaId.replace('+', '-')}-task-1-step-2.png`] }],
          dimension_scores: runner.DIMENSIONS.map(([id]) => ({ id, score: 2, confidence: 'high', evidence: 'Playground tool call is visible.' })),
        };
        return { usage: { input_tokens: 7, output_tokens: 5 }, output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(personaResult) }] }] };
      },
    });
    assert.equal(live.results.length, 2);
    assert.equal(live.turns_used, 4);
    assert.equal(JSON.parse(fs.readFileSync(path.join(artifacts, 'persona-results.json'))).length, 2);
    const mergedJourney = JSON.parse(fs.readFileSync(path.join(artifacts, 'journey-log.json')));
    assert.equal(mergedJourney.usability_dimensions.personas_evaluated.length, 2);
    assert.equal(mergedJourney.usability_dimensions.dimensions.length, 7);

    const failedPage = await browser.newPage(); let failedCalls = 0;
    try {
      await runner.runPersonaSession({
        page: failedPage, artifactsDir: artifacts, prototypeUrl: url,
        persona: { id: 'ml-engineer+junior', profile: 'Junior ML engineer.' },
        task: 'Inspect tool calls', taskIndex: 2, acIds: ['AC-1'],
        model: 'gpt-6-sol', reasoningEffort: 'high', maxTurns: 3,
        requestFn: async () => {
          failedCalls += 1;
          if (failedCalls === 1) return { id: 'r3', output: [{ type: 'function_call', call_id: 'c2', name: 'browser_observe', arguments: '{}' }], usage: { input_tokens: 7, output_tokens: 3, total_tokens: 10 } };
          throw new Error('provider unavailable');
        },
      });
      assert.fail('Expected LiveUsabilityError');
    } catch (error) {
      assert(error instanceof runner.LiveUsabilityError);
      assert.equal(error.usage.total_tokens, 10);
      assert.equal(error.turns, 2);
    } finally { await failedPage.close(); }
  } finally { await browser.close(); server.close(); fs.rmSync(root, { recursive: true, force: true }); }
  console.log('PASS');
})().catch(error => { console.error(error); process.exit(1); });
