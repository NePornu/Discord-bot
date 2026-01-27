import re

path = '/root/discord-bot/web/frontend/templates/index.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()


content = re.sub(r'\{\s+\{', '{{', content)
content = re.sub(r'\}\s+\}', '}}', content)


content = content.replace('default (0)', 'default(0)')



content = re.sub(r'const valOnline = \{\{ realtime_active \| default\(0\) \| tojson\n\s+\}\};', 'const valOnline = {{ realtime_active | default(0) | tojson }};', content)


content = content.replace('labe ls:', 'labels:')
content = content.replace('| s afe', '| safe')
content = content.replace('| t ojson', '| tojson')
content = content.replace('joins _data', 'joins_data')
content = content.replace('leaves_d ata', 'leaves_data')
content = content.replace('ms glen', 'msglen')
content = content.replace('msglen _labels', 'msglen_labels')
content = content.replace('msgl en_data', 'msglen_data')
content = content.replace('dau_mau_ra tio', 'dau_mau_ratio')
content = content.replace('dau_wa u_ratio', 'dau_wau_ratio')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Template cleaned.")
