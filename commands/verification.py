import discord
from discord.ext import commands
import logging

try:
    from config import GUILD_ID, MOD_CHANNEL_ID, WELCOME_CHANNEL_ID
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
except ImportError as e:
    logging.error(f"Chyba při načítání configů: {e}")
    raise

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class RemoveRoleView(discord.ui.View):
    """View s tlačítkem pro odebrání ověřovací role."""
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)  # View bez timeoutu (zůstane, dokud ho někdo nezmáčkne/nevyprší)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Odebrat ověřovací roli", style=discord.ButtonStyle.danger)
    async def remove_verification_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ověříme, že kdo kliká, má práva spravovat role
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message(
                "Nemáš oprávnění odebírat roli.",
                ephemeral=True  # zpráva viditelná jen pro toho, kdo kliknul
            )
            return

        guild = interaction.guild
        role = guild.get_role(VERIFIED_ROLE_ID)
        member = guild.get_member(self.target_user_id)

        if not member or not role:
            await interaction.response.send_message(
                "Nenašel jsem člena nebo roli.",
                ephemeral=True
            )
            return

        try:
            # Odebrání role
            await member.remove_roles(role)

            # Změna (editace) původní zprávy – už žádný button, jen info o ověření.
            embed_verified = discord.Embed(
                title="Uživatel ověřen!",
                description=f"{member.mention} byl právě ověřen a role odebrána.",
                color=discord.Color.green()
            )
            await interaction.response.edit_message(embed=embed_verified, view=None)
        except Exception as e:
            await interaction.response.send_message(f"Nepodařilo se odebrat roli: {e}", ephemeral=True)

class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Přidání dočasné ověřovací role, DM s kódem a případně info do mod kanálu."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild:
            logging.error(f"Nepodařilo se najít guildu s ID {GUILD_ID}.")
            return

        # 1) Přidáme ověřovací roli
        role = guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
                logging.debug(f"Role {VERIFIED_ROLE_ID} byla přidána uživateli {member}.")
            except Exception as e:
                logging.warning(f"Chyba při přidávání role: {e}")

        # 2) Pošleme DM s kódem
        try:
            embed_dm = discord.Embed(
                title="Ověření",
                description=(
                    "Ahoj! Abychom věděli, že nejsi robot, pošli mi do této konverzace náš tajný kód:\n\n"
                    f"**{VERIFICATION_CODE}**\n\n"
                    "Jakmile ho zadáš správně, moderátoři ti roli odeberou a budeš tu jako doma!"
                ),
                color=discord.Color.green()
            )
            await member.send(embed=embed_dm)
        except Exception as e:
            logging.warning(f"Nelze poslat DM uživateli {member}: {e}")
            return

        # 3) Čekáme na odpověď (správný kód) v DM
        def check(msg: discord.Message):
            return msg.author == member and isinstance(msg.channel, discord.DMChannel)

        while True:
            try:
                response = await self.bot.wait_for("message", check=check, timeout=3600)  # 1 hodina
                if response.content.strip().upper() == VERIFICATION_CODE.upper():
                    # Správný kód => pošleme do mod kanálu embed s tlačítkem k odebrání role
                    mod_channel = guild.get_channel(MOD_CHANNEL_ID)
                    if mod_channel:
                        embed_mod = discord.Embed(
                            title="Ověřovací kód zadán správně!",
                            description=(
                                f"{member.mention} zadal správný kód.\n"
                                "Moderátoři, prosím odeberte mu dočasnou roli."
                            ),
                            color=discord.Color.blue()
                        )
                        view = RemoveRoleView(member.id)  # Tady vzniká tlačítko
                        await mod_channel.send(embed=embed_mod, view=view)

                    # DM uživateli dáme vědět, že budeme čekat na odebrání role
                    embed_ok = discord.Embed(
                        title="Super!",
                        description=(
                            "Zadal jsi správný kód. Počkej, až ti moderátoři odeberou dočasnou roli."
                        ),
                        color=discord.Color.green()
                    )
                    await member.send(embed=embed_ok)
                    break
                else:
                    # Špatný kód => znovu
                    embed_wrong = discord.Embed(
                        title="Ups, špatný kód!",
                        description="Zkus to prosím znovu. ",
                        color=discord.Color.red()
                    )
                    await member.send(embed=embed_wrong)
            except Exception as e:
                logging.error(f"Chyba při zpracování kódu od uživatele {member}: {e}")
                break

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Jakmile dojde k odebrání ověřovací role, je uživatel oficiálně ověřen."""
        before_roles = {r.id for r in before.roles}
        after_roles = {r.id for r in after.roles}

        if VERIFIED_ROLE_ID in before_roles and VERIFIED_ROLE_ID not in after_roles:
            # DM pro uživatele, že je ověřen
            try:
                embed_dm = discord.Embed(
                    title="Hotovo!",
                    description=(
                        "Moderátoři ti právě odebrali dočasnou roli, takže jsi plně ověřen(a). "
                        "Vítej mezi námi, od teď se můžeš zapojit naplno!"
                    ),
                    color=discord.Color.green()
                )
                await after.send(embed=embed_dm)
            except Exception as e:
                logging.warning(f"Nelze poslat DM o ověření uživateli {after}: {e}")

            # Poslat do welcome kanálu uvítání
            guild = after.guild
            welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
            if welcome_channel:
                embed_welcome = discord.Embed(
                    title="Oficiální uvítání!",
                    description=(
                        f"{after.mention}, teď už jsi oficiálně ověřen(a)! Jsme rádi, že jsi tu. "
                        "Mrkni do našich kanálů, zapoj se do debaty a užij si to tady!"
                    ),
                    color=discord.Color.blue()
                )
                await welcome_channel.send(embed=embed_welcome)

            logging.info(f"Uživatel {after} byl ověřen odebráním role.")

async def setup(bot: commands.Bot):
    """Načtení cogu (pro discord.py 2.x)."""
    await bot.add_cog(VerificationCog(bot))
