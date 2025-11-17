# commands/reverification.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Iterable, List, Tuple

import discord
from discord import app_commands, Interaction
from discord.ext import commands

try:
    from config import GUILD_ID, MOD_CHANNEL_ID  # volitelné, lze přepsat parametry v příkazech
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
    logging.debug("✅ Načteny hodnoty z configů (ReverificationCog).")
except Exception as e:
    logging.warning(f"⚠️ Nelze načíst configy (ReverificationCog): {e}")
    # Poskytneme rozumné defaulty (přepiš v příkazech parametry role/code/mod_channel)
    GUILD_ID = None
    MOD_CHANNEL_ID = None
    VERIFICATION_CODE = "123456"
    VERIFIED_ROLE_ID = None


DEFAULT_DM_TEMPLATE = (
    "Ahoj {member}! 🔐 Probíhá **re-verifikace**.\n"
    "Zadej prosím v tomto DM kód: **{code}**.\n"
    "Jakmile ho zadáš, moderátor ti ověřovací roli upraví. Díky!"
)


def chunked(seq: Iterable, n: int) -> Iterable[list]:
    """Rozdělí iterovatelnou sekvenci do bloků po n kusech."""
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf


class ReverificationCog(commands.Cog):
    """/reverify – nástroje pro hromadnou re-verifikaci (slash)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    group = app_commands.Group(name="reverify", description="Re-verifikace uživatelů (DM s kódem)")

    # ---------- Pomocné vyhledávání ----------
    async def _resolve_guild(self, itx: Interaction, guild_id: Optional[int]) -> Optional[discord.Guild]:
        if guild_id:
            g = self.bot.get_guild(guild_id)
            if g:
                return g
        return itx.guild if isinstance(itx.guild, discord.Guild) else None

    def _resolve_mod_channel(
        self, guild: discord.Guild, mod_channel_id: Optional[int]
    ) -> Optional[discord.TextChannel]:
        if mod_channel_id:
            ch = guild.get_channel(mod_channel_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        if MOD_CHANNEL_ID:
            ch = guild.get_channel(MOD_CHANNEL_ID)
            if isinstance(ch, discord.TextChannel):
                return ch
        return None

    # ---------- /reverify status ----------
    @group.command(name="status", description="Zobrazí počty členů s danou ověřovací rolí.")
    @app_commands.describe(
        role="Role, která označuje ověřené členy (výchozí je VERIFIED_ROLE_ID z configu).",
        hide="Odpověď jen pro tebe (ephemeral).",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def status(
        self,
        itx: Interaction,
        role: Optional[discord.Role] = None,
        hide: Optional[bool] = True,
    ):
        await itx.response.defer(ephemeral=hide)
        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        target_role = role or (guild.get_role(VERIFIED_ROLE_ID) if VERIFIED_ROLE_ID else None)
        if not isinstance(target_role, discord.Role):
            return await itx.followup.send("❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True)

        members = [m for m in guild.members if target_role in m.roles and not m.bot]
        bots = [m for m in guild.members if target_role in m.roles and m.bot]

        await itx.followup.send(
            f"ℹ️ **Status re-verifikace**\n"
            f"• Role: {target_role.mention} ({target_role.id})\n"
            f"• Uživatelé: **{len(members)}**\n"
            f"• Boti: **{len(bots)}**",
            ephemeral=hide,
        )

    # ---------- /reverify preview ----------
    @group.command(name="preview", description="Náhled (dry-run): kdo dostane DM k re-verifikaci.")
    @app_commands.describe(
        role="Cílová role (výchozí VERIFIED_ROLE_ID).",
        include_bots="Zahrnout i boty (nedoporučeno).",
        limit_preview="Kolik jmen ukázat v náhledu (1–50).",
        hide="Ephemeral výstup.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def preview(
        self,
        itx: Interaction,
        role: Optional[discord.Role] = None,
        include_bots: Optional[bool] = False,
        limit_preview: app_commands.Range[int, 1, 50] = 15,
        hide: Optional[bool] = True,
    ):
        await itx.response.defer(ephemeral=hide)
        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        target_role = role or (guild.get_role(VERIFIED_ROLE_ID) if VERIFIED_ROLE_ID else None)
        if not isinstance(target_role, discord.Role):
            return await itx.followup.send("❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True)

        members_all = [m for m in guild.members if target_role in m.roles]
        members = members_all if include_bots else [m for m in members_all if not m.bot]

        sample = ", ".join(m.display_name for m in members[:limit_preview])
        more = "" if len(members) <= limit_preview else f"\n… a dalších **{len(members) - limit_preview}**"

        await itx.followup.send(
            f"🧪 **Preview re-verifikace**\n"
            f"• Role: {target_role.mention}\n"
            f"• Kandidátů celkem: **{len(members)}** (z toho boti {'započteni' if include_bots else 'nezapočteni'})\n"
            f"• Ukázka: {sample}{more}",
            ephemeral=hide,
        )

    # ---------- /reverify run ----------
    @group.command(name="run", description="Spustí hromadnou re-verifikaci (DM s kódem).")
    @app_commands.describe(
        role="Cílová role (výchozí VERIFIED_ROLE_ID).",
        code="Kód do DM (výchozí VERIFICATION_CODE).",
        dm_text="Vlastní text DM (použij {member} a {code}).",
        batch_size="Velikost dávky pro odesílání (1–50).",
        delay_ms="Prodleva mezi členy v ms (0–3000).",
        include_bots="Zahrnout i boty (nedoporučuje se).",
        mod_channel="Přesměrování logu do jiného mod kanálu.",
        reason="Důvod akce (zaloguje se).",
        dry_run="Pouze náhled – nic neodesílat.",
        hide="Ephemeral odpověď.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def run(
        self,
        itx: Interaction,
        role: Optional[discord.Role] = None,
        code: Optional[str] = None,
        dm_text: Optional[str] = None,
        batch_size: app_commands.Range[int, 1, 50] = 10,
        delay_ms: app_commands.Range[int, 0, 3000] = 300,
        include_bots: Optional[bool] = False,
        mod_channel: Optional[discord.TextChannel] = None,
        reason: Optional[str] = None,
        dry_run: Optional[bool] = False,
        hide: Optional[bool] = True,
    ):
        await itx.response.defer(ephemeral=hide)

        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        target_role = role or (guild.get_role(VERIFIED_ROLE_ID) if VERIFIED_ROLE_ID else None)
        if not isinstance(target_role, discord.Role):
            return await itx.followup.send("❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True)

        mod_ch = mod_channel or self._resolve_mod_channel(guild, MOD_CHANNEL_ID)
        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE

        # Kandidáti
        members_all = [m for m in guild.members if target_role in m.roles]
        members: List[discord.Member] = members_all if include_bots else [m for m in members_all if not m.bot]

        if not members:
            return await itx.followup.send("ℹ️ Nikdo s cílovou rolí (po aplikaci filtrů).", ephemeral=True)

        # Dry-run?
        if dry_run:
            sample = ", ".join(m.display_name for m in members[:15])
            more = "" if len(members) <= 15 else f"\n… a dalších **{len(members) - 15}**"
            return await itx.followup.send(
                f"🧪 **Dry-run**: DM by bylo odesláno **{len(members)}** členům.\n"
                f"• Role: {target_role.mention}\n"
                f"• Ukázka: {sample}{more}\n"
                f"• Text DM (náhled):\n```\n{template.format(member='{display_name}', code=code_final)}\n```",
                ephemeral=True,
            )

        sent_ok = 0
        sent_fail = 0

        # Odesílání po dávkách
        for block in chunked(members, batch_size):
            tasks = []
            for m in block:
                msg_text = template.format(member=m.display_name, code=code_final)
                async def send_dm(member: discord.Member, text: str):
                    nonlocal sent_ok, sent_fail
                    try:
                        await member.send(text)
                        sent_ok += 1
                    except Exception as e:
                        logging.warning(f"⚠️ Nelze poslat DM {member} ({member.id}): {e}")
                        sent_fail += 1
                tasks.append(send_dm(m, msg_text))
                if delay_ms:
                    await asyncio.sleep(delay_ms / 1000.0)
            # Paralelní dokončení dávky (max batch_size paralelně)
            await asyncio.gather(*tasks, return_exceptions=True)

        # Log do mod kanálu
        if mod_ch:
            try:
                await mod_ch.send(
                    f"📬 **Re-verifikace**\n"
                    f"• Spustil: {itx.user.mention}\n"
                    f"• Role: {target_role.mention}\n"
                    f"• Odesláno OK: **{sent_ok}**, neúspěch: **{sent_fail}**\n"
                    f"{'• Důvod: ' + reason if reason else ''}"
                )
            except Exception as e:
                logging.warning(f"⚠️ Nelze logovat do mod kanálu: {e}")

        await itx.followup.send(
            f"✅ Hotovo. DM odesláno **{sent_ok}** členům, neúspěch **{sent_fail}**.", ephemeral=hide
        )

    # ---------- /reverify resend ----------
    @group.command(name="resend", description="Znovu pošle DM s re-verifikačním kódem jednomu uživateli.")
    @app_commands.describe(
        member="Cílový uživatel",
        code="Kód (pokud prázdné, vezme se VERIFICATION_CODE).",
        dm_text="Vlastní text DM (použij {member} a {code}).",
        hide="Ephemeral odpověď.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def resend(
        self,
        itx: Interaction,
        member: discord.Member,
        code: Optional[str] = None,
        dm_text: Optional[str] = None,
        hide: Optional[bool] = True,
    ):
        await itx.response.defer(ephemeral=hide)

        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE
        try:
            await member.send(template.format(member=member.display_name, code=code_final))
        except Exception as e:
            logging.warning(f"⚠️ Nelze poslat DM {member} ({member.id}): {e}")
            return await itx.followup.send("❌ Nepodařilo se odeslat DM tomuto uživateli.", ephemeral=True)

        await itx.followup.send("✅ DM odesláno.", ephemeral=hide)

    # ---------- /reverify ping ----------
    @group.command(name="ping", description="Pošle ukázkovou re-verifikační zprávu tobě (DM).")
    @app_commands.describe(
        code="Kód (pokud prázdné, vezme se VERIFICATION_CODE).",
        dm_text="Vlastní text DM (použij {member} a {code}).",
        hide="Ephemeral potvrzení v kanále.",
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def ping(
        self,
        itx: Interaction,
        code: Optional[str] = None,
        dm_text: Optional[str] = None,
        hide: Optional[bool] = True,
    ):
        await itx.response.defer(ephemeral=hide)
        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE

        try:
            await itx.user.send(template.format(member=itx.user.display_name, code=code_final))
        except Exception as e:
            logging.warning(f"⚠️ Nelze poslat DM iniciátorovi: {e}")
            return await itx.followup.send("❌ Nepodařilo se poslat DM tobě (zřejmě máš zamčené zprávy).", ephemeral=True)

        await itx.followup.send("📨 Zaslali jsme ti ukázkové DM s re-verifikační zprávou.", ephemeral=hide)


async def setup(bot: commands.Bot):
    """Načtení cogu (discord.py 2.x)."""
    await bot.add_cog(ReverificationCog(bot))
