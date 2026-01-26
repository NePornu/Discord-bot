import re
import os

files = [
    '/root/discord-bot/web/frontend/templates/index.html',
    '/root/discord-bot/web/frontend/templates/predictions.html'
]

for path in files:
    if not os.path.exists(path):
        continue
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Fix split tags { { and } }
    content = re.sub(r'\{\s+\{', '{{', content)
    content = re.sub(r'\}\s+\}', '}}', content)

    # 2. Fix triple braces }}} or { {{
    content = re.sub(r'\}\}\}', '}}', content)
    content = re.sub(r'\{\{\{', '{{', content)

    # 3. Fix space in default (0)
    content = content.replace('default (0)', 'default(0)')

    # 4. Fix specific corrupted identifiers
    replacements = {
        'labe ls:': 'labels:',
        '| s afe': '| safe',
        '| t ojson': '| tojson',
        'joins _data': 'joins_data',
        'leaves_d ata': 'leaves_data',
        'ms glen': 'msglen',
        'msglen _labels': 'msglen_labels',
        'msgl en_data': 'msglen_data',
        'dau_mau_ra tio': 'dau_mau_ratio',
        'dau_wa u_ratio': 'dau_wau_ratio',
        'cailEl': 'detailEl',
        'Er r:': 'Err:',
    }
    for old, new in replacements.items():
        content = content.replace(old, new)

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

print("All templates cleaned.")
