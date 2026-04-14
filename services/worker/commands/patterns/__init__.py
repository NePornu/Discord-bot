import time
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Set

import discord
from discord import app_commands
from discord.ext import commands

from shared.python.config import config
from shared.python.redis_client import get_redis_client

from .common import K_LAST_SCAN, K_FIRST, is_staff
from .signals import PatternSignals
from .detectors import PatternDetectors
from .scanner import PatternScanner
from .alerts import PatternAlerts, DiagnosticResultView
from .sentiment_engine import SentimentEngine
from .health_monitor import CommunityHealthCog

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
        self.sentiment = SentimentEngine(bot, self._guild_id)
        self.health = CommunityHealthCog(bot)
        
        # Register Persistent Views
        from .alerts import ModeratorAssistantView
        self.bot.add_view(ModeratorAssistantView())
        
        # Register signals as a listener by adding the cog
        # Actually, we can just delegate from the main Cog to keep it simple
        self.bot.add_listener(self.signals.on_message)
        self.bot.add_listener(self.signals.on_message_delete)
        self.bot.add_listener(self.signals.on_raw_message_edit)
        self.bot.add_listener(self.signals.on_member_join)
        self.bot.add_listener(self.sentiment.on_message)

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
            embed = await self.detectors.build_diagnostic_embed(
                r, user.id, user.mention, user.display_name, user.display_avatar.url
            )
            # Add view with "Open Case" button
            view = DiagnosticResultView(user.id, self._guild_id, self.alerts, self.detectors)
            await itx.followup.send(embed=embed, view=view, ephemeral=True)
        finally:
            await r.aclose()

    @pattern_group.command(name="discourse_report", description="Generovat diagnostický přehled pro uživatele na Discourse.")
    @app_commands.describe(user_id="Discourse ID uživatele")
    @app_commands.checks.has_permissions(administrator=True)
    async def discourse_report(self, itx: discord.Interaction, user_id: int):
        await itx.response.defer(ephemeral=True)
        
        # We use a dummy alert to trigger the manual report
        from .common import PatternAlert
        dummy_alert = PatternAlert(
            pattern_name="Manuální prověření",
            user_id=user_id,
            risk_level="info",
            description="Tento přehled byl vygenerován na žádost moderátora.",
            recommended_action="Zhodnotit celkový profil a aktivitu uživatele.",
            emoji="👤"
        )
        
        try:
            await self.alerts.send_discourse_alert(user_id, [dummy_alert])
            await itx.followup.send(f"✅ Diagnostický přehled pro uživatele `{user_id}` byl vygenerován na Discourse.", ephemeral=True)
        except Exception as e:
            logger.error(f"Manual discourse report failed: {e}")
            await itx.followup.send(f"❌ Selhalo generování přehledu: {e}", ephemeral=True)

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
            "📅 Retence a Metodika": [
                ("🛡️ Survival Metoda", "Aktivní zmínky o prvcích Survival metody."),
                ("📝 Absence plánu", "Aktivní 14+ dní bez zmínky o krizovém plánu."),
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

    @pattern_group.command(name="reset-all", description="Kritický reset: Smaže všechny aktivní karty a historii detekcí.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_all(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        r = await self._get_redis()
        gid = self._guild_id
        
        try:
            # 1. Thread Cleanup
            thread_prefix = f"pat:thread:{gid}:"
            cursor = "0"
            thread_keys = []
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"{thread_prefix}*", count=1000)
                thread_keys.extend(keys)
                if cursor == 0 or cursor == "0": break
            
            deleted_threads = 0
            for k in thread_keys:
                tid_str = await r.get(k)
                if tid_str:
                    try:
                        tid = int(tid_str)
                        thread = itx.guild.get_thread(tid)
                        if not thread:
                            try: thread = await itx.guild.fetch_channel(tid)
                            except: pass
                        
                        if thread and isinstance(thread, discord.Thread):
                            await thread.delete()
                            deleted_threads += 1
                    except Exception as e:
                        logger.warning(f"Failed to delete thread {tid_str}: {e}")
                
                await r.delete(k)
                if tid_str:
                    from .common import K_THREAD_UID
                    await r.delete(K_THREAD_UID(int(tid_str)))

            # 2. Alert History Cleanup
            alert_prefix = f"pat:alert_sent:{gid}:"
            cursor = "0"
            alert_keys = []
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"{alert_prefix}*", count=1000)
                alert_keys.extend(keys)
                if cursor == 0 or cursor == "0": break
            
            if alert_keys:
                # Delete in chunks to avoid large command issues
                for i in range(0, len(alert_keys), 100):
                    chunk = alert_keys[i:i+100]
                    await r.delete(*chunk)

            await itx.followup.send(
                f"✅ **Reset dokončen.**\n"
                f"- Smazáno aktivních karet (vláken): `{deleted_threads}`\n"
                f"- Vymazáno záznamů o historii detekcí: `{len(alert_keys)}`", 
                ephemeral=True
            )
        except Exception as e:
            logger.error(f"Error in reset_all: {e}")
            await itx.followup.send(f"❌ Nastala chyba při resetu: {e}", ephemeral=True)
        finally:
            await r.aclose()

    @pattern_group.command(name="pulse", description="Okamžitě vygenerovat a odeslat přehled zdraví komunity.")
    @app_commands.checks.has_permissions(administrator=True)
    async def manual_pulse(self, itx: discord.Interaction):
        await itx.response.send_message("⏳ Generuji aktuální přehled zdraví komunity...", ephemeral=True)
        try:
            # Call the refactored analysis method for immediate results
            await self.health.run_analysis()
        except Exception as e:
            logger.error(f"Manual pulse failed: {e}")
            await itx.followup.send(f"❌ Selhalo generování přehledu: {e}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(PatternDetectorCog(bot))
