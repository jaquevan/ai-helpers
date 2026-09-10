#!/usr/bin/env node
'use strict';

/**
 * Capture portable visual evidence for a structured evaluator phase.
 *
 * Usage:
 *   node capture-prototype-evidence.js <artifacts-dir> <prototype-url> [--json]
 *
 * The output JSON stores screenshot paths relative to the artifacts directory.
 * The caller may run this script from any working directory.
 */

const fs = require('fs');
const path = require('path');
let chromium;
try {
  ({ chromium } = require('@playwright/test'));
} catch {
  console.error('This skill requires its local Node dependencies. Run npm install in the uxd-prototype-evaluate skill directory.');
  process.exit(1);
}

const args = process.argv.slice(2);
const jsonMode = args.includes('--json');
const positional = args.filter(arg => !arg.startsWith('--'));
const [artifactsArg, prototypeUrl] = positional;

if (!artifactsArg || !prototypeUrl) {
  console.error('Usage: node capture-prototype-evidence.js <artifacts-dir> <prototype-url> [--json]');
  process.exit(1);
}

function assertSupportedUrl(rawUrl) {
  let parsed;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new Error(`Invalid prototype URL: ${rawUrl}`);
  }
  if (!['http:', 'https:', 'file:'].includes(parsed.protocol)) {
    throw new Error(`Unsupported prototype URL protocol: ${parsed.protocol}`);
  }
  return parsed.toString();
}

async function main() {
  const artifactsDir = path.resolve(artifactsArg);
  const url = assertSupportedUrl(prototypeUrl);
  const screenshotsDir = path.join(artifactsDir, 'screenshots');
  const screenshotRelative = 'screenshots/journey-baseline.png';
  const screenshotPath = path.join(artifactsDir, screenshotRelative);
  const evidencePath = path.join(artifactsDir, 'prototype-evidence.json');

  fs.mkdirSync(screenshotsDir, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  try {
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 30000 });
    await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => null);
    await page.screenshot({ path: screenshotPath, fullPage: false });

    const pageEvidence = await page.evaluate(() => {
      const clean = value => String(value || '').replace(/\s+/g, ' ').trim();
      const visible = element => {
        const style = window.getComputedStyle(element);
        const rect = element.getBoundingClientRect();
        return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
      };
      const textName = element => clean(
        element.getAttribute('aria-label') ||
        element.getAttribute('title') ||
        element.getAttribute('placeholder') ||
        element.textContent ||
        element.getAttribute('value')
      ).slice(0, 240);

      const headings = Array.from(document.querySelectorAll('h1,h2,h3,h4,h5,h6'))
        .filter(visible)
        .slice(0, 40)
        .map(element => ({
          level: Number(element.tagName.slice(1)),
          text: clean(element.textContent).slice(0, 300),
        }));

      const controls = Array.from(document.querySelectorAll(
        'button,a[href],input,select,textarea,[role="button"],[role="tab"],[role="menuitem"],[role="checkbox"],[role="radio"]'
      ))
        .filter(visible)
        .slice(0, 100)
        .map(element => ({
          tag: element.tagName.toLowerCase(),
          role: element.getAttribute('role') || '',
          name: textName(element),
          href: element.getAttribute('href') || '',
          disabled: Boolean(element.disabled || element.getAttribute('aria-disabled') === 'true'),
          expanded: element.getAttribute('aria-expanded') || '',
          selected: element.getAttribute('aria-selected') || '',
        }));

      return {
        title: document.title,
        body_text: clean(document.body && document.body.innerText).slice(0, 16000),
        headings,
        controls,
      };
    });

    const evidence = {
      schema_version: 1,
      capture_method: 'deterministic-baseline',
      prototype_url: page.url(),
      captured_at: new Date().toISOString(),
      viewport: { width: 1440, height: 900 },
      screenshots: [screenshotRelative],
      page: pageEvidence,
    };
    fs.writeFileSync(evidencePath, `${JSON.stringify(evidence, null, 2)}\n`);

    const result = {
      status: 'completed',
      model_invoked: false,
      implementation: path.basename(__filename),
      evidence_file: evidencePath,
      screenshot_count: evidence.screenshots.length,
      screenshot_paths: evidence.screenshots,
      heading_count: evidence.page.headings.length,
      control_count: evidence.page.controls.length,
    };
    console.log(jsonMode ? JSON.stringify(result) : `Captured ${result.screenshot_count} screenshot to ${evidencePath}`);
  } finally {
    await browser.close();
  }
}

main().catch(error => {
  console.error(error.message);
  process.exit(1);
});
