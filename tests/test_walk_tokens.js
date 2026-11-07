// 线性 walkTokens 必须与 marked 12 原实现访问相同的 token、相同的顺序（含回调改写 type 的情况）。
const assert = require('node:assert/strict');
const { createApp } = require('./helpers.js');
let assertions = 0;
function same(actual, expected, message) { assert.deepEqual(actual, expected, message); assertions++; }

const CORPUS = {
  plain: '# 标题\n\n段落 **粗** 与 *斜* `代码`\n\n## 二级\n\n文字',
  lists: '- a\n  - b\n    - c\n- d\n\n1. one\n2. two\n   - nested **bold**\n\n- [ ] task\n- [x] done',
  table: '| A | **B** |\n| - | - |\n| `x` | [l](https://e.com) |\n| 1 | 2 |',
  quote: '> 引用 **粗**\n>\n> > 嵌套引用\n\n> [!NOTE]\n> 提示 *块*\n\n> [!WARNING]\n> 警告',
  footnote: '正文[^1] 和 [^note]\n\n[^1]: 脚注一\n[^note]: 脚注二 **粗**',
  html: '<div class="x">hi <b>there</b></div>\n\n段落\n\n<span>inline</span>',
  math: '行内 $a+b$ 和 \\(c\\)\n\n$$\nx^2\n$$\n\n\\[\ny\n\\]',
  code: '```js\nconst x = 1;\n```\n\n    indented code\n\n---\n\n***',
  mixed: '# T\n\n- a\n\n  > quote in list\n\n| h |\n| - |\n| - [ ] not task |\n\n![img](a.png)\n\n[^f]: def',
};

(async () => {
  const app = await createApp();
  const { w } = app;
  try {
    const marked = w.marked;
    const linear = w.MarkdownPipeline.linearWalkTokens;
    assert.equal(typeof linear, 'function', 'linearWalkTokens 已导出');
    assertions++;

    for (const [name, markdown] of Object.entries(CORPUS)) {
      const visit = (walker) => {
        const instance = new marked.Marked({ gfm: true, breaks: true });
        const seen = [];
        const tokens = instance.lexer(markdown);
        walker.call(instance, tokens, (token) => { seen.push(token.type + ':' + (token.raw || '').length); });
        return seen;
      };
      const reference = visit(marked.Marked.prototype.walkTokens);
      const actual = visit(linear);
      assert.ok(reference.length > 0, name + ' 有 token');
      assertions++;
      same(actual, reference, '访问序列一致：' + name);
    }

    // 回调改写 type（blockquote → alert）之后，必须按新的 type/子 token 继续深入。
    const rewrite = (walker) => {
      const instance = new marked.Marked({ gfm: true });
      const tokens = instance.lexer('> [!NOTE]\n> **粗** 文字\n\n> 普通引用');
      const seen = [];
      walker.call(instance, tokens, (token) => {
        if (token.type === 'blockquote' && /^\[!NOTE\]/.test(token.text)) {
          token.type = 'alert';
          token.tokens = instance.lexer('改写后的 *子节点*');
        }
        seen.push(token.type);
      });
      return seen;
    };
    same(rewrite(linear), rewrite(marked.Marked.prototype.walkTokens), '回调改写 type 后的遍历一致');

    // 回调返回值：数组按一层展开，undefined 被忽略（与 concat 语义一致）。
    const returns = (walker) => {
      const instance = new marked.Marked({ gfm: true });
      return walker.call(instance, instance.lexer('# a\n\nb'), (token) => (token.type === 'heading' ? [1, 2] : token.type === 'paragraph' ? 3 : undefined));
    };
    same(returns(linear), returns(marked.Marked.prototype.walkTokens), '返回值收集一致');

    // 复杂度：数万个顶层 token 必须在远小于二次实现的时间内完成。
    const big = Array.from({ length: 30000 }, (_, i) => '段落 ' + i + ' **粗**').join('\n\n');
    const instance = new marked.Marked({ gfm: true });
    const tokens = instance.lexer(big);
    let count = 0;
    const begin = Date.now();
    linear.call(instance, tokens, () => { count++; });
    const elapsed = Date.now() - begin;
    assert.ok(count > 60000, 'token 数量足够多：' + count);
    assert.ok(elapsed < 1500, '线性遍历 ' + count + ' 个 token 用时 ' + elapsed + 'ms');
    assertions += 2;

    // 管线整体：大文档解析必须保持近似线性（旧实现 800KB 约 17 秒）。
    const sample = Array.from({ length: 4000 }, (_, i) => '## 节 ' + i + '\n\n正文 **粗** 与 `code`\n\n- a\n- b\n').join('\n');
    const start = Date.now();
    const html = w.MarkdownPipeline.parse(sample);
    const parseMs = Date.now() - start;
    assert.ok(html.includes('<h2'), '解析产出标题');
    assert.ok(parseMs < 20000, '大文档解析用时 ' + parseMs + 'ms');
    assertions += 2;

    console.log('walkTokens 一致性与复杂度检查通过：' + assertions + ' 项断言（30000 段落遍历 ' + elapsed + 'ms）');
  } finally {
    w.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
