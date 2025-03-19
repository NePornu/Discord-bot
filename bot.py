import discord
from discord.ext import commands
import os
import bot_token  # Soubor s tokenem bota
import config  # Konfigurační soubor

# Inicializace bota
# Definování konkrétních intentů
intents = discord.Intents.default()
intents.members = True  # Pro on_member_join
intents.guilds = True   # Pro správné načítání guild ID
intents.messages = True  # Pro detekci zpráv od uživatele
intents.dm_messages = True  # Pro zprávy v DM
intents.message_content = True  # Pro čtení obsahu zpráv
bot = commands.Bot(command_prefix=config.BOT_PREFIX, intents=intents)

print("[DEBUG] Bot se inicializuje...")

# Dynamické načítání cogů (pouze commands/)
async def load_cogs():
    """Načítá všechny cogy ze složky commands/"""
    folder = "commands"
    print(f"[DEBUG] Načítání modulů ze složky {folder}...")
    for filename in os.listdir(folder):
        if filename.endswith(".py") and not filename.startswith("_"):
            module_name = f"{folder}.{filename[:-3]}"
            print(f"[DEBUG] Pokus o načtení modulu: {module_name}")
            try:
                await bot.load_extension(module_name)
                print(f"[INFO] Modul {module_name} načten úspěšně.")
            except Exception as e:
                print(f"[ERROR] Chyba při načítání modulu {module_name}: {e}")

    # ✅ Kontrola, zda VerificationCog byl úspěšně načten
    if "commands.verification" in bot.extensions:
        print("[INFO] ✅ VerificationCog byl úspěšně načten.")
    else:
        print("[ERROR] ❌ VerificationCog nebyl načten správně!")

# Událost při spuštění bota
@bot.event
async def on_ready():
    print(f"[INFO] ✅ Přihlášen jako {bot.user}")
    print("[INFO] ✅ Připraven na příkazy!")
    await load_cogs()

    # Loguje info o VerificationCog
    verification_cog = bot.get_cog("VerificationCog")
    if verification_cog:
        print("[INFO] ✅ VerificationCog je aktivní a běží!")
    else:
        print("[ERROR] ❌ VerificationCog nebyl načten správně!")

# Povolené příkazy z config.py
@bot.check
async def globally_block_commands(ctx):
    command_name = ctx.command.name
    command_config = config.COMMANDS_CONFIG.get(command_name, {})

    if not command_config.get("enabled", False):
        print(f"[WARNING] Příkaz {command_name} je zakázán v konfiguraci.")
        return False

    if command_config.get("admin_only", False) and not ctx.author.guild_permissions.administrator:
        print(f"[WARNING] Uživatel {ctx.author} se pokusil použít admin-only příkaz {command_name}.")
        return False

    print(f"[DEBUG] Příkaz {command_name} prováděn uživatelem {ctx.author}.")
    return True

# Spuštění bota
async def main():
    async with bot:
        await bot.start(bot_token.TOKEN)

try:
    print("[DEBUG] Spouštění bota...")
    import asyncio
    asyncio.run(main())
except Exception as e:
    print(f"[ERROR] Chyba při spuštění bota: {e}")
