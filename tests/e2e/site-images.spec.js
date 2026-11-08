// 生成官网截图（原始 PNG，写入 docs/images/_raw）：
//   MAKE_SITE_IMAGES=1 npx playwright test tests/e2e/site-images.spec.js --project=webkit
// 之后用 node scripts/site-images-webp.cjs 转成体积更小的 WebP。
const {test}=require('@playwright/test');
const path=require('path');
const fs=require('fs');
const OUT=path.join(__dirname,'../../docs/images/_raw');

// 正文长度要足以触发“还剩 N 分钟”；末尾的问题清单只负责把文档撑长。
function questionBank(lang){
  const topics=lang==='zh'
    ?['退款政策','账号注销','发票抬头','物流延迟','会员续费','隐私设置','密码找回','优惠叠加','门店自提','售后换货']
    :['refund policy','account deletion','invoice details','delayed shipping','plan renewal','privacy settings','password recovery','stacked discounts','store pickup','exchanges'];
  const stems=lang==='zh'
    ?['用户问到“{t}”时，答案是否引用了最新的条款？','关于“{t}”，检索到的段落是否包含具体步骤？','“{t}”相关的回答里，有没有出现过期的信息？','当“{t}”没有明确答案时，系统是否会坦率承认？']
    :['When asked about {t}, does the answer cite the latest wording?','For {t}, do the retrieved passages contain concrete steps?','Does any answer about {t} rely on information that has expired?','When {t} has no clear answer, does the system say so plainly?'];
  const lines=[];
  for(const s of stems)for(const t of topics)lines.push('- '+s.replace('{t}',t));
  return lines.join('\n');
}

const DOCS={
 en:{name:'rag-evaluation.md',md:`# Evaluating a RAG system

A practical checklist, **from first prototype to production**. Most teams skip the first two steps and pay for it later.

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

Run the full set on every change to prompts, chunking, or the embedding model. Store results next to the commit, and read the diff of answers, not only the score.

Keep a short list of “never again” questions, the ones that once embarrassed the team. They run first, every time.

## 5. Monitor in production

Log queries, retrieved ids and user feedback. Review a random sample weekly, and every thumbs-down.

## 6. Common failure modes

- Chunks that split a table from its caption
- Stale documents outranking fresh ones
- Answers that sound confident when retrieval returned nothing
- Prompts that quietly grew to contain contradictory rules

## 7. A sensible rollout

Ship to internal users first, then ten percent of traffic, then everyone. Keep a one-click rollback.

## 8. Question bank

${questionBank('en')}
`,
  // 并排对比用的短文档：左边展示这段原文，右边展示渲染结果
  after:`# Evaluating a RAG system

A practical checklist, **from first prototype to production**. Most teams skip the first two steps.

## 1. Define what “good” means

> [!TIP]
> Keep the set small enough to read in an afternoon.

| Metric | Healthy range |
|---|---|
| Recall@5 | above 0.85 |
| MRR | above 0.6 |

- Collect fifty real questions
- Write the answer an expert would accept
`,
  goto:'reg',editName:'Evaluating a RAG system'},
 zh:{name:'rag-evaluation.md',md:`# 评估一个检索增强系统

从原型到上线的实用清单，**大多数团队会跳过前两步**，之后再付出代价。

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

提示词、切块方式或向量模型每次改动，都完整跑一遍。把结果和提交存在一起，并且看答案的差异，而不只是分数。

留一份“绝不再犯”的问题清单，就是那些曾经让团队难堪的问题，每次最先跑它们。

## 5. 线上监控

记录查询、检索到的文档 id 和用户反馈。每周随机抽查，所有点踩的都要看。

## 6. 常见失败模式

- 把表格和它的标题切开
- 旧文档排在新文档前面
- 检索为空时答案依然言之凿凿
- 提示词悄悄长出了互相矛盾的规则

## 7. 稳妥的上线节奏

先给内部用户，再放十分之一流量，最后全量。始终保留一键回滚。

## 8. 问题清单

${questionBank('zh')}
`,
  after:`# 评估一个检索增强系统

从原型到上线的实用清单，**大多数团队会跳过前两步**。

## 1. 先定义什么叫“好”

> [!TIP]
> 数据集小到一个下午能读完。

| 指标 | 健康范围 |
|---|---|
| Recall@5 | 高于 0.85 |
| MRR | 高于 0.6 |

- 收集五十个真实问题
- 写出专家能接受的答案
`,
  goto:'回归',editName:'评估一个检索增强系统'}};

test.skip(!process.env.MAKE_SITE_IMAGES,'docs image generator');

async function openDoc(browser,lang,scheme,viewport,md,name){
  const context=await browser.newContext({viewport,deviceScaleFactor:2,colorScheme:scheme,locale:lang==='zh'?'zh-CN':'en-US'});
  const page=await context.newPage();
  await page.goto('http://127.0.0.1:29381/');
  await page.waitForFunction(()=>typeof loadContent==='function');
  await page.evaluate(async()=>{window.pywebview={api:{async get_export_css(){return {css:'',version:'2.0.0'}},get_output_settings(){return {}},set_dirty(){return Promise.resolve(true)},store_content(){return Promise.resolve({success:true})},startup_ready(){},get_settings(){return Promise.resolve({})},set_settings(){return Promise.resolve({success:true})}}};await ensureTurndown();});
  await page.evaluate(([n,m,z])=>loadContent('/Users/me/Documents/'+n,m,720,false,z),[name,md,lang==='zh']);
  await page.waitForTimeout(700);
  await page.addStyleTag({content:'.mode-indicator{display:none!important}'});
  return {context,page};
}
async function showOutline(page){
  if(await page.locator('#tocSidebar.hidden').count())await page.click('#tocToggle');
  await page.waitForTimeout(300);
}
const scroll=(page,ratio)=>page.evaluate(r=>{const w=document.querySelector('.scroll-wrap');w.scrollTop=Math.max(0,w.scrollHeight*r);},ratio);

for(const lang of ['en','zh']){
  for(const scheme of ['light','dark']){
    const suffix=(lang==='zh'?'-zh':'')+(scheme==='dark'?'-dark':'');
    const d=DOCS[lang];
    test(`site images ${lang} ${scheme}`,async({browser})=>{
      // 1) 首屏：阅读中段，大纲完整，右下角显示进度
      let {context,page}=await openDoc(browser,lang,scheme,{width:1200,height:750},d.md,d.name);
      await showOutline(page);
      await scroll(page,0.07);
      await page.waitForTimeout(600);
      await page.screenshot({path:path.join(OUT,'hero-reading'+suffix+'.png')});
      // 2) 阅读：折叠一节，再打开“跳转到标题”
      await scroll(page,0.05);
      await page.evaluate(()=>{const h=[...document.querySelectorAll('#content > h2')].find(x=>/^4\./.test(x.textContent.trim()));if(h&&window.Folding)Folding.toggle(h);});
      await page.waitForTimeout(300);
      await page.evaluate(()=>openGoToHeading());
      await page.keyboard.type(d.goto);
      await page.waitForTimeout(350);
      await page.screenshot({path:path.join(OUT,'hero-goto'+suffix+'.png')});
      await page.keyboard.press('Escape');
      // 3) 编辑：点击正文，选中一小段，顶部出现格式条
      await scroll(page,0);
      await page.evaluate(()=>{if(window.Folding)Folding.setAll(false);});
      await page.click('#content p');
      await page.evaluate(()=>{const p=document.querySelector('#content p');const t=p.firstChild;const r=document.createRange();r.setStart(t,2);r.setEnd(t,Math.min(14,t.length));const s=getSelection();s.removeAllRanges();s.addRange(r);});
      await page.waitForTimeout(450);
      await page.screenshot({path:path.join(OUT,'edit-bar'+suffix+'.png')});
      // 社交分享图：1200×630，不带大纲干扰
      await context.close();

      // 4) 对比图：只有渲染结果，不带大纲
      ({context,page}=await openDoc(browser,lang,scheme,{width:680,height:720},d.after,d.name));
      await page.addStyleTag({content:'#tocToggle,.reading-end{display:none!important}'});
      await page.waitForTimeout(300);
      await page.screenshot({path:path.join(OUT,'after'+suffix+'.png')});
      await context.close();

      if(scheme==='light'){
        ({context,page}=await openDoc(browser,lang,'light',{width:1200,height:630},d.md,d.name));
        await showOutline(page);
        await scroll(page,0.07);
        await page.waitForTimeout(500);
        await page.screenshot({path:path.join(OUT,'og'+(lang==='zh'?'-zh':'')+'.png')});
        await context.close();
      }
    });
  }
}
// 对比图左侧的 Markdown 原文，供官网页面复制引用
test('site images after source',async()=>{
  fs.mkdirSync(OUT,{recursive:true});
  fs.writeFileSync(path.join(OUT,'after-source.json'),JSON.stringify({en:DOCS.en.after,zh:DOCS.zh.after},null,1));
});
