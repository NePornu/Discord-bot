# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import logging
from typing import Optional, Iterable, List, Union

import discord
from discord import app_commands, Interaction
from discord.ext import commands

# Konfigurace - pokus o načtení, jinak default
try:
    from config import GUILD_ID, MOD_CHANNEL_ID
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
    logging.debug("✅ Načteny hodnoty z configů (ReverificationCog).")
except ImportError:
    logging.warning("⚠️ Nelze načíst configy (ReverificationCog) - použijí se výchozí hodnoty.")
    GUILD_ID = None
    MOD_CHANNEL_ID = None
    VERIFICATION_CODE = "Restart"
    VERIFIED_ROLE_ID = None
except Exception as e:
    logging.error(f"⚠️ Chyba při importu configů: {e}")
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

    # ---------- Pomocné metody ----------
    async def _resolve_guild(self, itx: Interaction, guild_id: Optional[int]) -> Optional[discord.Guild]:
        """Vrátí objekt guildy buď z configu, nebo z kontextu interakce."""
        if guild_id:
            g = self.bot.get_guild(guild_id)
            if g:
                return g
        return itx.guild if isinstance(itx.guild, discord.Guild) else None

    def _resolve_mod_channel(
        self, guild: discord.Guild, mod_channel_id: Optional[int]
    ) -> Optional[discord.TextChannel]:
        """Najde kanál pro logování."""
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
        hide: bool = True,
    ):
        await itx.response.defer(ephemeral=hide)
        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        # Určení role
        target_role = role
        if not target_role and VERIFIED_ROLE_ID:
            target_role = guild.get_role(VERIFIED_ROLE_ID)
        
        if not isinstance(target_role, discord.Role):
            return await itx.followup.send(
                "❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True
            )

        members = [m for m in guild.members if target_role in m.roles and not m.bot]
        bots = [m for m in guild.members if target_role in m.roles and m.bot]

        await itx.followup.send(
            f"ℹ️ **Status re-verifikace**\n"
            f"• Role: {target_role.mention} (ID: {target_role.id})\n"
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
        include_bots: bool = False,
        limit_preview: app_commands.Range[int, 1, 50] = 15,
        hide: bool = True,
    ):
        await itx.response.defer(ephemeral=hide)
        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        target_role = role
        if not target_role and VERIFIED_ROLE_ID:
            target_role = guild.get_role(VERIFIED_ROLE_ID)

        if not isinstance(target_role, discord.Role):
            return await itx.followup.send(
                "❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True
            )

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
        delay_ms="Prodleva mezi členy v ms (min 100ms, doporučeno 500+).",
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
        delay_ms: app_commands.Range[int, 100, 5000] = 500,
        include_bots: bool = False,
        mod_channel: Optional[discord.TextChannel] = None,
        reason: Optional[str] = None,
        dry_run: bool = False,
        hide: bool = True,
    ):
        await itx.response.defer(ephemeral=hide)

        guild = await self._resolve_guild(itx, GUILD_ID)
        if not guild:
            return await itx.followup.send("❌ Nelze určit server (guild).", ephemeral=True)

        target_role = role
        if not target_role and VERIFIED_ROLE_ID:
            target_role = guild.get_role(VERIFIED_ROLE_ID)

        if not isinstance(target_role, discord.Role):
            return await itx.followup.send(
                "❌ Zadej platnou roli nebo nastav VERIFIED_ROLE_ID v configu.", ephemeral=True
            )

        mod_ch = mod_channel or self._resolve_mod_channel(guild, MOD_CHANNEL_ID)
        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE

        # Filtrace kandidátů
        members_all = [m for m in guild.members if target_role in m.roles]
        members: List[discord.Member] = members_all if include_bots else [m for m in members_all if not m.bot]

        if not members:
            return await itx.followup.send("ℹ️ Nikdo s cílovou rolí (po aplikaci filtrů).", ephemeral=True)

        # --- Dry Run ---
        if dry_run:
            sample = ", ".join(m.display_name for m in members[:15])
            more = "" if len(members) <= 15 else f"\n… a dalších **{len(members) - 15}**"
            
            preview_msg = template.format(member='Uzivatel', code=code_final)
            
            return await itx.followup.send(
                f"🧪 **Dry-run**: DM by bylo odesláno **{len(members)}** členům.\n"
                f"• Role: {target_role.mention}\n"
                f"• Delay: {delay_ms} ms\n"
                f"• Ukázka adresátů: {sample}{more}\n"
                f"• Text DM (náhled):\n```\n{preview_msg}\n```",
                ephemeral=True,
            )

        # --- Ostrý Start ---
        await itx.followup.send(
            f"🚀 Spouštím hromadnou re-verifikaci pro **{len(members)}** uživatelů.\n"
            f"⏳ Odhadovaný čas: {len(members) * (delay_ms/1000) / 60:.1f} min.",
            ephemeral=hide
        )

        sent_ok = 0
        sent_fail = 0
        blocked_dms = 0

        # Sekvenční odesílání je pro DMs bezpečnější než asyncio.gather
        # aby se předešlo rate-limitům a spam filtrům Discordu.
        for i, member in enumerate(members):
            msg_text = template.format(member=member.display_name, code=code_final)
            
            try:
                await member.send(msg_text)
                sent_ok += 1
            except discord.Forbidden:
                # Uživatel má vypnuté DMs
                blocked_dms += 1
                sent_fail += 1
            except Exception as e:
                logging.warning(f"⚠️ Nelze poslat DM {member} ({member.id}): {e}")
                sent_fail += 1
            
            # Pauza mezi odesláním (rate limit prevence)
            # Nečekáme po posledním členovi
            if i < len(members) - 1:
                await asyncio.sleep(delay_ms / 1000.0)

        # Log do mod kanálu
        if mod_ch:
            try:
                await mod_ch.send(
                    f"📬 **Re-verifikace Dokončena**\n"
                    f"• Spustil: {itx.user.mention}\n"
                    f"• Role: {target_role.mention}\n"
                    f"• Celkem cílů: **{len(members)}**\n"
                    f"• ✅ Odesláno: **{sent_ok}**\n"
                    f"• ❌ Selhalo: **{sent_fail}** (z toho **{blocked_dms}** má vypnuté DMs)\n"
                    f"{'• Důvod: ' + reason if reason else ''}"
                )
            except Exception as e:
                logging.warning(f"⚠️ Nelze logovat do mod kanálu: {e}")

        # Finální zpráva (pokud nebyla ephemeral, pošleme novou, jinak edit/followup)
        # Protože jsme už odpověděli (defer/send), použijeme followup
        try:
            await itx.followup.send(
                f"✅ Akce dokončena. Odesláno: **{sent_ok}**, Selhalo: **{sent_fail}**.",
                ephemeral=True 
            )
        except Exception:
            pass # Pokud uživatel zahodil interakci, nevadí

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
        hide: bool = True,
    ):
        await itx.response.defer(ephemeral=hide)

        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE
        
        try:
            await member.send(template.format(member=member.display_name, code=code_final))
        except discord.Forbidden:
            return await itx.followup.send(
                f"❌ Uživatel {member.mention} má **zablokované soukromé zprávy** (DMs).", 
                ephemeral=True
            )
        except Exception as e:
            logging.warning(f"⚠️ Nelze poslat DM {member} ({member.id}): {e}")
            return await itx.followup.send("❌ Nastala chyba při odesílání DM.", ephemeral=True)

        await itx.followup.send(f"✅ DM úspěšně odesláno uživateli {member.mention}.", ephemeral=hide)

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
        hide: bool = True,
    ):
        await itx.response.defer(ephemeral=hide)
        code_final = code or VERIFICATION_CODE
        template = dm_text or DEFAULT_DM_TEMPLATE

        try:
            await itx.user.send(template.format(member=itx.user.display_name, code=code_final))
        except discord.Forbidden:
            return await itx.followup.send(
                "❌ Nemohu ti poslat DM. Zkontroluj si nastavení soukromí na tomto serveru.", 
                ephemeral=True
            )
        except Exception as e:
            logging.warning(f"⚠️ Nelze poslat DM iniciátorovi: {e}")
            return await itx.followup.send("❌ Nepodařilo se poslat DM (neznámá chyba).", ephemeral=True)

        await itx.followup.send("📨 Zaslali jsme ti ukázkové DM s re-verifikační zprávou.", ephemeral=hide)


async def setup(bot: commands.Bot):
    """Načtení cogu (discord.py 2.x)."""
    await bot.add_cog(ReverificationCog(bot))