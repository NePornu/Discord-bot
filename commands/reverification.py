# reverification.py
import discord
import logging
from discord.ext import commands

try:
    from config import GUILD_ID, MOD_CHANNEL_ID
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
    logging.debug("✅ Načteny hodnoty z configů (ReverificationCog).")
except ImportError as e:
    logging.error(f"❌ Chyba při načítání konfiguračních souborů (ReverificationCog): {e}")
    raise

class ReverificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name="reverify_all", hidden=True)
    @commands.has_permissions(administrator=True)
    async def reverify_all(self, ctx: commands.Context):
        """Hromadná re-verifikace všech, co stále mají ověřovací roli."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            await ctx.send(f"❌ Nelze najít guild s ID: {GUILD_ID}")
            return

        verification_role = guild.get_role(VERIFIED_ROLE_ID)
        if not verification_role:
            await ctx.send(f"❌ Nelze najít ověřovací roli s ID: {VERIFIED_ROLE_ID}")
            return

        # Seznam všech členů, kteří mají ověřovací roli
        members_to_reverify = [m for m in guild.members if verification_role in m.roles]
        await ctx.send(f"Nalezeno {len(members_to_reverify)} členů s verifikační rolí k re-verifikaci.")

        # Pro každého pošleme DM a informujeme mod kanál
        mod_channel = guild.get_channel(MOD_CHANNEL_ID)
        for member in members_to_reverify:
            # DM
            try:
                await member.send(
                    f"Ahoj {member.display_name}! Probíhá re-verifikace. "
                    f"Zadej prosím v tomto chatu kód: **{VERIFICATION_CODE}**.\n"
                    "Jakmile ho zadáš, moderátor ti roli zase odebere."
                )
            except Exception as e:
                logging.warning(f"⚠️ Nelze poslat DM uživateli {member.name}: {e}")

            # Informace do mod kanálu
            if mod_channel:
                await mod_channel.send(
                    f"{member.mention} byl vyzván k re-verifikaci. "
                    "Jakmile zadá správný kód, odeberte mu ověřovací roli."
                )

        await ctx.send("✅ Hotovo! Všem vybraným členům byla poslána zpráva k re-verifikaci.")

async def setup(bot: commands.Bot):
    """Funkce pro načtení cogu (v discord.py 2.x)."""
    await bot.add_cog(ReverificationCog(bot))
