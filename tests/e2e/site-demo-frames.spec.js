// 官网首屏演示用的真实界面素材（窗口 900×680 点，内容区 900×652，大纲展开）：
//   MAKE_SITE_IMAGES=1 npx playwright test tests/e2e/site-demo-frames.spec.js --project=webkit
//   node scripts/site-images-webp.cjs
// 素材：整篇长文的竖向长图、几个滚动位置的大纲、编辑/选中/加粗三帧；位置信息写入 docs/images/_raw/demo-coords.json。
const {test}=require('@playwright/test');
const path=require('path');
const fs=require('fs');
const OUT=path.join(__dirname,'../../docs/images/_raw');
const SIDE=225; // 大纲栏宽度（点）

const FILL={en:[
 'Ship to internal users first, then ten percent of traffic, then everyone.',
 'Keep a one-click rollback, and write down who decides when to use it.'],
 zh:['先给内部用户，再放十分之一流量，最后全量。','始终保留一键回滚，并写清楚由谁来决定何时使用。']};

const DOCS={
 en:`# Evaluating a RAG system

A practical checklist, **from first prototype to production**. Most teams skip the first two steps and pay for it later.[^1]

> [!TIP]
> Keep the set small enough to read in an afternoon. Fifty good questions beat five thousand scraped ones.

## 1. Define what “good” means

Start with the questions users actually ask, then write the answer a domain expert would accept.

- [x] Collect fifty real questions
- [x] Write the expert answers
- [ ] Review them with the team

## 2. Measure retrieval separately

Before judging answers, check whether the right passages were retrieved at all.

| Metric | What it tells you | Healthy range |
|---|---|---|
| Recall@5 | Is the evidence in the top five? | above 0.85 |
| MRR | How high does the first hit rank? | above 0.6 |
| Context precision | How much retrieved text is relevant? | above 0.5 |

## 3. Judge the generated answer

Score faithfulness, completeness and tone. Faithfulness is the share of claims the evidence supports:

$$\\text{faithfulness}=\\frac{|\\text{supported claims}|}{|\\text{claims}|}$$

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

## 4. How the pieces fit together

\`\`\`mermaid
flowchart LR
  Q[Question] --> R[Retrieve]
  R --> G[Generate]
  G --> J{Judge}
  J -->|pass| S[Ship]
  J -->|fail| R
\`\`\`

## 5. Monitor in production

Log queries, retrieved ids and user feedback. Review a random sample weekly, and read every thumbs-down. Stale documents that outrank fresh ones are the most common quiet failure.

- Chunks that split a table from its caption
- Answers that sound confident when retrieval returned nothing

## 6. A sensible rollout

${FILL.en[0]} ${FILL.en[1]}

## 7. Wrapping up

Treat the evaluation set as a product of its own: version it, review it, and let it grow with every incident.

[^1]: Based on common practice across several teams.
`,
 zh:`# 评估一个检索增强系统

从原型到上线的实用清单，**大多数团队会跳过前两步**，之后再付出代价。[^1]

> [!TIP]
> 数据集小到一个下午能读完。五十个好问题胜过五千个随手爬来的。

## 1. 先定义什么叫“好”

从用户真正会问的问题开始，再写出领域专家能接受的答案。

- [x] 收集五十个真实问题
- [x] 写出专家答案
- [ ] 和团队一起评审

## 2. 单独衡量检索

在评判答案之前，先看正确的段落到底有没有被检索到。

| 指标 | 说明什么 | 健康范围 |
|---|---|---|
| Recall@5 | 证据是否在前五条里 | 高于 0.85 |
| MRR | 第一条命中排在多靠前 | 高于 0.6 |
| 上下文精度 | 检索到的文本有多少相关 | 高于 0.5 |

## 3. 评判生成的答案

给忠实度、完整度和语气打分。忠实度就是有证据支持的论断所占的比例：

$$\\text{忠实度}=\\frac{|\\text{有依据的论断}|}{|\\text{全部论断}|}$$

\`\`\`python
def score(answer, evidence):
    claims = split_claims(answer)
    supported = [c for c in claims if entails(evidence, c)]
    return len(supported) / max(1, len(claims))
\`\`\`

## 4. 各个环节怎么衔接

\`\`\`mermaid
flowchart LR
  Q[问题] --> R[检索]
  R --> G[生成]
  G --> J{评判}
  J -->|通过| S[上线]
  J -->|不通过| R
\`\`\`

## 5. 线上监控

记录查询、检索到的文档 id 和用户反馈。每周随机抽查，所有点踩的都要看。旧文档排在新文档前面，是最常见的悄悄失败。

- 把表格和它的标题切开
- 检索为空时答案依然言之凿凿

## 6. 稳妥的上线节奏

${FILL.zh[0]}${FILL.zh[1]}

## 7. 收个尾

把评测集当作一个独立的产品：做版本、做评审，每出一次事故就让它长大一点。

[^1]: 依据多个团队的常见做法。
`};

test.skip(!process.env.MAKE_SITE_IMAGES,'docs image generator');
const coords={};
for(const lang of ['en','zh']){
  for(const scheme of ['light','dark']){
    const suffix=(lang==='zh'?'-zh':'')+(scheme==='dark'?'-dark':'');
    test(`demo frames ${lang} ${scheme}`,async({browser})=>{
      test.setTimeout(90000);
      const context=await browser.newContext({viewport:{width:900,height:652},deviceScaleFactor:2,colorScheme:scheme,locale:lang==='zh'?'zh-CN':'en-US'});
      const page=await context.newPage();
      await page.goto('http://127.0.0.1:29381/');
      await page.waitForFunction(()=>typeof loadContent==='function');
      await page.evaluate(async()=>{window.pywebview={api:{async get_export_css(){return {css:'',version:'2.0.0'}},get_output_settings(){return {}},set_dirty(){return Promise.resolve(true)},store_content(){return Promise.resolve({success:true})},startup_ready(){},get_settings(){return Promise.resolve({})},set_settings(){return Promise.resolve({success:true})}}};await ensureTurndown();});
      const name=lang==='zh'?'检索评估报告.md':'rag-evaluation.md';
      await page.evaluate(([n,m,z])=>loadContent('/Users/me/Documents/'+n,m,720,false,z),[name,DOCS[lang],lang==='zh']);
      await page.waitForSelector('.mermaid-diagram svg',{timeout:20000});
      await page.waitForTimeout(1200);
      await page.addStyleTag({content:'.mode-indicator,.reading-end,.toc-count,.reading-hud,.reading-bar{display:none!important}::-webkit-scrollbar{display:none}'});
      if(await page.locator('#tocSidebar.hidden').count())await page.click('#tocToggle');
      await page.mouse.move(450,640);
      await page.waitForTimeout(500);
      // 1) 整篇竖向长图（右侧内容区）
      const H=await page.evaluate(()=>{const w=document.querySelector('.scroll-wrap');return w.scrollHeight;});
      await page.setViewportSize({width:900,height:H});
      await page.waitForTimeout(700);
      await page.screenshot({path:path.join(OUT,'demo-long'+suffix+'.png'),clip:{x:SIDE,y:0,width:900-SIDE,height:H}});
      await page.setViewportSize({width:900,height:652});
      await page.waitForTimeout(700);
      // 2) 各章节位置的大纲状态
      const heads=await page.evaluate(()=>{const w=document.querySelector('.scroll-wrap');const wr=w.getBoundingClientRect();return [...document.querySelectorAll('#content > h2')].map(h=>({top:h.getBoundingClientRect().top-wr.top+w.scrollTop,text:h.textContent.trim()}));});
      const stops=[0,...heads.slice(0,-1).map(h=>Math.max(0,Math.round(h.top-90)))];
      // 编辑落点：第 5 节的正文段
      const target=await page.evaluate(()=>{const hs=[...document.querySelectorAll('#content > h2')];const h=hs[5];const p=h.nextElementSibling;p.id='demo-target';const w=document.querySelector('.scroll-wrap');const wr=w.getBoundingClientRect();return {top:p.getBoundingClientRect().top-wr.top+w.scrollTop,h:p.getBoundingClientRect().height,maxScroll:w.scrollHeight-w.clientHeight};});
      const END=Math.min(target.maxScroll,Math.round(target.top-300));
      const sideStops=[...stops.filter(s=>s<END),END];
      for(let i=0;i<sideStops.length;i++){
        await page.evaluate(s=>{document.querySelector('.scroll-wrap').scrollTop=s;},sideStops[i]);
        await page.waitForTimeout(450);
        await page.screenshot({path:path.join(OUT,'demo-side-'+i+suffix+'.png'),clip:{x:0,y:0,width:SIDE,height:652}});
      }
      // 3) 停在 END：点击、选中、加粗三帧（完整窗口）
      await page.evaluate(s=>{document.querySelector('.scroll-wrap').scrollTop=s;},END);
      await page.waitForTimeout(500);
      const last=page.locator('#demo-target');
      const box=await last.boundingBox();
      await page.mouse.click(box.x+60,box.y+14);
      await page.waitForTimeout(500);
      await page.screenshot({path:path.join(OUT,'demo-edit'+suffix+'.png')});
      await page.mouse.click(box.x+60,box.y+14,{clickCount:3});
      await page.waitForTimeout(400);
      await page.screenshot({path:path.join(OUT,'demo-select'+suffix+'.png')});
      const labels=await page.$$eval('.edit-bar button',bs=>bs.map(b=>b.getAttribute('aria-label')));
      const bb=await page.locator('.edit-bar button').nth(labels.findIndex(l=>/bold|加粗/i.test(l||''))).boundingBox();
      await page.mouse.click(bb.x+bb.width/2,bb.y+bb.height/2);
      await page.waitForTimeout(450);
      await page.screenshot({path:path.join(OUT,'demo-bold'+suffix+'.png')});
      if(scheme==='light'){
        coords[lang]={docHeight:H,end:END,stops:sideStops,heads:heads.map(h=>Math.round(h.top)),text:{x:box.x+60,y:box.y+14},bold:{x:bb.x+bb.width/2,y:bb.y+bb.height/2}};
      }
      await context.close();
    });
  }
}
test.afterAll(()=>{fs.writeFileSync(path.join(OUT,'demo-coords.json'),JSON.stringify(coords,null,1));});
