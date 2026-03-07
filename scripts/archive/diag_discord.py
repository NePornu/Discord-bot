import discord
print(f"Version: {discord.__version__}")
print(f"File: {discord.__file__}")
try:
    from discord import app_commands
    print("app_commands: YES")
except ImportError:
    print("app_commands: NO")
