# commands/purge.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import re
from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple

import discord
from discord import app_commands, Interaction
from discord.ext import commands

MESSAGE_LINK_RE = re.compile(
    r"(?:https?://)?(?:ptb\.|canary\.)?discord(?:app)?\.com/channels/(?P<guild>\d+)/(?P<channel>\d+)/(?P<message>\d+)"
)

def parse_message_ref(s: Optional[str]) -> Optional[int]:
    """Vrátí message_id ze stringu (čisté ID nebo celý odkaz)."""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    m = MESSAGE_LINK_RE.search(s)
    if m:
        return int(m.group("message"))
    return None

def is_older_than_14d(msg: discord.Message) -> bool:
    return (datetime.now(timezone.utc) - msg.created_at) > timedelta(days=14)

class PurgeCog(commands.Cog):
    """/purge – mazání zpráv s filtry a náhledem (dry-run)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    purge_group = app_commands.Group(name="purge", description="Mazání zpráv s filtry")

    @purge_group.command(name="run", description="Smaže přesně N zpráv dle filtrů.")
    @app_commands.describe(
        amount="Počet zpráv ke smazání (1–100)",
        user="Omezit na konkrétního uživatele",
        word="Filtrovat podle výskytu slova/řetězce (case-insensitive)",
        bots_only="Mazat jen zprávy od botů",
        include_pins="Mazat i připnuté zprávy (jinak se přeskočí)",
        before="Hledej jen před touto zprávou (ID nebo odkaz)",
        after="Hledej jen po této zprávě (ID nebo odkaz)",
        dry_run="Jen ukázat, co by se smazalo (nic nemaže)",
        hide="Odpověď jen pro tebe (ephemeral)",
        reason="Důvod (pošle se do CONSOLE kanálu, pokud je nastaven)"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_run(
        self,
        itx: Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: Optional[discord.User] = None,
        word: Optional[str] = None,
        bots_only: Optional[bool] = False,
        include_pins: Optional[bool] = False,
        before: Optional[str] = None,
        after: Optional[str] = None,
        dry_run: Optional[bool] = False,
        hide: Optional[bool] = True,
        reason: Optional[str] = None,
    ):
        """Smaže přesně `amount` zpráv vyhovujících filtrům. Limitujeme průchod historie na ~2000 zpráv pro výkon."""
        await itx.response.defer(ephemeral=hide)

        channel = itx.channel
        if not isinstance(channel, discord.TextChannel):
            return await itx.followup.send("❌ Tento příkaz lze použít jen v textovém kanálu.", ephemeral=True)

        before_id = parse_message_ref(before)
        after_id = parse_message_ref(after)

        # Připrav filtrační funkci
        word_lc = (word or "").lower()

        def check_msg(msg: discord.Message) -> bool:
            if msg.id == itx.id:
                return False
            if not include_pins and msg.pinned:
                return False
            if bots_only and not msg.author.bot:
                return False
            if user and msg.author.id != user.id:
                return False
            if word_lc and word_lc not in msg.content.lower():
                return False
            return True

        # Upravit parametry průchodu historie
        kwargs = {}
        if before_id:
            kwargs["before"] = discord.Object(id=before_id)
        if after_id:
            kwargs["after"] = discord.Object(id=after_id)

        # 1) Najdi přesně amount kandidátů (max ~2000 zpráv k prohledání)
        candidates: List[discord.Message] = []
        found = 0
        scanned = 0
        async for msg in channel.history(limit=2000, oldest_first=False, **kwargs):
            scanned += 1
            if check_msg(msg):
                candidates.append(msg)
                found += 1
                if found >= amount:
                    break

        if not candidates:
            return await itx.followup.send("ℹ️ Nenašel jsem žádné zprávy odpovídající filtrům.", ephemeral=True)

        # 2) Dry-run náhled
        if dry_run:
            preview = "\n".join(
                f"- {m.id} • {m.author.display_name}: {m.content[:60].replace('`','´')}{'…' if len(m.content) > 60 else ''}"
                for m in candidates[:10]
            )
            more = "" if len(candidates) <= 10 else f"\n… a dalších {len(candidates)-10}"
            text = (
                f"🧪 **Dry-run náhled**\n"
                f"Kanál: {channel.mention}\n"
                f"Požadováno: **{amount}**, Nalezeno: **{len(candidates)}**, Prohledáno: **{scanned}** zpráv\n"
                f"Filtry: user={user.mention if user else '-'}, word={word or '-'}, bots_only={bots_only}, include_pins={include_pins}\n"
                f"Rozsah: before={before_id or '-'}, after={after_id or '-'}\n\n"
                f"**Prvních {min(10, len(candidates))} zpráv ke smazání:**\n{preview}{more}"
            )
            return await itx.followup.send(text, ephemeral=True)

        # 3) Reálné mazání – rozdělíme na <14 dní (bulk) a >=14 dní (po jedné)
        recent: List[discord.Message] = []
        older: List[discord.Message] = []
        for m in candidates:
            (older if is_older_than_14d(m) else recent).append(m)

        deleted_total = 0
        # Bulk delete recent (Discord smaže max 100 naráz; máme <= amount <= 100)
        if recent:
            try:
                deleted = await channel.delete_messages(recent)
                # delete_messages může vrátit None (závisí na verzi); fallback na len(recent)
                deleted_total += len(deleted) if isinstance(deleted, list) else len(recent)
            except discord.Forbidden:
                return await itx.followup.send("❌ Nemám oprávnění mazat zprávy (bulk).", ephemeral=True)
            except discord.HTTPException as e:
                return await itx.followup.send(f"❌ Chyba při bulk mazání: {e}", ephemeral=True)

        # Individuální mazání starých
        for m in older:
            try:
                await m.delete()
                deleted_total += 1
                await asyncio.sleep(0.3)  # šetrně proti rate-limitům
            except discord.Forbidden:
                return await itx.followup.send("❌ Nemám oprávnění smazat některé starší zprávy.", ephemeral=True)
            except discord.HTTPException:
                # pokračuj, i kdyby jedna selhala
                continue

        # 4) Log do CONSOLE_CHANNEL_ID (pokud je k dispozici)
        console_id = getattr(self.bot, "CONSOLE_CHANNEL_ID", None)
        if console_id and reason:
            try:
                ch = self.bot.get_channel(console_id)
                if isinstance(ch, discord.TextChannel):
                    await ch.send(
                        f"🧹 **PURGE** v {channel.mention} • {itx.user.mention}\n"
                        f"• Smazáno: **{deleted_total}** (požadováno {amount})\n"
                        f"• Filtry: user={user.mention if user else '-'}, word={word or '-'}, bots_only={bots_only}, include_pins={include_pins}\n"
                        f"• Rozsah: before={before_id or '-'}, after={after_id or '-'}\n"
                        f"• Důvod: {reason}"
                    )
            except Exception:
                pass

        await itx.followup.send(
            f"✅ Smazáno **{deleted_total}** zpráv (požadováno {amount}).\n"
            f"_Pozn.: Zprávy starší než 14 dní byly mazány jednotlivě._",
            ephemeral=hide,
        )

    @purge_group.command(name="preview", description="Jen náhled (dry-run), co by se smazalo.")
    @app_commands.describe(
        amount="Počet zpráv k výběru (1–100)",
        user="Omezit na konkrétního uživatele",
        word="Filtrovat podle výskytu slova/řetězce",
        bots_only="Jen zprávy od botů",
        include_pins="Zahrnout i připnuté zprávy",
        before="Hledej jen před touto zprávou (ID/odkaz)",
        after="Hledej jen po této zprávě (ID/odkaz)",
        hide="Ephemeral odpověď"
    )
    @app_commands.checks.has_permissions(manage_messages=True)
    async def purge_preview(
        self,
        itx: Interaction,
        amount: app_commands.Range[int, 1, 100],
        user: Optional[discord.User] = None,
        word: Optional[str] = None,
        bots_only: Optional[bool] = False,
        include_pins: Optional[bool] = False,
        before: Optional[str] = None,
        after: Optional[str] = None,
        hide: Optional[bool] = True,
    ):
        # Přesměruj na run s dry_run=True
        await self.purge_run.callback(
            self,
            itx,
            amount=amount,
            user=user,
            word=word,
            bots_only=bots_only,
            include_pins=include_pins,
            before=before,
            after=after,
            dry_run=True,
            hide=hide,
            reason=None,
        )

async def setup(bot: commands.Bot):
    await bot.add_cog(PurgeCog(bot))

