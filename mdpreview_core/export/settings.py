"""输出设置的默认值及桥接输入校验。"""
CHOICES = {'paper': ('auto', 'a4', 'letter'), 'margins': ('narrow', 'normal', 'wide'),
           'font': ('small', 'normal', 'large'), 'pdf_layout': ('paged', 'continuous'),
           'png_width': ('original', 'mobile')}


def defaults():
    return {'paper': 'auto', 'margins': 'normal', 'font': 'normal',
            'page_numbers': True, 'show_urls': False, 'hide_frontmatter': True,
            'h1_new_page': False, 'pdf_layout': 'paged', 'png_width': 'original', 'legacy_docx': False}


def validate(options):
    if not isinstance(options, dict):
        return False
    base = defaults()
    return all(key in base and (isinstance(value, str) and value in CHOICES[key]
               if key in CHOICES else type(value) is bool) for key, value in options.items())
