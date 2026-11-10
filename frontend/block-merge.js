// Keeps untouched Markdown byte-for-byte when a document is edited in the rendered page.
//
// The rendered page is converted back to Markdown ("cur"). Converting rewrites things the
// reader never touched (list indentation, `***` rules, reference links, HTML comments, image
// titles...). So we also convert the page as it was *before* editing ("base", made from the
// original text) and compare block by block: a block that is the same in base and cur was not
// edited, so the ORIGINAL text of that block is used; only edited or new blocks come from cur.
// Original blocks that never appeared in base (comments, link definitions...) are kept in place.
(function (root) {
  'use strict';

  const ENTITIES = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'", nbsp: ' ', copy: '©', reg: '®', hellip: '…', mdash: '—', ndash: '–' };
  const MAX_CELLS = 4000000;

  function looseKey(text) {
    let s = String(text).replace(/<!--[\s\S]*?-->/g, '').replace(/<[^>]*>/g, '');
    s = s.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (m, e) => {
      if (e[0] === '#') { const n = e[1] === 'x' || e[1] === 'X' ? parseInt(e.slice(2), 16) : parseInt(e.slice(1), 10); return Number.isFinite(n) ? String.fromCodePoint(n) : ''; }
      return Object.prototype.hasOwnProperty.call(ENTITIES, e.toLowerCase()) ? ENTITIES[e.toLowerCase()] : '';
    });
    const key = s.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, '');
    if (!key && /^[ \t]*([-*_])([ \t]*\1){2,}[ \t]*$/.test(String(text).trim())) return 'HR';
    return key;
  }

  // Split into blocks separated by blank lines (blank lines inside code fences do not split).
  // A block that continues a list or quote (indented, a list marker or ">") joins the previous one.
  function splitBlocks(text) {
    const lines = String(text).split('\n');
    const raw = [];
    let cur = [], fence = null;
    const seps = [];
    const flush = () => { if (cur.length) { raw.push(cur.join('\n')); seps.push(''); cur = []; } };
    for (const line of lines) {
      const f = /^ {0,3}(`{3,}|~{3,})/.exec(line);
      if (fence) {
        cur.push(line);
        if (f && f[1][0] === fence.ch && f[1].length >= fence.len && /^ {0,3}(`+|~+)\s*$/.test(line)) fence = null;
        continue;
      }
      if (/^\s*$/.test(line)) {
        if (cur.length) { flush(); seps[seps.length - 1] = '\n'; } else if (seps.length) { seps[seps.length - 1] += '\n'; }
        continue;
      }
      if (f) fence = { ch: f[1][0], len: f[1].length };
      // Each link / footnote definition is its own block, so one can change without touching its neighbours.
      if (cur.length && /^ {0,3}\[[^\]]+\]:/.test(line) && /^ {0,3}\[[^\]]+\]:/.test(cur[0])) flush();
      cur.push(line);
    }
    flush();
    // seps[i] currently holds the newlines that followed block i, minus the line break ending it.
    const blocks = raw.map((t, i) => ({ text: t, sep: '\n' + (seps[i] || '') }));
    // Join continuation blocks into the previous list/quote block.
    const out = [];
    for (const b of blocks) {
      const prev = out[out.length - 1];
      const isList = /^\s*([-*+]|\d+[.)])\s/.test(b.text);
      const startsQuote = /^\s*>/.test(b.text);
      const startsIndented = /^( {2,}|\t)/.test(b.text);
      const prevList = prev && /^\s*([-*+]|\d+[.)])\s/.test(prev.text);
      const prevQuote = prev && /^\s*>/.test(prev.text);
      if (prev && ((prevList && (isList || startsIndented)) || (prevQuote && startsQuote))) {
        prev.text += prev.sep + b.text;
        prev.sep = b.sep;
      } else out.push({ text: b.text, sep: b.sep });
    }
    out.forEach((b, i) => { b.key = looseKey(b.text); b.idx = i; });
    return out;
  }

  // Longest common subsequence of two arrays under `eq`; returns matched index pairs.
  function lcs(a, b, eq) {
    let s = 0;
    while (s < a.length && s < b.length && eq(a[s], b[s])) s++;
    let ea = a.length, eb = b.length;
    while (ea > s && eb > s && eq(a[ea - 1], b[eb - 1])) { ea--; eb--; }
    const pairs = [];
    for (let i = 0; i < s; i++) pairs.push([i, i]);
    const n = ea - s, m = eb - s;
    if (n && m) {
      if (n * m > MAX_CELLS) return null;
      const w = m + 1, dp = new Uint32Array((n + 1) * w);
      for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--) {
        dp[i * w + j] = eq(a[s + i], b[s + j]) ? dp[(i + 1) * w + j + 1] + 1 : Math.max(dp[(i + 1) * w + j], dp[i * w + j + 1]);
      }
      let i = 0, j = 0;
      while (i < n && j < m) {
        if (eq(a[s + i], b[s + j])) { pairs.push([s + i, s + j]); i++; j++; }
        else if (dp[(i + 1) * w + j] >= dp[i * w + j + 1]) i++;
        else j++;
      }
    }
    for (let k = 0; k < a.length - ea; k++) pairs.push([ea + k, eb + k]);
    return pairs;
  }

  // For each base block, the original block it came from (or -1).
  function alignOriginalToBase(O, B) {
    const pairs = lcs(O, B, (x, y) => x.key === y.key && x.key !== '');
    if (!pairs) return null;
    const partner = new Array(B.length).fill(-1);
    for (const [oi, bi] of pairs) partner[bi] = oi;
    // Between two anchors, pair the remaining blocks in order: they are the same block written differently.
    const anchors = [[-1, -1], ...pairs, [O.length, B.length]];
    for (let k = 0; k + 1 < anchors.length; k++) {
      let oi = anchors[k][0] + 1; const oe = anchors[k + 1][0];
      let bi = anchors[k][1] + 1; const be = anchors[k + 1][1];
      const os = []; for (let i = oi; i < oe; i++) if (O[i].key !== '') os.push(i);
      const bs = []; for (let j = bi; j < be; j++) bs.push(j);
      for (let p = 0; p < Math.min(os.length, bs.length); p++) partner[bs[p]] = os[p];
    }
    // One original block can cover several base blocks (e.g. a run of footnote definitions).
    const members = new Map();
    for (let j = 0; j < B.length; j++) {
      if (partner[j] < 0 && j > 0 && partner[j - 1] >= 0 && B[j].key && O[partner[j - 1]].key.includes(B[j].key)) partner[j] = partner[j - 1];
      if (partner[j] >= 0) { if (!members.has(partner[j])) members.set(partner[j], []); members.get(partner[j]).push(j); }
    }
    // Blocks the converter moved (footnotes go to the end): pair by content, ignoring position.
    const moved = new Map();
    const usedO = new Set(partner.filter(i => i >= 0));
    for (let j = 0; j < B.length; j++) {
      if (partner[j] >= 0 || !B[j].key) continue;
      const oi = O.findIndex((o, idx) => !usedO.has(idx) && o.key && (o.key === B[j].key || o.key.includes(B[j].key)));
      if (oi >= 0) { moved.set(j, oi); usedO.add(oi); }
    }
    return { partner, members, moved };
  }

  const isTable = text => { const lines = text.trim().split('\n'); return lines.length >= 2 && lines.every(l => /^\s*\|/.test(l)) && /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[1]) && /-/.test(lines[1]); };

  // A changed table: keep every row you did not touch exactly as written (spacing, alignment markers),
  // and use the converted text only for rows that changed, were added, or were removed.
  function mergeTable(originalTable, baseTable, curTable) {
    if (!isTable(originalTable) || !isTable(baseTable) || !isTable(curTable)) return null;
    const rows = t => t.trim().split('\n').map(l => l.replace(/\s+$/, ''));
    const O = rows(originalTable), B = rows(baseTable), C = rows(curTable);
    if (O.length !== B.length) return null;
    const pairs = lcs(B, C, (x, y) => x.trim() === y.trim());
    if (!pairs) return null;
    const matched = new Map(pairs.map(([bi, ci]) => [ci, bi]));
    const out = [];
    for (let ci = 0; ci < C.length; ci++) out.push(matched.has(ci) ? O[matched.get(ci)] : C[ci]);
    return out.join('\n');
  }

  function merge(original, base, cur) {
    original = String(original); base = String(base); cur = String(cur);
    const tail = (/\s*$/.exec(original) || [''])[0];
    const O = splitBlocks(original), B = splitBlocks(base), C = splitBlocks(cur);
    const aligned = alignOriginalToBase(O, B);
    const ops = lcs(B, C, (x, y) => x.text.trim() === y.text.trim());
    if (!aligned || !ops) return cur;
    const { partner, members, moved } = aligned;
    const keptB = new Set(ops.map(pair => pair[0]));
    const claimed = new Set(partner.filter(i => i >= 0));
    for (const [bj, oj] of moved) if (!keptB.has(bj)) claimed.add(oj); // a moved block that was edited or deleted is replaced
    const out = []; let nextO = 0;
    // Original blocks that never reached the page (comments, link definitions...) stay where they were.
    const flushTo = limit => { for (; nextO < limit; nextO++) if (!claimed.has(nextO)) out.push(O[nextO]); };
    const fresh = c => out.push({ text: c.text, sep: '\n\n' });
    O.forEach(o => { o.fromOriginal = true; });
    let i = 0, j = 0;
    for (const [pb, pc] of [...ops, [B.length, C.length]]) {
      const edited = [];                                                       // base blocks that changed or were removed
      for (; i < pb; i++) { const oi = partner[i]; edited.push({ b: i, oi }); if (oi >= 0) { flushTo(oi); nextO = oi + 1; } }
      const added = []; for (; j < pc; j++) added.push(j);                       // blocks that are edited or new
      const sameCount = edited.length === added.length;
      added.forEach((cj, k) => {
        const e = sameCount ? edited[k] : null;
        const merged = e && e.oi >= 0 ? mergeTable(O[e.oi].text, B[e.b].text, C[cj].text) : null;
        if (merged !== null) out.push({ text: merged, sep: O[e.oi].sep, idx: O[e.oi].idx, fromOriginal: true }); else fresh(C[cj]);
      });
      if (pb < B.length && moved.has(pb)) { i = pb + 1; j = pc + 1; continue; }  // moved and untouched: stays where it was
      if (pb < B.length) {                                                       // unchanged
        const oi = partner[pb];
        if (oi >= 0) {
          flushTo(oi);
          const group = members.get(oi);
          if (group.every(m => keptB.has(m))) { if (group[0] === pb) out.push(O[oi]); } // untouched: original text, once
          else fresh(C[pc]);                                                            // a sibling was edited: keep this one's text
          nextO = oi + 1;
        } else fresh(C[pc]);
        i = pb + 1; j = pc + 1;
      }
    }
    flushTo(O.length);
    if (!out.length) return cur;
    let text = '';
    out.forEach((blk, k) => {
      if (k === out.length - 1) { text += blk.text; return; }
      // A single line break (between two definitions) is only kept when both were adjacent in the original.
      const adjacent = blk.idx !== undefined && out[k + 1].idx === blk.idx + 1 && out[k + 1].fromOriginal && blk.fromOriginal;
      text += blk.text + (blk.sep === '\n' && !adjacent ? '\n\n' : (blk.sep === '\n' ? '\n' : (blk.sep || '\n\n')));
    });
    return text.replace(/\s+$/, '') + tail;
  }

  // Rendered page -> Markdown, rewriting only what changed. `deps`: turndown(html), normalize(html), renderOriginal(markdown) -> html.
  let baseline = { original: null, markdown: '' };
  function convert(html, original, deps) {
    const keepNbsp = /\u00a0|&nbsp;/.test(original || '');
    const clean = text => keepNbsp ? text : text.replace(/\u00a0/g, ' ');
    const cur = clean(deps.turndown(html));
    if (!original) return cur;
    try {
      if (baseline.original !== original) baseline = { original, markdown: clean(deps.turndown(deps.normalize(deps.renderOriginal(original)))) };
      return merge(original, baseline.markdown, cur);
    } catch (error) { console.warn('block merge skipped', error); return cur; }
  }

  const api = { merge, convert, splitBlocks, looseKey };
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.BlockMerge = api;
})(typeof window !== 'undefined' ? window : globalThis);
