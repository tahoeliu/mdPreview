"""T03 一次性可复核迁移：从本地 T02 快照按原顺序分离规则。"""
from pathlib import Path
import re
ROOT = Path(__file__).resolve().parents[1]
source = (ROOT / 'tests/fixtures/styles-t02.css').read_text()
source = re.sub(r'/\*.*?\*/', '', source, flags=re.S)
light, dark = {}, {}

def rules(text):
    pos = 0
    while pos < len(text):
        start = text.find('{', pos)
        if start < 0:
            break
        level, end = 1, start + 1
        while level:
            if text[end] == '{': level += 1
            if text[end] == '}': level -= 1
            end += 1
        yield text[pos:start].strip(), text[start+1:end-1].strip()
        pos = end

color = re.compile(r'#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)')
def colors(body, table, prefix):
    def replace(match):
        value = match[0]
        if value not in table:
            table[value] = f'--{prefix}-{len(table)+1}'
        return f'var({table[value]})'
    return color.sub(replace, body)

def content_selector(selector):
    return bool(re.search(r'\.(markdown|tok[-\w]*|mermaid[-\w]*|math[-\w]*|frontmatter[-\w]*|footnotes)\b', selector))

def split(text, is_dark=False):
    content, app = [], []
    for selector, body in rules(text):
        if selector == '@media print':
            continue
        if selector.startswith('@media'):
            c, a = split(body, 'prefers-color-scheme: dark' in selector)
            if c: content.append(f'{selector} {{\n{c}\n}}')
            if a: app.append(f'{selector} {{\n{a}\n}}')
            continue
        csel, asel = [], []
        for sel in selector.split(','):
            (csel if content_selector(sel) else asel).append(sel.strip())
        if csel:
            declarations = colors(body, dark if is_dark else light, 'dark' if is_dark else 'color')
            declarations = declarations.replace('"SF Mono", "Menlo", monospace', 'var(--font-mono)')
            declarations = declarations.replace('line-height: 1.8;', 'line-height: var(--content-line-height);')
            if is_dark:
                csel = [':root:not([data-output]) ' + s for s in csel]
            content.append(', '.join(csel) + ' { ' + declarations + ' }')
        if asel:
            if selector == 'body' and not is_dark:
                body = body.replace('-apple-system, BlinkMacSystemFont, "Helvetica Neue", sans-serif', 'var(--font-sans)')
            body = body.replace('"SF Mono", "Menlo", monospace', 'var(--font-mono)')
            app.append(', '.join(asel) + ' { ' + body + ' }')
    return '\n'.join(content), '\n'.join(app)

content, app = split(source)
# 暗色规则仅用于屏幕；打印始终使用浅色令牌。
content = content.replace('@media (prefers-color-scheme: dark)', '@media screen and (prefers-color-scheme: dark)')
base = '''  --fg: #333;
  --fg-strong: #1d1d1f;
  --fg-muted: #666;
  --bg: #fff;
  --code-bg: #f5f5f7;
  --border: #e0e0e0;
  --link: #007aff;
  --content-font-size: 16px;
  --content-line-height: 1.8;
  --font-sans: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Segoe UI", "Microsoft YaHei", "Noto Sans CJK SC", "Helvetica Neue", Arial, sans-serif;
  --font-mono: "SF Mono", Menlo, Consolas, "Cascadia Mono", "Noto Sans Mono", monospace;'''
# 主语义色直接复用，其他颜色保留唯一命名令牌，不改变原有色值。
semantic = {'#333': '--fg', '#1d1d1f': '--fg-strong', '#666': '--fg-muted', '#f5f5f7': '--code-bg', '#e0e0e0': '--border', '#007aff': '--link'}
for value, token in semantic.items():
    if value in light:
        content = content.replace(f'var({light[value]})', f'var({token})')
        del light[value]
light_values = '\n'.join(f'  {key}: {value};' for value, key in light.items())
dark_values = '\n'.join(f'    {key}: {value};' for value, key in dark.items())
tokens = ':root {\n' + base + '\n' + light_values + '\n}\n'
tokens += '@media screen and (prefers-color-scheme: dark) {\n  :root:not([data-output]) {\n' + dark_values + '\n  }\n}\n'
tokens += ':root[data-output] {\n' + base + '\n' + light_values + '\n}\n'
for name, data in [('tokens', tokens), ('content', content), ('app', app)]:
    target = ROOT / 'css' / (name + '.css')
    if target.exists():
        raise FileExistsError(target)
    target.write_text(data + '\n')
