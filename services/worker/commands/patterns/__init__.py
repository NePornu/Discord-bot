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

    @pattern_group.command(name="list", description="Seznam uživatelů s detekovanými vzorci.")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_alerts(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        r = await self._get_redis()
        try:
            # Match: pat:alert_sent:{gid}:{uid}:{pat}
            prefix = f"pat:alert_sent:{self._guild_id}:"
            cursor = "0"
            matches = {}
            
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"{prefix}*", count=1000)
                for k in keys:
                    parts = k.split(":")
                    if len(parts) >= 5:
                        uid = parts[3]
                        pat = parts[4]
                        if uid not in matches:
                            matches[uid] = []
                        matches[uid].append(pat)
                if cursor == 0 or cursor == "0":
                    break

            if not matches:
                await itx.followup.send("✅ Aktuálně nebyly zachyceny žádné podezřelé vzorce.", ephemeral=True)
                return

            embed = discord.Embed(title="🚨 Detekované vzorce chování", color=0xF1C40F)
            description = ""
            for uid, pats in matches.items():
                pats_str = ", ".join([f"`{p}`" for p in pats])
                description += f"• <@{uid}> — {pats_str}\n"

            embed.description = description
            await itx.followup.send(embed=embed, ephemeral=True)
        finally:
            await r.aclose()

    @pattern_group.command(name="info", description="Informace o dostupných vzorcích.")
    @app_commands.checks.has_permissions(administrator=True)
    async def info(self, itx: discord.Interaction):
        categories = {
            "🚨 Krize a Relaps": [
                ("🌋 Zrcadlový relaps", "Nákaza selháním v kanálu (3+ lidi najednou)."),
                ("🔁 Relapsová únava", "Točení se v kruhu ('znovu', 'zase')."),
                ("💥 Explozivní návrat", "Nápor zpráv po dlouhém tichu. Riziko přepálení."),
                ("🕯️ Tiché vyhoření", "Pochybnosti následované náhlým zmizením.")
            ],
            "📊 Chování a Motivace": [
                ("☁️ Falešný vrchol", "Euforické zprávy bez jakékoli metodiky."),
                ("📉 Sémantický útlum", "Zprávy se zkracují na jednoslovné odpovědi."),
                ("🧱 Zdi odvykání", "Pocit stagnace ('stále stejné', 'nevím')."),
                ("🦉 Noční sova", "Většina aktivity mezi 01-04 ráno.")
            ],
            "🤝 Sociální a Reciprocity": [
                ("❓ Nenaplněná reciprocita", "Otázka bez odpovědi více než 6 hodin."),
                ("📢 Poslední monolog", "3+ příspěvky v deníku bez reakce okolí."),
                ("🤝 Vrstevnické pouto", "Silná vazba na parťáka. Pozor na jeho odchod."),
                ("🦸 Nadšený pomocník", "Přílišná koncentrace na pomoc ostatním na úkor sebe.")
            ],
            "📅 Retence a Čas": [
                ("📆 Rytmus 90 dní", "Klesající aktivita u milníků 21, 60, 90 dní."),
                ("📉 Víkendový propad", "Pád aktivity o víkendech o 60%+."),
                ("👋 Jednorázovka", "Pouze 1 zpráva od registrace."),
                ("🏹 Tichý boj", "Návrat po 90+ dnech jedinou zprávou."),
                ("🍂 Sezónní návrat", "Návrat po více než roce.")
            ]
        }
        
        embeds = []
        for cat_name, pats in categories.items():
            embed = discord.Embed(title=cat_name, color=0x3498DB)
            for name, desc in pats:
                embed.add_field(name=name, value=desc, inline=False)
            embeds.append(embed)
        
        await itx.response.send_message(embeds=embeds[:2], ephemeral=True)
        if len(embeds) > 2:
            await itx.followup.send(embeds=embeds[2:], ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PatternDetectorCog(bot))
