import re

path = '/root/discord-bot/web/frontend/templates/index.html'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace { { with {{ and } } with }} allowing for any whitespace
new_content = re.sub(r'\{\s+\{', '{{', content)
new_content = re.sub(r'\}\s+\}', '}}', new_content)

with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Fixed Jinja2 tags.")
