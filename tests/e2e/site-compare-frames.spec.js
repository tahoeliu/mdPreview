// 官网“通用编辑器 vs mdPreview”对比图右侧的 mdPreview 窗口素材（新版示例文档：长大纲、表格、流程图只露一角）：
//   MAKE_SITE_IMAGES=1 npx playwright test tests/e2e/site-compare-frames.spec.js --project=webkit
//   然后 node scripts/site-images-webp.cjs（只会转换 _raw 里的 PNG）
const {test}=require('@playwright/test');
const path=require('path');
const OUT=path.join(__dirname,'../../docs/images/_raw');
const SIDE=225;
const DOCS={
 en:`# Evaluating a RAG System

A practical guide, **from first prototype to production**.

## 1. Define what “good” means

> **Tip:** Keep the question set small enough to read in an afternoon.

## 2. Measure retrieval separately

| Metric | What it tells you | Healthy range |
|---|---|---|
| Recall@5 | Is the evidence in the top five? | above 0.85 |
| MRR | How high does the first hit rank? | above 0.6 |
| Context precision | How much retrieved text is relevant? | above 0.5 |

\`\`\`mermaid
flowchart TD
    Q[User question] --> R[Rewrite and embed the query]
    R --> S[Vector search]
    S --> K[Re-rank the top 20]
    K --> C{Enough evidence?}
    C -- Yes --> G[Generate a cited answer]
    C -- No --> N[Say it does not know]
    G --> J[Judge faithfulness]
    N --> J
    J --> L[(Evaluation log)]
    L --> D[Weekly review]
    D --> Q
\`\`\`

### The score we track

Faithfulness is the share of claims in an answer that the evidence supports:

$$
\\text{Faithfulness} = \\frac{\\lvert \\text{supported claims} \\rvert}{\\lvert \\text{all claims} \\rvert}
$$

## 3. Judge the generated answer

Score faithfulness, completeness and tone. Use a rubric, not a vibe.

### Automated judges

LLM judges are cheap and consistent, but they drift. Calibrate them against twenty human-labelled examples every release.

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

### Human review

- [x] Sample thirty answers every week
- [x] Review every thumbs-down within a day
- [ ] Add each new failure to the regression set

## 4. Watch for regressions

Run the full set on every change to prompts, chunking or the embedding model. Read the diff of answers, not only the score.

## 5. Monitor in production

Log queries, retrieved ids and user feedback. Review a random sample weekly.

## 6. Common failure modes

- Chunks that split a table from its caption
- Stale documents outranking fresh ones
- Answers that sound confident when retrieval returned nothing

### Prompt drift

Prompts that quietly grew to contain contradictory rules.

### Embedding drift

A new embedding model changes every neighbour list; re-index before you compare.

## 7. A sensible rollout

Ship to internal users first, then ten percent of traffic, then everyone. Keep a one-click rollback.

## 8. Cost and latency budget

Decide the budget before tuning. A slower, better answer is only better if users wait for it.

## 9. Privacy and compliance

Redact personal data before logging, and set a retention period for stored queries.

## 10. Summary and next steps

Evaluate retrieval and generation separately, automate what is cheap, and keep humans on the hard cases.

## 11. References

- Es et al., *RAGAS: Automated Evaluation of Retrieval Augmented Generation*
- Zheng et al., *Judging LLM-as-a-Judge with MT-Bench*
`,
 zh:`# 评估一个 RAG 系统

一份从原型到上线的实用指南，**大多数团队会跳过前两步**。

## 1. 先定义什么叫“好”

> **提示：** 问题集小到一个下午能读完就好。

## 2. 单独衡量检索

| 指标 | 说明什么 | 健康范围 |
|---|---|---|
| Recall@5 | 证据是否在前五条里 | 高于 0.85 |
| MRR | 第一条命中排在多靠前 | 高于 0.6 |
| 上下文精度 | 检索到的文本有多少相关 | 高于 0.5 |

\`\`\`mermaid
flowchart TD
    Q[用户提问] --> R[改写并向量化问题]
    R --> S[向量检索]
    S --> K[对前 20 条重排]
    K --> C{证据足够吗？}
    C -- 是 --> G[生成带引用的答案]
    C -- 否 --> N[坦率说不知道]
    G --> J[评判忠实度]
    N --> J
    J --> L[(评估日志)]
    L --> D[每周复盘]
    D --> Q
\`\`\`

### 我们追踪的分数

忠实度是答案中有证据支持的论断所占的比例：

$$
\\text{忠实度} = \\frac{\\lvert \\text{有依据的论断} \\rvert}{\\lvert \\text{全部论断} \\rvert}
$$

## 3. 评判生成的答案

给忠实度、完整度和语气打分。用评分细则，不要凭感觉。

### 自动评审

LLM 评审又便宜又稳定，但会漂移。每次发版都用二十条人工标注的样例校准一次。

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

### 人工抽查

- [x] 每周抽查三十条答案
- [x] 一天内看完所有点踩的反馈
- [ ] 把每个新的失败案例加入回归集

## 4. 盯住回归

提示词、切块方式或向量模型每次改动，都完整跑一遍。看答案的差异，而不只是分数。

## 5. 线上监控

记录查询、检索到的文档 id 和用户反馈，每周随机抽查。

## 6. 常见失败模式

- 把表格和它的标题切开
- 旧文档排在新文档前面
- 检索为空时答案依然言之凿凿

### 提示词漂移

提示词悄悄长出了互相矛盾的规则。

### 向量模型漂移

换向量模型会改变每个近邻列表，对比之前先重建索引。

## 7. 稳妥的上线节奏

先给内部用户，再放十分之一流量，最后全量。始终保留一键回滚。

## 8. 成本与延迟预算

调优之前先定预算。更慢但更好的答案，只有用户愿意等才算更好。

## 9. 隐私与合规

记录日志前先脱敏个人信息，并为存储的查询设定保留期限。

## 10. 总结与下一步

分开评估检索和生成，把便宜的环节自动化，把人留给疑难案例。

## 11. 参考资料

- Es 等，《RAGAS：检索增强生成的自动评估》
- Zheng 等，《用 MT-Bench 评判 LLM 评审》
`};
test.skip(!process.env.MAKE_SITE_IMAGES,'docs image generator');
for(const lang of ['en','zh']){
  for(const scheme of ['light','dark']){
    const suffix=(lang==='zh'?'-zh':'')+(scheme==='dark'?'-dark':'');
    test(`compare frames ${lang} ${scheme}`,async({browser})=>{
      test.setTimeout(90000);
      const context=await browser.newContext({viewport:{width:900,height:652},deviceScaleFactor:2,colorScheme:scheme,locale:lang==='zh'?'zh-CN':'en-US'});
      const page=await context.newPage();
      await page.goto('http://127.0.0.1:29381/');
      await page.waitForFunction(()=>typeof loadContent==='function');
      await page.evaluate(async()=>{window.pywebview={api:{async get_export_css(){return {css:'',version:'2.0.3'}},get_output_settings(){return {}},set_dirty(){return Promise.resolve(true)},store_content(){return Promise.resolve({success:true})},startup_ready(){},get_settings(){return Promise.resolve({})},set_settings(){return Promise.resolve({success:true})}}};await ensureTurndown();});
      const name=lang==='zh'?'检索评估报告.md':'rag-evaluation.md';
      await page.evaluate(([n,m,z])=>loadContent('/Users/me/Documents/'+n,m,720,false,z),[name,DOCS[lang],lang==='zh']);
      await page.waitForSelector('.mermaid-diagram svg',{timeout:20000});
      await page.evaluate(()=>{contentFontSize=15;applyFontSize();});
      await page.waitForTimeout(1200);
      await page.addStyleTag({content:'.mode-indicator,.reading-end,.toc-count,.reading-hud,.reading-bar{display:none!important}::-webkit-scrollbar{display:none}'});
      if(await page.locator('#tocSidebar.hidden').count())await page.click('#tocToggle');
      await page.evaluate(()=>{document.querySelector('.scroll-wrap').scrollTop=0;});
      await page.mouse.move(450,640);
      await page.waitForTimeout(700);
      await page.screenshot({path:path.join(OUT,'demo-cmplong'+suffix+'.png'),clip:{x:SIDE,y:0,width:900-SIDE,height:652}});
      await page.screenshot({path:path.join(OUT,'demo-cmpside'+suffix+'.png'),clip:{x:0,y:0,width:SIDE,height:652}});
      await context.close();
    });
  }
}
