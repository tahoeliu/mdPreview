#!/usr/bin/env node
/*
 * Quality gate for the update bubble UI (mdPreview, JS side).
 *
 * Covers the user-facing contract agreed for the updater:
 *   - manual download: bubble shows a percent progress (no MB)
 *   - download failure: bubble shows a short reason (by code) and the status
 *     bar carries the detailed cause
 *   - after download completes: the same "click to install" bubble as the
 *     auto-download path
 *   - dismissing the bubble does not break a later progress show
 *
 * Loads the REAL index.html + app.js inside jsdom and drives the actual
 * window functions.
 *
 * Run:
 *   <node> tests/test_update_ui.js
 */
'use strict';

const { JSDOM } = require('jsdom');
const fs = require('fs');
const path = require('path');

const REPO = path.resolve(__dirname, '..');

let passed = 0;
let failed = 0;
const failures = [];

function ok(cond, name, detail) {
  if (cond) { passed++; console.log('  PASS  ' + name); }
  else { failed++; failures.push(name + (detail ? ' :: ' + detail : '')); console.log('  FAIL  ' + name + (detail ? ' :: ' + detail : '')); }
}

function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

(async () => {
  const htmlSrc = fs.readFileSync(path.join(REPO, 'index.html'), 'utf8');
  const dom = new JSDOM(htmlSrc, {
    runScripts: 'dangerously',
    resources: 'usable',
    pretendToBeVisual: true,
    url: 'file://' + REPO + '/index.html',
    beforeParse(window) {
      window.matchMedia = window.matchMedia || function (q) {
        return { matches: false, media: q, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {} };
      };
    },
  });
  const { window } = dom;
  const doc = window.document;

  let ready = false;
  for (let i = 0; i < 100; i++) {
    if (typeof window.showUpdateDownloadProgress === 'function' && typeof window.marked !== 'undefined') { ready = true; break; }
    await sleep(100);
  }
  if (!ready) { console.error('FATAL: app.js did not load in jsdom'); process.exit(1); }

  window.pywebview = { api: { set_dirty: async () => true, store_content: async () => true } };

  const bubble = () => doc.getElementById('updateBubble');

  console.log('\n[1] manual download progress (percent only)');
  {
    window.showUpdateDownloadProgress(0);
    ok(bubble().classList.contains('visible'), '1a bubble visible at 0%');
    ok(bubble().classList.contains('downloading'), '1b downloading state');
    window.showUpdateDownloadProgress(37);
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '37%', '1c progress bar width 37%', bar.style.width);
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/37%/.test(txt), '1d text shows percent', txt);
    ok(!/MB|KB/i.test(txt), '1e no MB/KB in text', txt);
  }

  console.log('\n[2] download failure shows reason by code');
  {
    window.showUpdateDownloadFailed('network', 'detail for status bar');
    ok(bubble().classList.contains('visible'), '2a bubble visible after failure');
    ok(!bubble().classList.contains('downloading'), '2b downloading state cleared');
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/Download failed/.test(txt), '2c failure text', txt);
    ok(/Network error/.test(txt), '2d network reason shown', txt);
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '0%', '2e progress reset', bar.style.width);
    // Unknown code falls back gracefully
    window.showUpdateDownloadFailed('weird-code', '');
    ok(/Download failed/.test(bubble().querySelector('.update-bubble-text').textContent), '2f unknown code fallback');
    // Legacy single-string call still safe
    window.showUpdateDownloadFailed('download failed');
    ok(/Download failed/.test(bubble().querySelector('.update-bubble-text').textContent), '2g legacy call safe');
  }

  console.log('\n[3] after download completes: install bubble like auto path');
  {
    window.showUpdateDownloadProgress(99);
    window.showUpdateBubble();
    const txt = bubble().querySelector('.update-bubble-text').textContent;
    ok(/click to install|点击安装/.test(txt), '3a install prompt text', txt);
    ok(bubble().classList.contains('visible'), '3b bubble visible');
    ok(!bubble().classList.contains('downloading'), '3c downloading state cleared');
    const bar = doc.getElementById('updateProgressBar');
    ok(bar.style.width === '0%', '3d progress reset for next use', bar.style.width);
  }

  console.log('\n[4] dismiss vs progress interplay');
  {
    window.dismissUpdateBubble();
    ok(!bubble().classList.contains('visible'), '4a dismissed hides bubble');
    window.showUpdateBubble(); // dismissed flag blocks it (by design)
    ok(!bubble().classList.contains('visible'), '4b showUpdateBubble stays hidden after dismiss');
    window.showUpdateDownloadProgress(5); // new download resets the flag
    ok(bubble().classList.contains('visible'), '4c progress re-shows bubble after dismiss');
  }

  console.log('\n─────────────────────────────────────');
  console.log('PASSED: ' + passed + '   FAILED: ' + failed);
  if (failures.length) {
    console.log('Failures:');
    failures.forEach(f => console.log('  - ' + f));
    process.exit(1);
  }
  process.exit(0);
})().catch((err) => { console.error('FATAL:', err); process.exit(1); });
