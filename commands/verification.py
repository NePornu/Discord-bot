# commands/verification.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import discord
from discord.ext import commands
from discord import app_commands, Interaction

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
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Odebrat ověřovací roli", style=discord.ButtonStyle.danger)
    async def remove_verification_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Kontrola oprávnění
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Nemáš oprávnění odebírat roli.", ephemeral=True)
            return

        guild = interaction.guild
        role = guild.get_role(VERIFIED_ROLE_ID) if guild else None
        member = guild.get_member(self.target_user_id) if guild else None

        if not member or not role:
            await interaction.response.send_message("Nenašel jsem člena nebo roli.", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason="Verification approved via button")
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

    # ===================== SLASH skupina =====================
    verify_group = app_commands.Group(name="verify", description="Ověřování členů (DM kód, role, status)")

    @verify_group.command(name="send", description="Pošle uživateli DM s ověřovacím kódem.")
    @app_commands.describe(member="Uživatel, kterému poslat DM s kódem", hide="Ephemeral potvrzení v kanále")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_send(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
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
            await itx.followup.send(f"📨 DM s kódem odesláno uživateli {member.mention}.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Nelze poslat DM: {e}", ephemeral=True)

    @verify_group.command(name="resend", description="Znovu pošle ověřovací DM vybranému uživateli.")
    @app_commands.describe(member="Uživatel pro opětovné odeslání", hide="Ephemeral potvrzení")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_resend(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await self.verify_send.callback(self, itx, member=member, hide=hide)

    @verify_group.command(name="approve", description="Odebere ověřovací roli uživateli (rychlá moderace).")
    @app_commands.describe(member="Uživatel k ověření (odebrání role)", hide="Ephemeral potvrzení")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def verify_approve(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        role = member.guild.get_role(VERIFIED_ROLE_ID) if member.guild else None
        if not role:
            return await itx.followup.send("❌ Ověřovací roli nelze najít.", ephemeral=True)
        if role not in member.roles:
            return await itx.followup.send("ℹ️ Tento uživatel ověřovací roli nemá.", ephemeral=True)
        try:
            await member.remove_roles(role, reason="Verification approved via slash")
            await itx.followup.send(f"✅ Odebírám ověřovací roli uživateli {member.mention}.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Chyba při odebírání role: {e}", ephemeral=True)

    @verify_group.command(name="panel", description="Pošle do mod kanálu panel s tlačítkem pro odebrání role.")
    @app_commands.describe(member="Uživatel, pro kterého vytvořit panel", hide="Ephemeral potvrzení")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_panel(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        guild = itx.guild
        if not guild:
            return await itx.followup.send("❌ Příkaz lze použít jen na serveru.", ephemeral=True)
        mod_channel = guild.get_channel(MOD_CHANNEL_ID)
        if not isinstance(mod_channel, discord.TextChannel):
            return await itx.followup.send("❌ Mod kanál nelze najít.", ephemeral=True)

        embed_mod = discord.Embed(
            title="Ověřovací kód zadán správně!",
            description=(
                f"{member.mention} zadal správný kód.\n"
                "Moderátoři, prosím odeberte mu dočasnou roli."
            ),
            color=discord.Color.blue()
        )
        view = RemoveRoleView(member.id)
        try:
            await mod_channel.send(embed=embed_mod, view=view)
            await itx.followup.send("🧩 Panel odeslán do mod kanálu.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Nelze odeslat panel: {e}", ephemeral=True)

    @verify_group.command(name="status", description="Zobrazí, zda má člen ověřovací roli.")
    @app_commands.describe(member="Uživatel ke kontrole", hide="Ephemeral odpověď")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_status(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        role = member.guild.get_role(VERIFIED_ROLE_ID) if member.guild else None
        if not role:
            return await itx.followup.send("❌ Ověřovací role nebyla nalezena.", ephemeral=True)
        has_role = role in member.roles
        await itx.followup.send(
            f"🔎 {member.mention} **{'má' if has_role else 'nemá'}** ověřovací roli ({role.mention}).",
            ephemeral=hide
        )

    @verify_group.command(name="ping", description="Pošle zkušební ověřovací DM tobě.")
    @app_commands.describe(hide="Ephemeral potvrzení v kanále")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_ping(self, itx: Interaction, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        try:
            embed_dm = discord.Embed(
                title="Ověření (test DM)",
                description=f"Zkušební zpráva. Tvůj kód by normálně byl: **{VERIFICATION_CODE}**",
                color=discord.Color.orange()
            )
            await itx.user.send(embed=embed_dm)
            await itx.followup.send("📨 Zkušební DM odesláno.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Nelze poslat testovací DM: {e}", ephemeral=True)

    # ===================== PŮVODNÍ LISTENERY (BEZE ZMĚN) =====================
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Přidání dočasné ověřovací role, DM s kódem a případně info do mod kanálu."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild or member.guild.id != GUILD_ID:
            return

        # 1) Přidáme ověřovací roli
        role = guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await member.add_roles(role, reason="Join: temporary verified role")
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
                        view = RemoveRoleView(member.id)
                        await mod_channel.send(embed=embed_mod, view=view)

                    embed_ok = discord.Embed(
                        title="Super!",
                        description="Zadal jsi správný kód. Počkej, až ti moderátoři odeberou dočasnou roli.",
                        color=discord.Color.green()
                    )
                    await member.send(embed=embed_ok)
                    break
                else:
                    embed_wrong = discord.Embed(
                        title="Ups, špatný kód!",
                        description="Zkus to prosím znovu.",
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
            # DM pro uživatele
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

            # Uvítání do welcome kanálu
            guild = after.guild
            welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
            if isinstance(welcome_channel, discord.TextChannel):
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
