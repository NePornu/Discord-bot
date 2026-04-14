import asyncio
import logging
import json
import time
import os
import httpx
from datetime import datetime, timedelta, timezone
import discord
from discord.ext import commands, tasks
from shared.python.redis_client import get_redis_client
from shared.python.config import config
from .common import K_SENTIMENT, get_today
from .ai_service import AIService

logger = logging.getLogger("HealthMonitor")

class CommunityHealthCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._guild_id = config.GUILD_ID
        self.health_pulse_task.start()

    def cog_unload(self):
        self.health_pulse_task.cancel()

    @tasks.loop(hours=6)
    async def health_pulse_task(self):
        """Periodically analyzes community health and trends."""
        # Add initial delay on startup to prevent CPU spikes
        # especially after a restart when everything initializes
        if self.health_pulse_task.current_loop == 0:
            logger.info("Health monitor: Waiting 5 minutes initial delay...")
            await asyncio.sleep(300)

        await self.run_analysis()

    async def run_analysis(self):
        """Performs the actual community health pulse analysis."""
        logger.info("Starting community health pulse analysis...")
        r = await get_redis_client()
        try:
            today = get_today()
            # 1. Aggregate global sentiment for today
            sentiment_summary, active_users = await self._aggregate_global_sentiment(r, today)
            
            if active_users == 0:
                logger.info("Skipping health report: No active users today.")
                return

            # 2. Get a sample of recent critical alerts or trending keywords
            recent_alerts = await self._get_recent_alert_summary(r, today)
            
            # 3. Generate data-driven insights (No AI)
            report = self._get_data_driven_summary(sentiment_summary, active_users, recent_alerts)
            
            # 4. Post to alert channel
            await self._post_health_report(report, sentiment_summary, active_users)
                
        except Exception as e:
            logger.error(f"Health pulse analysis error: {e}")
        finally:
            await r.aclose()

    async def _aggregate_global_sentiment(self, r, today) -> tuple[dict, int]:
        prefix = f"pat:sentiment:{self._guild_id}:*:{today}"
        cursor = "0"
        totals = {"POSITIVE": 0, "NEUTRAL": 0, "NEGATIVE": 0, "URGENT": 0}
        uids = set()
        
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=prefix, count=1000)
            for k in keys:
                # Key format: pat:sentiment:gid:uid:date
                parts = k.split(":")
                if len(parts) >= 5:
                    uids.add(parts[3])
                
                data = await r.hgetall(k)
                for s, c in data.items():
                    s_up = s.upper()
                    if s_up in totals:
                        totals[s_up] += int(c)
            if cursor == 0 or cursor == "0" or cursor == 0: break
            
        return totals, len(uids)

    async def _get_recent_alert_summary(self, r, today) -> str:
        # Simplified: just count common pattern alerts from last 24h
        prefix = f"pat:alert_sent:{self._guild_id}:*"
        cursor = "0"
        patterns = {}
        
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=prefix, count=1000)
            for k in keys:
                pname = k.split(":")[-1]
                patterns[pname] = patterns.get(pname, 0) + 1
            if cursor == 0 or cursor == "0": break
            
        summary = ", ".join([f"{p}: {c}x" for p, c in sorted(patterns.items(), key=lambda x: x[1], reverse=True)[:5]])
        return summary or "Žádné výrazné vzorce."

    def _get_data_driven_summary(self, sentiment: dict, active_users: int, patterns: str) -> str:
        total = sum(sentiment.values())
        if total == 0:
            return "Dnes zatím nebyla zaznamenána žádná aktivita k analýze."
        
        # Calculate dominant sentiment
        sorted_sent = sorted(sentiment.items(), key=lambda x: x[1], reverse=True)
        dominant, count = sorted_sent[0]
        
        # Crisis check
        urgent = sentiment.get("URGENT", 0)
        neg = sentiment.get("NEGATIVE", 0)
        crisis_ratio = (urgent + neg) / total if total > 0 else 0
        
        moods = {
            "POSITIVE": "velmi pozitivní",
            "NEUTRAL": "klidná a vyvážená",
            "NEGATIVE": "napjatá",
            "URGENT": "kritická"
        }
        
        summary = f"Dnes je na serveru aktivních **{active_users} uživatelů**, kteří vyprodukovali **{total} zpráv** k analýze. "
        summary += f"Celková atmosféra se zdá být **{moods.get(dominant, 'stabilní')}**. "
        
        if urgent > 0:
            summary += f"⚠️ Bylo zachyceno **{urgent} zpráv s krizovým obsahem**, které vyžadují pozornost moderátorů. "
        elif neg > total * 0.3:
             summary += "📉 Pozorujeme zvýšený výskyt negativních emocí v diskusích. "
             
        if patterns != "Žádné výrazné vzorce.":
            summary += f"\n\n**Hlavní trendy:** {patterns}"
            
        return summary

    async def _post_health_report(self, report: str, sentiment: dict, active_users: int):
        guild = self.bot.get_guild(self._guild_id)
        if not guild: return
        
        channel = guild.get_channel(config.PATTERN_ALERT_CHANNEL_ID)
        if not channel: return
        
        embed = discord.Embed(
            title="💓 Komunitní Puls (AI Přehled)",
            description=report,
            color=0x2ECC71 if sum(sentiment.values()) > 0 else 0x95A5A6,
            timestamp=datetime.now(timezone.utc)
        )
        
        total = sum(sentiment.values())
        stats_text = (
            f"👥 **Aktivní uživatelé:** {active_users}\n"
            f"✉️ **Zpráv k analýze:** {total}\n"
            f"──────────────────\n"
            f"😊 Kladné: {sentiment['POSITIVE']}\n"
            f"😐 Neutrální: {sentiment['NEUTRAL']}\n"
            f"😔 Záporné: {sentiment['NEGATIVE']}\n"
            f"🚨 Krize: {sentiment['URGENT']}"
        )
        embed.add_field(name="📊 Denní statistiky", value=stats_text, inline=False)
        embed.set_footer(text="Periodický přehled zdraví serveru • Lokální AI (Llama 3.2)")
        
        await channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(CommunityHealthCog(bot))
