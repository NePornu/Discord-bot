import re
import os

files = [
    "bot/commands/verification.py",
    "bot/commands/calendar.py",
    "bot/commands/challenge_manager.py",
    "bot/commands/automod_custom.py",
    "bot/commands/notify.py",
    "bot/commands/help.py"
]

for f in files:
    try:
        content = os.popen(f"git show HEAD~1:{f}").read()
        print(f"\n--- {f} ---")
        commands = re.findall(r'@app_commands.command\(name="([^"]+)"', content)
        for cmd in commands:
            print(cmd)
    except Exception as e:
        print(e)
