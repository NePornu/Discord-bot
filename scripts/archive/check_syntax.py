import py_compile
import sys

try:
    py_compile.compile('/root/discord-bot/bot/commands/avatar_nsfw.py', doraise=True)
    print("Syntax OK")
except Exception as e:
    print(f"Syntax ERROR: {e}")
    sys.exit(1)
