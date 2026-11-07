// CJK strong-emphasis compatibility suite (development-only; not shipped).
// Verifies that `**标题：**正文` (closing ** between CJK punctuation and a Han
// character) renders as <strong> without altering the source document, and
// that standard CommonMark emphasis behavior is unchanged.
const assert = require('node:assert/strict');
const { createApp } = require('./helpers.js');
let assertions = 0;
function check(value, message) { assert.ok(value, message); assertions++; }

const KYA_LINES = [
  '**身份对象与信任关系：**区分用户、服务主体、智能体、执行实例、委托方与被委托方。',
  '**身份与执行实例绑定：**规定身份材料、密钥及版本关联；核验用户授权是否对应预期实例。',
  '**委托关系与权限传递：**规定父子委托、跨平台核验及委托不扩权规则。',
  '**状态与生命周期：**规定身份状态、密钥轮换、版本变化、撤销与恢复的关联处理。',
  '**接口及符合性：**规定身份和委托证明的最低数据与验证方法。'
];

(async () => {
  const app = await createApp(); const { w } = app;
  const parse = (md) => w.MarkdownPipeline.parse(md);
  try {
    // ── A. Original failure cases from the reported document ───────────────
    for (const line of KYA_LINES) {
      const html = parse(line);
      check(/<strong>[^<]*：[^<]*<\/strong>/.test(html), 'KYA line bolds: ' + line.slice(0, 12));
      check(!html.includes('**'), 'No literal ** remains: ' + line.slice(0, 12));
    }
    await app.load(KYA_LINES.join('\n\n'));
    check(w.document.querySelectorAll('#content strong').length === 5, 'All five KYA items render strong');

    // ── B. Punctuation coverage and boundaries ────────────────────────────
    for (const p of ['：', '，', '。', '；', '！', '？', '）', '”', '’']) {
      check(parse('**甲' + p + '**乙').includes('<strong>甲' + p + '</strong>乙'), 'Boundary punctuation ' + p);
    }
    check(parse('**标题：** 正文').includes('<strong>标题：</strong> 正文'), 'Spaced closer still native');
    check(parse('**标题**：正文').includes('<strong>标题</strong>：正文'), 'Colon outside still native');
    check(parse('**标题：**').includes('<strong>标题：</strong>'), 'Closer at line end unaffected');
    check(parse('**a:**b').includes('**a:**b'), 'Latin-only punctuation boundary stays native');
    check(parse('**甲:**乙').includes('<strong>甲:</strong>乙'), 'ASCII punctuation before Han supported');
    check(parse('**标题：x').includes('**标题：x'), 'Missing closer stays literal');

    // ── C. Negative cases: must NOT bold ───────────────────────────────────
    check(parse('***标题：***正文').includes('***标题：***'), 'Triple stars untouched');
    check(parse('**甲：****乙：**丙').includes('**甲：**'), 'Closer followed by ** not hijacked');
    check(parse('**甲：\\**乙').includes('**'), 'Escaped star cannot close');
    check(parse('`x` **甲：** `**乙**`').includes('`**乙**`') || parse('`x` **甲：** `**乙**`').includes('<code>**乙**</code>'), 'Inline code after bold keeps code literal');

    // ── D. Fenced code and indented content are never compat-parsed ───────
    const fenced = parse('```text\n**标题：**正文\n```');
    check(fenced.includes('**标题：**正文'), 'Fence keeps stars literal');
    check(!fenced.includes('<strong>'), 'Fence never strong');

    // ── E. Masking: code spans / links / tags inside bold region ──────────
    check(parse('**`代码：**正文`：**正文').includes('<strong><code>代码：**正文</code>：</strong>正文'), 'Code span masked inside bold');
    check(parse('**见[链接](https://example.com)：**正文').includes('<strong>见<a href="https://example.com">链接</a>：</strong>正文'), 'Inline link inside bold');

    // ── F. Mixed with standard emphasis ───────────────────────────────────
    check(parse('**甲：**正文 **普通**结尾').includes('<strong>甲：</strong>正文 <strong>普通</strong>结尾'), 'Compat + native strong coexist');
    check(parse('**bold** and *em* and `x**y**z`').includes('<strong>bold</strong>'), 'English emphasis unchanged');
    check(parse('snake_case_name').includes('snake_case_name'), 'Underscore words unchanged');
    check(parse('__标题：__正文').includes('__标题：__正文'), 'Underscore strong stays native');
    check(parse('**嵌套 *斜体* 内容：**正文').includes('<em>斜体</em>'), 'Nested em inside compat strong');

    // ── G. Structural contexts ─────────────────────────────────────────────
    check(parse('- **项目：**说明').includes('<strong>项目：</strong>'), 'List item bold');
    check(parse('| A |\n| --- |\n| **单元：**值 |').includes('<strong>单元：</strong>'), 'Table cell bold');
    check(parse('注[^n]\n\n[^n]: **脚注：**内容').includes('<strong>脚注：</strong>'), 'Footnote definition bold');
    check(parse('## **标题：**正文').includes('<strong>标题：</strong>'), 'Heading bold');
    check(parse('> **引用：**正文').includes('<strong>引用：</strong>'), 'Blockquote bold');

    // ── H. Round trip: render → edit → markdown source preserved ──────────
    await app.load('**标题：**正文');
    const content = w.document.getElementById('content');
    content.querySelector('p').appendChild(w.document.createTextNode('！'));
    content.dispatchEvent(new w.Event('input'));
    check(w.getCurrentMarkdown().includes('**标题：**正文'), 'Round trip preserves CJK strong source');

    await app.load(KYA_LINES.join('\n\n'));
    content.querySelector('p').appendChild(w.document.createTextNode('。'));
    content.dispatchEvent(new w.Event('input'));
    const round = w.getCurrentMarkdown();
    for (const line of KYA_LINES) check(round.includes(line), 'KYA round trip: ' + line.slice(0, 12));

    // ── I. Source-mode highlight does not crash on compat syntax ──────────
    await w.toggleView();
    app.input('**标题：**正文');
    await w.toggleView();
    check(w.document.querySelector('#content strong') !== null, 'Source/render toggle keeps bold');

    console.log('CJK strong: ' + assertions + ' assertions PASS');
  } finally { app.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
