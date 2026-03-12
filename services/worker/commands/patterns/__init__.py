import time
import logging
from datetime import datetime, timezone
from typing import List, Dict, Set

import discord
from discord import app_commands
from discord.ext import commands

from shared.python.config import config
from shared.python.redis_client import get_redis_client

from .common import K_LAST_SCAN, is_staff
from .signals import PatternSignals
from .detectors import PatternDetectors
from .scanner import PatternScanner
from .alerts import PatternAlerts

logger = logging.getLogger("PatternDetector")

class PatternDetectorCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._guild_id = config.GUILD_ID
        
        # Initialize sub-components
        self.alerts = PatternAlerts(bot, self._guild_id)
        self.detectors = PatternDetectors(self._guild_id)
        self.scanner = PatternScanner(bot, self._guild_id, self._get_redis, self.detectors, self.alerts)
        self.signals = PatternSignals(bot, self._guild_id, self._get_redis)
        
        # Register signals as a listener by adding the cog
        # Actually, we can just delegate from the main Cog to keep it simple
        self.bot.add_listener(self.signals.on_message)
        self.bot.add_listener(self.signals.on_message_delete)
        self.bot.add_listener(self.signals.on_raw_message_edit)
        self.bot.add_listener(self.signals.on_member_join)

    async def _get_redis(self):
        return await get_redis_client()

    def cog_unload(self):
        self.scanner.cog_unload()

    # Slash Command Group
    pattern_group = app_commands.Group(name="patterns", description="Detekce vzorců chování")

    @pattern_group.command(name="check", description="Ručně zkontrolovat vzorce u konkrétního uživatele.")
    @app_commands.describe(user="Uživatel ke kontrole")
    @app_commands.checks.has_permissions(administrator=True)
    async def check_user(self, itx: discord.Interaction, user: discord.Member):
        if is_staff(user):
            await itx.response.send_message(f"⚠️ **{user.display_name}** je členem týmu.", ephemeral=True)
            return

        await itx.response.defer(ephemeral=True)
        r = await self._get_redis()
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y%m%d")

        try:
            alerts = await self.detectors.scan_user(r, self._guild_id, user.id, now, today)
            stats_7d = await self.detectors.get_user_msg_stats(r, self._guild_id, user.id, 7)
            stats_30d = await self.detectors.get_user_msg_stats(r, self._guild_id, user.id, 30)
            days_inactive = await self.detectors.days_since_last_activity(r, self._guild_id, user.id, 180)
            affinities = await self.detectors.analyze_user_affinity(r, self._guild_id, user.id, now, today, stats_7d, stats_30d, days_inactive)

            embed = discord.Embed(title=f"🔍 Diagnostika: {user.display_name}", color=0x5865F2, timestamp=now)
            embed.set_thumbnail(url=user.display_avatar.url)
            
            act_val = f"**7 dní:** {stats_7d['msg_count']} zpráv\n**30 dní:** {stats_30d['msg_count']} zpráv"
            embed.add_field(name="📊 Statistiky", value=act_val, inline=True)

            if affinities:
                aff_text = "\n".join([f"{af['emoji']} **{af['name']}** `{af['score']}%`" for af in affinities])
                embed.add_field(name="🎯 Afinita", value=aff_text, inline=False)
            
            if alerts:
                pat_text = "\n".join([f"**{a.emoji} {a.pattern_name}**" for a in alerts[:5]])
                embed.add_field(name=f"🚨 Poplachy", value=pat_text, inline=False)

            await itx.followup.send(embed=embed, ephemeral=True)
        finally:
            await r.aclose()

    @pattern_group.command(name="status", description="Zobrazí stav pattern detection enginu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        r = await self._get_redis()
        try:
            last_scan = await r.get(K_LAST_SCAN(self._guild_id))
            last_val = "Nikdy" if not last_scan else datetime.fromtimestamp(int(last_scan), tz=timezone.utc).strftime("%d.%m.%Y %H:%M")
            
            embed = discord.Embed(title="⚙️ Pattern Engine", color=0x2ECC71)
            embed.add_field(name="📊 Stav", value="✅ Běží", inline=True)
            embed.add_field(name="🕐 Poslední scan", value=last_val, inline=True)
            await itx.followup.send(embed=embed, ephemeral=True)
        finally:
            await r.aclose()

async def setup(bot: commands.Bot):
    await bot.add_cog(PatternDetectorCog(bot))
