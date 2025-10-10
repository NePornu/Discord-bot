import discord
from discord.ext import commands
import asyncio

class PurgeCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.has_permissions(manage_messages=True)
    @commands.command(name='purge')
    async def purge(self, ctx, amount: int, user: discord.User = None, word: str = None):
        """
        Smaže přesně <amount> zpráv podle uživatele a/nebo slova. (max 100 najednou)
        Použití: !purge <množství> [@uživatel] [slovo]
        """
        if amount < 1 or amount > 100:
            await ctx.send("❌ Množství zpráv k smazání musí být mezi 1 a 100.")
            return

        confirmation_message = await ctx.send(f"⏳ Hledám a mažu {amount} zpráv...")

        # Vybírejme pouze zprávy, které splňují filtr a přitom jich bude právě tolik, kolik chceš smazat
        def filter_msg(message):
            if user and word:
                return message.author == user and word.lower() in message.content.lower()
            elif user:
                return message.author == user
            elif word:
                return word.lower() in message.content.lower()
            else:
                return True

        deleted = []
        # Discord API umožňuje najednou bulk mazat jen 100 zpráv mladších než 14 dní!
        # Projdeme tedy např. posledních 1000 zpráv a z těch vybereme tolik, kolik uživatel požaduje.
        try:
            counter = 0
            async for message in ctx.channel.history(limit=1000, oldest_first=False):
                if message.id == confirmation_message.id:
                    continue  # Nemažeme potvrzovací zprávu

                if filter_msg(message):
                    deleted.append(message)
                    counter += 1
                    if counter >= amount:
                        break

            if not deleted:
                await confirmation_message.edit(content="Nenalezeny žádné zprávy, které by odpovídaly filtru.")
                await asyncio.sleep(5)
                await confirmation_message.delete()
                return

            # Smazání nalezených zpráv najednou
            # Pokud je pouze jedna, použij delete, jinak bulk delete
            if len(deleted) == 1:
                await deleted[0].delete()
            else:
                await ctx.channel.delete_messages(deleted)

            await confirmation_message.edit(content=f"✅ Smazáno {len(deleted)} zpráv.")
            await asyncio.sleep(5)
            await confirmation_message.delete()
        except discord.Forbidden:
            await confirmation_message.edit(content="❌ Nemám oprávnění pro smazání zpráv.")
        except discord.HTTPException as e:
            await confirmation_message.edit(content=f"❌ Chyba Discord API: {e}")

async def setup(bot):
    await bot.add_cog(PurgeCog(bot))
