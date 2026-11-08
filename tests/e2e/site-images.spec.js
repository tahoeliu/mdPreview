// 生成官网截图：MAKE_SITE_IMAGES=1 npx playwright test tests/e2e/site-images.spec.js --project=webkit
const {test}=require('@playwright/test');
const path=require('path');
const OUT=path.join(__dirname,'../../docs/images');
const DOCS={
 en:{name:'rag-evaluation.md',md:`# How to evaluate a retrieval-augmented system

A practical checklist, from first prototype to production. Most teams skip the first two steps and pay for it later.

## 1. Define what “good” means

Start with the questions users actually ask. Collect fifty real ones, then write the answer a domain expert would accept. Without this set, every later number is noise.

> [!TIP]
> Keep the set small enough to read in an afternoon. Fifty good questions beat five thousand scraped ones.

## 2. Measure retrieval separately

Before judging answers, check whether the right passages were retrieved at all.

| Metric | What it tells you | Healthy range |
|---|---|---|
| Recall@5 | Is the evidence in the top five? | above 0.85 |
| MRR | How high does the first hit rank? | above 0.6 |
| Context precision | How much retrieved text is relevant? | above 0.5 |

## 3. Judge the generated answer

Score faithfulness (is every claim supported?), completeness, and tone. Use a rubric, not a vibe.

### Automated judges

LLM judges are cheap and consistent, but they drift. Calibrate them against twenty human-labelled examples every release.

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

## 4. Watch for regressions

Run the full set on every change to prompts, chunking, or the embedding model. Store results next to the commit.

## 5. Monitor in production

Log queries, retrieved ids and user feedback. Review a random sample weekly, and every thumbs-down.

## 6. Common failure modes

- Chunks that split a table from its caption
- Stale documents outranking fresh ones
- Answers that sound confident when retrieval returned nothing
- Prompts that quietly grew to contain contradictory rules

## 7. A sensible rollout

Ship to internal users first, then ten percent of traffic, then everyone. Keep a one-click rollback.
`},
 zh:{name:'rag-evaluation.md',md:`# 如何评估一个检索增强系统

从原型到上线的实用清单。大多数团队会跳过前两步，之后再付出代价。

## 1. 先定义什么叫“好”

从用户真正会问的问题开始。收集五十个真实问题，再写出领域专家能接受的答案。没有这套数据，后面的每个数字都只是噪音。

> [!TIP]
> 数据集小到一个下午能读完。五十个好问题胜过五千个随手爬来的。

## 2. 单独衡量检索

在评判答案之前，先看正确的段落到底有没有被检索到。

| 指标 | 说明什么 | 健康范围 |
|---|---|---|
| Recall@5 | 证据是否在前五条里 | 高于 0.85 |
| MRR | 第一条命中排在多靠前 | 高于 0.6 |
| 上下文精度 | 检索到的文本有多少相关 | 高于 0.5 |

## 3. 评判生成的答案

给忠实度（每个论断是否有依据）、完整度和语气打分。用评分细则，不要凭感觉。

### 自动评审

LLM 评审又便宜又稳定，但会漂移。每次发版都用二十条人工标注的样例校准一次。

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

## 4. 盯住回归

提示词、切块方式或向量模型每次改动，都完整跑一遍。把结果和提交存在一起。

## 5. 线上监控

记录查询、检索到的文档 id 和用户反馈。每周随机抽查，所有点踩的都要看。

## 6. 常见失败模式

- 把表格和它的标题切开
- 旧文档排在新文档前面
- 检索为空时答案依然言之凿凿
- 提示词悄悄长出了互相矛盾的规则

## 7. 稳妥的上线节奏

先给内部用户，再放十分之一流量，最后全量。始终保留一键回滚。
`}};
test.skip(!process.env.MAKE_SITE_IMAGES,'docs image generator');
for(const lang of ['en','zh']){
  const suffix=lang==='zh'?'-zh':'';
  test('site images '+lang,async({browser})=>{
    for(const scheme of ['light']){
      const context=await browser.newContext({viewport:{width:1200,height:750},deviceScaleFactor:2,colorScheme:scheme,locale:lang==='zh'?'zh-CN':'en-US'});
      const page=await context.newPage();
      await page.goto('http://127.0.0.1:29381/');
      await page.waitForFunction(()=>typeof loadContent==='function');
      await page.evaluate(async()=>{window.pywebview={api:{async get_export_css(){return {css:'',version:'2.0.0'}},get_output_settings(){return {}},set_dirty(){return Promise.resolve(true)},store_content(){return Promise.resolve({success:true})},startup_ready(){},get_settings(){return Promise.resolve({})},set_settings(){return Promise.resolve({success:true})}}};await ensureTurndown();});
      const d=DOCS[lang];
      await page.evaluate(([n,m,z])=>loadContent('/Users/me/Documents/'+n,m,720,false,z),[d.name,d.md,lang==='zh']);
      await page.waitForTimeout(600);
      // 阅读：展开大纲，滚动到中段，显示进度
      await page.addStyleTag({content:'.mode-indicator{display:none!important}'});
      if(await page.locator('#tocSidebar.hidden').count())await page.click('#tocToggle');
      await page.waitForTimeout(300);
      await page.evaluate(()=>{const w=document.querySelector('.scroll-wrap');w.scrollTop=Math.max(0,w.scrollHeight*0.18);});
      await page.waitForTimeout(500);
      await page.screenshot({path:path.join(OUT,'hero-reading'+suffix+'.png')});
      // 跳转标题
      await page.evaluate(()=>openGoToHeading());
      await page.keyboard.type(lang==='zh'?'评':'eval');
      await page.waitForTimeout(300);
      await page.screenshot({path:path.join(OUT,'hero-goto'+suffix+'.png')});
      await page.keyboard.press('Escape');
      // 编辑：点击正文，选中一段文字
      await page.evaluate(()=>{const w=document.querySelector('.scroll-wrap');w.scrollTop=0;});
      await page.click('#content p');
      await page.evaluate(()=>{const p=document.querySelector('#content p');const r=document.createRange();r.setStart(p.firstChild,2);r.setEnd(p.firstChild,Math.min(14,p.firstChild.length));const s=getSelection();s.removeAllRanges();s.addRange(r);});
      await page.waitForTimeout(400);
      await page.screenshot({path:path.join(OUT,'edit-bar'+suffix+'.png')});
      await context.close();
    }
  });
}
