"""生成无隐私、可复现的合成输出样本；不是任何服务的真实导出。"""
import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent / 'fixtures' / 'output'
ROOT.mkdir(parents=True, exist_ok=True)
fixtures = {}
paragraph = ('阅读工具应当忠实保留源文档的层级、标点与内容，而不是为了排版悄悄改写文字。'
             '在分享之前，我们逐项核对标题、正文、代码和表格，确认分页没有遗漏，中文标点没有孤立在行首。'
             '中英混排常见于技术说明，Markdown、Unicode、WebKit 与 PDF 都需要保持可读性。'
             '同一份材料可能出现在大屏幕、打印纸张和移动设备上，因此应分别记录实际测量结果，避免用截图代替数据。'
             '本段为输出回归测试合成内容，不包含真实会议、客户或个人信息。')
fixtures['zh-longform.md'] = '# HHeading One 中文长文\n\n' + '\n\n'.join(
    f'## 第 {i} 节 Mixed typography\n\n### 细节检查\n\n#### 保留层次\n\n{paragraph}\n\n{paragraph}'
    for i in range(1, 15)) + '\n\n长文结束 LONGFORM_END\n'
fixtures['wide-table.md'] = '# 十列三十行表格\n\n' + '| ' + ' | '.join(f'列{i}' for i in range(1, 11)) + ' |\n' + '| ' + ' | '.join(['---'] * 10) + ' |\n' + ''.join('| ' + ' | '.join(f'R{row:02d}C{col:02d}内容' for col in range(1, 11)) + ' |\n' for row in range(1, 31))
fixtures['long-code.md'] = '# 单个一百二十行代码块\n\n```python\n' + ''.join(f'print("line_{i:03d}: 中文代码输出")\n' for i in range(1, 121)) + '```\n'
fixtures['mermaid.md'] = '# Mermaid 流程与时序\n\n```mermaid\nflowchart LR\n A[读取文档] --> B[排版] --> C[输出]\n```\n\n```mermaid\nsequenceDiagram\n participant Reader\n participant Renderer\n Reader->>Renderer: Markdown\n Renderer-->>Reader: Preview\n```\n'
fixtures['math.md'] = r'''# 四种数学分隔符

行内美元符号：$a^2+b^2=c^2$。

$$
\sum_{i=1}^{n} i = \frac{n(n+1)}{2}
$$

行内反斜杠：\(E=mc^2\)。

\[
\int_0^1 x^2\,dx=\frac{1}{3}
\]
'''
fixtures['footnotes.md'] = '# 脚注与链接\n\n正文引用[^one]，再次引用[^one]，以及另一条[^two]。\n\n[^one]: 第一条中文脚注。\n[^two]: 含有 **粗体** 和 [项目源码](https://github.com/tahoeliu/mdPreview) 的脚注。\n'
fixtures['images.md'] = '# 本地与远程图片\n\n![合成彩条](assets/color-bars.png)\n\n![远程源码图片，探针禁止联网](https://github.com/tahoeliu/mdPreview/raw/main/images/screenshot.png)\n'
fixtures['frontmatter.md'] = '---\ntitle: 合成排版样本\nauthor: 测试机器人\nlang: zh-CN\ntags: [排版, 回归]\n---\n\n# 元数据与正文\n\n元数据不是正文标题，须分别记录打印行为。\n'
fixtures['alerts.md'] = '# 提示块\n\n' + '\n\n'.join(f'> [!{kind}]\n> 这是合成的 {kind} 提示内容。' for kind in ['NOTE', 'TIP', 'IMPORTANT', 'WARNING', 'CAUTION']) + '\n'
for name in ['chatgpt', 'claude']:
    fixtures[f'ai-export-{name}.md'] = f'''# {name} 风格合成替代样本

> 来源声明：SYNTHETIC SUBSTITUTE。未提供真实 AI 导出素材，本文件由测试工具人工构造，**不是 {name} 的真实对话或导出**。不得据此宣称真实导出兼容性已验证。

## 用户问题（虚构）

请说明如何验证 Markdown 输出质量。

## 助手回答（虚构）

1. 保留 **标题层级** 与正文。
2. 检查表格、代码、公式 $x^2$ 与脚注[^note]。
3. 输出 PDF 后测量字形和边距。

| 项目 | 检查方式 |
| --- | --- |
| 分页 | 记录页数 |
| 代码 | 保留换行 |

```python
print("synthetic fixture")
```

[^note]: 这是合成脚注，不引用真实用户数据。
'''
for name, text in fixtures.items():
    path = ROOT / name
    if path.exists():
        if path.read_text(encoding='utf-8') != text:
            raise FileExistsError(path)
    else:
        path.write_text(text, encoding='utf-8')
assets = ROOT / 'assets'
if not assets.exists():
    assets.mkdir()
def chunk(kind, data):
    return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data))
colors = [(30, 90, 160), (110, 170, 90), (230, 170, 60), (180, 70, 80)]
row = b'\x00' + b''.join(bytes(colors[x // 80]) for x in range(320))
png = b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', 320, 120, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(row * 120)) + chunk(b'IEND', b'')
(assets / 'color-bars.png').write_bytes(png)
(ROOT / 'manifest.json').write_text(json.dumps({'provenance': '全部为合成回归样本；AI 样本并非真实导出', 'real_ai_exports_available': False, 'fixtures': list(fixtures)}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'已生成 {len(fixtures)} 个 Markdown 样本及本地 PNG')
