import fs from 'node:fs';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const files=['app.js','mdPreview.py',...fs.readdirSync(path.join(root,'frontend')).filter(x=>x.endsWith('.js')).map(x=>'frontend/'+x)];
const en={},hans={};
const decode=s=>s.replace(/\\(['"\\])/g,'$1').replace(/\\n/g,'\n');
for(const file of files){const source=fs.readFileSync(path.join(root,file),'utf8');
 for(const m of source.matchAll(/\b(?:_?t|translate)\(\s*(['"])((?:\\.|(?!\1).)*?)\1\s*,\s*(['"])((?:\\.|(?!\3).)*?)\3\s*\)/gs)){
  const key=decode(m[2]);en[key]=key;hans[key]=decode(m[4]);
 }
}
for(const item of JSON.parse(fs.readFileSync(path.join(root,'frontend/shortcuts.json'),'utf8'))){en[item.en]=item.en;hans[item.en]=item.zh;}
// 固定简繁字符表只用于生成候选；复杂用词仍需人工逐项审核。
const pairs='叠疊 开開 显顯 隐隱 宽寬 贴貼 转轉 换換 来來 乱亂 错錯 内內 请請 码碼 视視 图圖 检檢 查查 剪剪 读讀 没沒 嵌嵌 试試 导導 败敗 录錄 绪緒 页頁 为為 复複 关關 变變 时時 问問 处處 编編 辑輯 丢丟 弃棄 冲衝 盘盤 选選 择擇 续續 档檔 径徑 当當 窗窗 覆覆 盖蓋 过過 字字 号號 个個 纲綱 击擊 装裝 载載 网網 络絡 误誤 连連 接接 验驗 动動 准準 备備 启啟 实實 验驗 输輸 览覽 浏瀏 纯純 编編 删刪 您您 损損 进進 全全 缩縮 属屬 性性 称稱 节節 创創 建建 稍稍 后後 设設 置置 语語 言言 跟跟 随隨 系系 统統 简簡 体體 恢恢 复復 默默 认認 远遠 程程 询詢 总總 从從 边邊 布布 隐隱 数數 据據 隐隱 私私 仅僅 主主 访訪 问問 许許 致致 谢謝 诊診 断斷 信信 息息 无無 法法 纸紙 张張 强強 调調 汉漢 头頭 级級 参參 数數 终終 结結 标標 签籤 单單 线線 测測 骤驟 练練 习習 赞贊 权權 限限 源源 详詳 细細 云雲 传傳 递遞 迟遲 滚滾 拖拖 动動 浅淺 复複 杂雜 项項 组組 览覽 释釋 减減 轻輕 质質 量量 证證 扩擴 张張 与與 并並 专專 业業 实實 用用 类類 别別 对對 应應 经經 认認 识識 效效 义義 状狀 态態 负負 责責 触觸 发發 键鍵 列列 表表 览覽 组組 织織 划劃 背背 景景 确確 协協 议議 脚腳 注註 汇彙 编編 译譯 义義 术術 语語 套套 件件 双雙 净淨 卫衛 护護 资資 产產 广廣 联聯 达達 会會 话話 硬硬 历歷 史史 难難 旧舊 寻尋 钮鈕 让讓 这這 将將 您您 还還 够夠 说說 获獲 执執 行行 含含 则則 保保 留留 进進 度度 条條 纹紋 缺缺 严嚴 格格 尝嘗 学學 习習 静靜 态態 员員 额額 约約 略略 临臨 获獲 映映 射射 仅僅 须須 运運 行行 管管 理理 选選 弹彈 环環 境境'.split(/\s+/);
pairs.push(...'闭閉 继繼 点點 现現 预預 夹夾 帮幫 报報 题題 间間 于於 欢歡 迎迎 阅閱 链鏈 离離 勾勾 状狀 态態 图圖 仅僅 且且 把把 传傳 递遞 览覽'.split(/\s+/));
const map=Object.fromEntries(pairs.map(pair=>[...pair]));
const hant=Object.fromEntries(Object.entries(hans).map(([key,value])=>[key,[...value].map(c=>map[c]||c).join('')]));
for(const key of Object.keys(hant))for(const [from,to] of [['複制','複製'],['恢複','恢復'],['粘貼','貼上'],['剪貼板','剪貼簿'],['源碼','原始碼'],['導出','匯出'],['打印','列印'],['文件夾','資料夾'],['文件','檔案'],['文檔','文件'],['設置','設定'],['界面','介面'],['信息','資訊'],['鏈接','連結'],['链接','連結'],['加載','載入'],['遠程','遠端'],['默認','預設'],['網絡','網路'],['窗口','視窗'],['保存','儲存'],['富文本','富文字'],['純文本','純文字'],['字號','字級'],['示例','範例'],['打開','開啟'],['查找','尋找'],['佈局','版面'],['布局','版面']])hant[key]=hant[key].split(from).join(to);
const aliases={'export.failed':'Export failed: ','settings.title':'Settings','help.title':'Help','onboarding.example':'Open Example'};
for(const [key,source] of Object.entries(aliases))if(en[source]){en[key]=en[source];hans[key]=hans[source];hant[key]=hant[source];}
if(process.argv.includes('--check')){
 for(const [name,expected] of Object.entries({en,'zh-Hans':hans,'zh-Hant':hant})){
  const actual=JSON.parse(fs.readFileSync(path.join(root,'frontend',name+'.json'),'utf8'));
  for(const key of Object.keys(expected))if(!(key in actual))throw new Error(name+': missing '+key);
 }
 console.log('文案收录检查通过');
}else{
 for(const [name,value] of Object.entries({en,'zh-Hans':hans,'zh-Hant':hant}))fs.writeFileSync(path.join(root,'frontend',name+'.json'),JSON.stringify(value,null,2)+'\n');
 console.log('已生成三份候选字典；繁体用词仍需人工审核');
}
