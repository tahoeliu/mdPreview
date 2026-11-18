const assert = require('node:assert/strict');
const fs = require('node:fs');
const { JSDOM } = require('jsdom');

(async () => {
  const dom = new JSDOM('<div id="updateBubble"><div class="update-bubble-body"><span class="update-bubble-text"></span></div></div><div id="page"><div id="content">Long document</div></div><div class="scroll-wrap"></div>', { runScripts: 'outside-only', pretendToBeVisual: true });
  const w = dom.window;
  w.eval(fs.readFileSync('frontend/updates.js', 'utf8'));
  w.eval(fs.readFileSync('frontend/reading-progress.js', 'utf8'));
  const bubble = w.document.getElementById('updateBubble');
  const feedback = w.UpdateFeedback.create({ document: w.document, t: en => en, Bridge: { ready: () => true, call: async () => ({ phase: 'idle', automatic: false, detail: 'up to date' }) } });
  await feedback.refreshUpdateState();
  assert.equal(bubble.classList.contains('visible'), false, 'historical check stays hidden in a new window');
  feedback.updateFeedbackState({ phase: 'checking', automatic: false });
  feedback.updateFeedbackState({ phase: 'idle', automatic: false, detail: 'up to date' });
  assert.equal(bubble.classList.contains('visible'), true, 'a new manual check remains visible');
  const scroller = w.document.querySelector('.scroll-wrap');
  Object.defineProperties(scroller, { scrollHeight: { value: 4000 }, clientHeight: { value: 500 } });
  scroller.scrollTop = 500;
  scroller.dispatchEvent(new w.Event('scroll'));
  w.dispatchEvent(new w.Event('resize'));
  await new Promise(resolve => w.requestAnimationFrame(resolve));
  assert.equal(w.document.querySelector('.read-hud'), null, 'reading HUD is absent');
  assert.equal(w.document.querySelector('.read-progress > div').style.transform, 'scaleX(0.1429)');
  dom.window.close();
  console.log('window feedback: ok');
})().catch(error => { console.error(error); process.exitCode = 1; });
