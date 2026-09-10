#!/usr/bin/env node
'use strict';

const assert = require('assert');
const fs = require('fs');
const http = require('http');
const os = require('os');
const path = require('path');
const { chromium } = require('@playwright/test');
const runner = require('../scripts/openai-browser-persona.js');

(async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'uxd-persona-'));
  const artifacts = path.join(root, '.artifacts', 'TEST-1', 'eval'); fs.mkdirSync(artifacts, { recursive: true });
  const server = http.createServer((_req, res) => { res.setHeader('content-type', 'text/html'); res.end('<h1>Playground</h1><button onclick="document.querySelector(\'p\').textContent=\'Tool details visible\'">Show tool call</button><p>Hidden</p>'); });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}/`;
  const calls = [];
  const dimensionScores = runner.DIMENSIONS.map(([id]) => ({ id, score: 2, confidence: 'high', evidence: 'The rendered flow remained understandable.' }));
  const requestFn = async payload => {
    calls.push(payload);
    if (calls.length === 1) return { id: 'r1', output: [{ type: 'function_call', phase: 'commentary', name: 'browser_click', call_id: 'c1', arguments: JSON.stringify({ target: 'Show tool call' }) }], usage: { input_tokens: 10, output_tokens: 5, total_tokens: 15 } };
    if (calls.length === 2) return { id: 'r2', output: [{ type: 'function_call', name: 'browser_observe', call_id: 'c2', arguments: '{}' }], usage: { input_tokens: 12, output_tokens: 8, total_tokens: 20 } };
    const result = { persona: 'ml-engineer+junior', persona_name: 'Alex', task_index: 1, task: 'Inspect tool calls', outcome: 'completed', would_complete: true, abandoned: false, confusion_events: 0, patience_start: 100, patience_end: 100, screenshots: ['screenshots/persona-ml-engineer-junior-task-1-step-2.png'], trace: [{ step: 1, what_i_see: 'Tool details visible', what_im_thinking: 'The disclosure worked.', action: 'Opened tool call details', confidence: 'high', patience: 100, evidence_for_acs: ['AC-1'], screenshots: ['screenshots/persona-ml-engineer-junior-task-1-step-2.png'] }], dimension_scores: dimensionScores };
    return { id: 'r3', output: [{ type: 'message', content: [{ type: 'output_text', text: JSON.stringify(result) }] }], usage: { input_tokens: 14, output_tokens: 9, total_tokens: 23 } };
  };
  const browser = await chromium.launch({ headless: true }); const page = await browser.newPage();
  try {
    const result = await runner.runPersonaSession({ page, artifactsDir: artifacts, prototypeUrl: url, persona: { id: 'ml-engineer+junior', profile: 'Junior ML engineer who needs clear labels.' }, task: 'Inspect tool calls', taskIndex: 1, acIds: ['AC-1'], model: 'gpt-5.6-terra', reasoningEffort: 'low', maxTurns: 3, requestFn });
    assert.equal(result.turns, 3); assert.equal(result.usage.total_tokens, 58);
    const names = calls[0].tools.map(tool => tool.name);
    assert.deepEqual(names, ['browser_observe', 'browser_click', 'browser_type', 'browser_navigate', 'browser_press']);
    assert(!names.some(name => /shell|file|grep|search|workspace/.test(name)));
    assert.equal(calls[0].tool_choice, 'required'); assert.equal(calls[0].text.format.type, 'json_schema');
    assert.deepEqual(calls[0].include, ['reasoning.encrypted_content']);
    assert(calls[0].input[0].content.some(item => item.type === 'input_image'));
    assert(!('previous_response_id' in calls[1]));
    assert.equal(calls[1].input[0].phase, 'commentary');
    assert(calls[1].input.some(item => item.type === 'function_call_output'));
    assert(calls[1].input.at(-1).content.some(item => item.type === 'input_image'));
    assert.equal(calls[2].tool_choice, 'none');
    assert(!JSON.stringify(calls).includes(root));

    const failedPage = await browser.newPage(); let failedCalls = 0;
    try {
      await runner.runPersonaSession({
        page: failedPage, artifactsDir: artifacts, prototypeUrl: url,
        persona: { id: 'ml-engineer+junior', profile: 'Junior ML engineer.' },
        task: 'Inspect tool calls', taskIndex: 2, acIds: ['AC-1'],
        model: 'gpt-5.6-terra', reasoningEffort: 'low', maxTurns: 3,
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
