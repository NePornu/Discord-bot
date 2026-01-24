import os

target_files = [
    '/root/discord-bot/web/frontend/templates/index.html',
    '/root/discord-bot/web/frontend/templates/predictions.html'
]

for file_path in target_files:
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        new_content = content.replace('{ {', '{{').replace('} }', '}}')
        
        if content != new_content:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(new_content)
            print(f"Fixed {file_path}")
        else:
            print(f"No changes needed for {file_path}")
    else:
        print(f"File not found: {file_path}")
