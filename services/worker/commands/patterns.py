"""
PatternDetectorCog — Behavioral pattern detection engine for NePornu community.
Detects 27 user behavior patterns and alerts mentors via Discord embeds.

Architecture:
  1. Real-time signal collectors (on_message, on_message_delete, on_raw_message_edit)
  2. Periodic pattern scanner (every 15 min)
  3. Alert system with deduplication (24h cooldown per pattern per user)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Set, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks

from shared.python.config import config
from shared.python.redis_client import get_redis_client

logger = logging.getLogger("PatternDetector")

from shared.python.pattern_logic import KEYWORD_GROUPS, count_keywords, count_words, normalize_text


# ─── Pattern Alert ────────────────────────────────────────────────────

@dataclass
class PatternAlert:
    pattern_name: str
    user_id: int
    risk_level: str  # "critical", "warning", "info"
    description: str
    recommended_action: str
    emoji: str = "🔍"

    @property
    def color(self) -> int:
        return {"critical": 0xFF0000, "warning": 0xFFA500, "info": 0x3498DB}[self.risk_level]

    @property
    def level_label(self) -> str:
        return {"critical": "🔴 KRITICKÉ", "warning": "🟡 VAROVÁNÍ", "info": "🟢 INFO"}[self.risk_level]


# ─── Redis Helper Keys ───────────────────────────────────────────────

def K_KW(gid, uid, date, group):  return f"pat:kw:{gid}:{uid}:{date}:{group}"
def K_MSG(gid, uid, date):        return f"pat:msg:{gid}:{uid}:{date}"
def K_DEL(gid, uid, date):        return f"pat:del:{gid}:{uid}:{date}"
def K_EDIT(gid, uid, date):       return f"pat:edit:{gid}:{uid}:{date}"
def K_DIARY(gid, uid):            return f"pat:diary_unanswered:{gid}:{uid}"
def K_REPLY(gid, a, b):           return f"pat:reply_pair:{gid}:{min(a,b)}:{max(a,b)}"
def K_FIRST(gid, uid):            return f"pat:first_msg:{gid}:{uid}"
def K_ALERT(gid, uid, pat):       return f"pat:alert_sent:{gid}:{uid}:{pat}"
def K_JOIN(gid, uid):             return f"pat:user_join:{gid}:{uid}"
def K_LAST_SCAN(gid):             return f"pat:last_scan:{gid}"
def K_QUESTION(gid, uid, mid):    return f"pat:question:{gid}:{uid}:{mid}"

PAT_TTL = 730 * 86400  # 2 years default TTL (for long-term pattern analysis)


# ─── Main Cog ────────────────────────────────────────────────────────

class PatternDetectorCog(commands.Cog):
    """Behavioral pattern detection engine for the NePornu community."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._alert_channel: Optional[discord.TextChannel] = None
        self._diary_channel_ids: Set[int] = set()
        self._guild_id = config.GUILD_ID
        logger.info("PatternDetectorCog initialized")

    async def cog_load(self):
        self.pattern_scanner.start()
        logger.info("Pattern scanner task started")

    async def cog_unload(self):
        self.pattern_scanner.cancel()

    def _is_diary_channel(self, channel: discord.TextChannel) -> bool:
        """Check if a channel is a diary channel by name."""
        name = channel.name.lower()
        return any(dn in name for dn in config.DIARY_CHANNEL_NAMES)

    async def _get_redis(self):
        return await get_redis_client()

    async def _get_alert_channel(self) -> Optional[discord.TextChannel]:
        if self._alert_channel:
            return self._alert_channel
        guild = self.bot.get_guild(self._guild_id)
        if guild:
            self._alert_channel = guild.get_channel(config.PATTERN_ALERT_CHANNEL_ID)
        return self._alert_channel

    def _is_staff(self, member: discord.Member) -> bool:
        """Check if a member is a staff/worker (Admin, Mod, Mentor, etc.)."""
        # Administrators are always staff
        if member.guild_permissions.administrator:
            return True
        
        # Substring matching for roles
        staff_keywords = {
            "mentor", "moderátor", "admin", "průvodce", "tým", "koordinátor", 
            "pracovník", "vedení", "kouč", "lektor", "expert", "specialista", "správce"
        }
        return any(
            any(kw in role.name.lower() for kw in staff_keywords)
            for role in member.roles
        )

    def _today(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%d")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LAYER 1: Real-time Signal Collectors
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.guild.id != self._guild_id:
            return
            
        # Skip workers / staff
        if isinstance(message.author, discord.Member) and self._is_staff(message.author):
            return

        r = await self._get_redis()
        try:
            gid = message.guild.id
            uid = message.author.id
            today = self._today()
            text = message.content or ""
            wc = count_words(text)
            is_reply = message.reference is not None
            mentions = len(message.mentions)

            pipe = r.pipeline()

            # --- Aggregate message stats ---
            msg_key = K_MSG(gid, uid, today)
            pipe.hincrby(msg_key, "word_count", wc)
            pipe.hincrby(msg_key, "msg_count", 1)
            pipe.hincrby(msg_key, "char_count", len(text))
            if is_reply:
                pipe.hincrby(msg_key, "reply_count", 1)
            if mentions > 0:
                pipe.hincrby(msg_key, "mention_count", mentions)
            pipe.expire(msg_key, PAT_TTL)

            # --- Keyword scanning ---
            if len(text) > 3:
                for group in KEYWORD_GROUPS:
                    hits = count_keywords(text, group)
                    if hits > 0:
                        kw_key = K_KW(gid, uid, today, group)
                        pipe.incrby(kw_key, hits)
                        pipe.expire(kw_key, PAT_TTL)

            # --- First message tracking ---
            first_key = K_FIRST(gid, uid)
            pipe.hsetnx(first_key, "msg_id", str(message.id))
            pipe.hsetnx(first_key, "timestamp", str(int(message.created_at.timestamp())))
            pipe.hsetnx(first_key, "channel_id", str(message.channel.id))
            pipe.expire(first_key, PAT_TTL)

            # --- Reply-pair tracking ---
            if is_reply and message.reference.message_id:
                try:
                    ref_msg = message.reference.cached_message
                    if ref_msg is None:
                        # Try to fetch from channel
                        try:
                            ref_msg = await message.channel.fetch_message(message.reference.message_id)
                        except Exception:
                            ref_msg = None
                    if ref_msg and not ref_msg.author.bot:
                        reply_key = K_REPLY(gid, uid, ref_msg.author.id)
                        pipe.incr(reply_key)
                        pipe.expire(reply_key, 30 * 86400)
                except Exception:
                    pass

            # --- Diary unanswered tracking ---
            if self._is_diary_channel(message.channel):
                if is_reply and message.reference.message_id:
                    # This is a reply in diary — mark the parent as answered
                    try:
                        ref_msg = message.reference.cached_message
                        if ref_msg is None:
                            try:
                                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                            except Exception:
                                ref_msg = None
                        if ref_msg and ref_msg.author.id != uid:
                            # Someone replied to a diary post — remove from unanswered
                            diary_key = K_DIARY(gid, ref_msg.author.id)
                            pipe.lrem(diary_key, 0, str(ref_msg.id))
                    except Exception:
                        pass
                else:
                    # Original diary post — add to unanswered list
                    diary_key = K_DIARY(gid, uid)
                    entry = json.dumps({"msg_id": str(message.id), "ts": int(message.created_at.timestamp())})
                    pipe.lpush(diary_key, entry)
                    pipe.ltrim(diary_key, 0, 9)  # Keep last 10
                    pipe.expire(diary_key, PAT_TTL)

            # --- Question tracking (messages ending with ?) ---
            if text.rstrip().endswith("?") and len(text) > 10:
                q_key = K_QUESTION(gid, uid, message.id)
                pipe.set(q_key, str(int(message.created_at.timestamp())), ex=24 * 3600)

            # --- Join date tracking ---
            if isinstance(message.author, discord.Member) and message.author.joined_at:
                join_key = K_JOIN(gid, uid)
                pipe.setnx(join_key, str(int(message.author.joined_at.timestamp())))
                pipe.expire(join_key, PAT_TTL)

            # --- Hour tracking for Noční sova ---
            hour = message.created_at.hour
            hour_key = f"pat:hour:{gid}:{uid}:{today}"
            pipe.hincrby(hour_key, str(hour), 1)
            pipe.expire(hour_key, PAT_TTL)

            await pipe.execute()

        except Exception as e:
            logger.error(f"on_message signal error: {e}")
        finally:
            await r.close()

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.author or message.author.bot or not message.guild:
            return
        if message.guild.id != self._guild_id:
            return
        try:
            r = await self._get_redis()
            key = K_DEL(message.guild.id, message.author.id, self._today())
            await r.incr(key)
            await r.expire(key, PAT_TTL)
            await r.close()
        except Exception as e:
            logger.error(f"on_message_delete signal error: {e}")

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if not payload.guild_id or payload.guild_id != self._guild_id:
            return
        # Payload may not have author info if message not cached
        data = payload.data
        author = data.get("author", {})
        if author.get("bot", False):
            return
        uid = int(author.get("id", 0))
        if uid == 0:
            return
        try:
            r = await self._get_redis()
            key = K_EDIT(payload.guild_id, uid, self._today())
            await r.incr(key)
            await r.expire(key, PAT_TTL)
            await r.close()
        except Exception as e:
            logger.error(f"on_raw_message_edit signal error: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if os.getenv("BOT_LITE_MODE") == "1":
            return
        if member.bot or member.guild.id != self._guild_id:
            return
        try:
            r = await self._get_redis()
            join_key = K_JOIN(member.guild.id, member.id)
            await r.set(join_key, str(int(member.joined_at.timestamp())), ex=PAT_TTL)
            await r.close()
        except Exception as e:
            logger.error(f"on_member_join signal error: {e}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LAYER 2: Periodic Pattern Scanner
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @tasks.loop(minutes=config.PATTERN_SCAN_INTERVAL_MINUTES)
    async def pattern_scanner(self):
        try:
            r = await self._get_redis()
            gid = self._guild_id
            alerts: List[PatternAlert] = []

            # 0. Identify staff to skip
            staff_ids = set()
            guild = self.bot.get_guild(gid)
            if guild:
                for member in guild.members:
                    if self._is_staff(member):
                        staff_ids.add(member.id)
            
            # 1. Collect all known user IDs from recent message data
            user_ids = set()
            cursor = "0"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"pat:msg:{gid}:*", count=500)
                for k in keys:
                    parts = k.split(":")
                    if len(parts) >= 4:
                        try:
                            user_ids.add(int(parts[3]))
                        except ValueError:
                            pass
                if cursor == 0 or cursor == "0":
                    break

            # Also check user_daily stats for users with no pattern data yet
            cursor2 = "0"
            while True:
                cursor2, keys2 = await r.scan(cursor=cursor2, match=f"stats:user_daily:{gid}:*", count=500)
                for k in keys2:
                    members = await r.zrange(k, 0, -1)
                    for m in members:
                        try:
                            user_ids.add(int(m))
                        except ValueError:
                            pass
                if cursor2 == 0 or cursor2 == "0":
                    break

            now = datetime.now(timezone.utc)
            today = self._today()

            for uid in user_ids:
                if uid in staff_ids:
                    continue
                try:
                    user_alerts = await self._scan_user(r, gid, uid, now, today)
                    alerts.extend(user_alerts)
                except Exception as e:
                    logger.error(f"Error scanning user {uid}: {e}")

            # Run group-level detectors
            try:
                group_alerts = await self._scan_group_patterns(r, gid, now, today, user_ids)
                alerts.extend(group_alerts)
            except Exception as e:
                logger.error(f"Error in group pattern scan: {e}")

            # Send alerts (with dedup)
            sent_count = 0
            for alert in alerts:
                if await self._should_send_alert(r, gid, alert):
                    await self._send_alert(alert)
                    await self._mark_alert_sent(r, gid, alert)
                    sent_count += 1

            # Update last scan timestamp
            await r.set(K_LAST_SCAN(gid), str(int(now.timestamp())), ex=86400)
            await r.close()

            if sent_count > 0:
                logger.info(f"Pattern scan: {len(user_ids)} users, {sent_count} alerts sent")

        except Exception as e:
            logger.error(f"Pattern scanner error: {e}")

    @pattern_scanner.before_loop
    async def _before_scanner(self):
        await self.bot.wait_until_ready()
        # Wait a bit for other cogs to load
        await asyncio.sleep(30)

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LAYER 3: Individual Pattern Detectors
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _get_user_msg_stats(self, r, gid: int, uid: int, days: int) -> Dict:
        """Get aggregated message stats for a user over N days."""
        now = datetime.now(timezone.utc)
        total = {"word_count": 0, "msg_count": 0, "char_count": 0,
                 "reply_count": 0, "mention_count": 0, "days_active": 0}
        daily_counts = []

        for i in range(days):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            data = await r.hgetall(K_MSG(gid, uid, d))
            if data:
                mc = int(data.get("msg_count", 0))
                total["word_count"] += int(data.get("word_count", 0))
                total["msg_count"] += mc
                total["char_count"] += int(data.get("char_count", 0))
                total["reply_count"] += int(data.get("reply_count", 0))
                total["mention_count"] += int(data.get("mention_count", 0))
                if mc > 0:
                    total["days_active"] += 1
                daily_counts.append(mc)
            else:
                daily_counts.append(0)

        total["daily_counts"] = daily_counts
        total["avg_words_per_msg"] = (
            total["word_count"] / total["msg_count"]
            if total["msg_count"] > 0 else 0
        )
        return total

    async def _get_keyword_count(self, r, gid: int, uid: int, group: str, days: int) -> int:
        """Get total keyword count for a group over N days."""
        now = datetime.now(timezone.utc)
        total = 0
        for i in range(days):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            val = await r.get(K_KW(gid, uid, d, group))
            if val:
                total += int(val)
        return total

    async def _get_user_daily_total(self, r, gid: int, uid: int, date_str: str) -> int:
        """Get user's total messages for a specific day from stats:user_daily."""
        score = await r.zscore(f"stats:user_daily:{gid}:{date_str}", str(uid))
        return int(score) if score else 0

    async def _days_since_last_activity(self, r, gid: int, uid: int, max_lookback: int = 365) -> int:
        """How many days since user's last message."""
        now = datetime.now(timezone.utc)
        for i in range(max_lookback):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            count = await self._get_user_daily_total(r, gid, uid, d)
            if count > 0:
                return i
        return max_lookback

    async def _get_join_days(self, r, gid: int, uid: int) -> Optional[int]:
        """Days since user joined the server."""
        ts_str = await r.get(K_JOIN(gid, uid))
        if ts_str:
            join_ts = int(ts_str)
            return (int(time.time()) - join_ts) // 86400
        return None

    async def _scan_user(self, r, gid: int, uid: int, now: datetime, today: str) -> List[PatternAlert]:
        """Run all per-user pattern detectors."""
        alerts = []

        stats_7d = await self._get_user_msg_stats(r, gid, uid, 7)
        stats_30d = await self._get_user_msg_stats(r, gid, uid, 30)
        days_inactive = await self._days_since_last_activity(r, gid, uid, 180)
        join_days = await self._get_join_days(r, gid, uid)

        # ── 1. Jednorázovka ──
        if stats_30d["msg_count"] == 1 and days_inactive >= 1:
            total_90 = (await self._get_user_msg_stats(r, gid, uid, 90))["msg_count"]
            if total_90 == 1:
                alerts.append(PatternAlert(
                    pattern_name="Jednorázovka",
                    user_id=uid,
                    risk_level="info",
                    description=f"Uživatel napsal pouze 1 příspěvek a poté zmlkl ({days_inactive}d neaktivní).",
                    recommended_action="Okamžitý uvítací DM od mentora. První den je kritický.",
                    emoji="👋"
                ))

        # ── 5. Rytmus 90 dní (milníky den 21, 60, 90) ──
        if join_days is not None:
            for milestone in [21, 60, 90]:
                if milestone - 2 <= join_days <= milestone + 2:
                    if stats_7d["msg_count"] > 0:
                        prev_stats = await self._get_user_msg_stats(r, gid, uid, 14)
                        first_half = sum(prev_stats["daily_counts"][7:])
                        second_half = sum(prev_stats["daily_counts"][:7])
                        if first_half > 0 and second_half < first_half * 0.75:
                            alerts.append(PatternAlert(
                                pattern_name="Rytmus 90 dní",
                                user_id=uid,
                                risk_level="warning",
                                description=f"Uživatel je kolem {milestone}. dne a aktivita klesla o {int((1 - second_half/first_half)*100)}%.",
                                recommended_action=f"Oslava milníku {milestone} dní! Mentora by měl pogratulovat 2 dny PŘEDEM.",
                                emoji="📆"
                            ))

        # ── 6. Explozivní návrat ──
        if days_inactive == 0 and stats_30d["msg_count"] > 0:
            # Check if 14+ days silence before recent burst
            recent_msgs = stats_7d["daily_counts"]
            today_msgs = recent_msgs[0] if recent_msgs else 0
            if today_msgs >= 15:
                silence_before = 0
                for i in range(1, min(30, len(stats_30d["daily_counts"]))):
                    if stats_30d["daily_counts"][i] == 0:
                        silence_before += 1
                    else:
                        break
                if silence_before >= 14:
                    alerts.append(PatternAlert(
                        pattern_name="Explozivní návrat",
                        user_id=uid,
                        risk_level="warning",
                        description=f"Po {silence_before} dnech ticha napsal {today_msgs}+ zpráv za 24h. Riziko přepálení.",
                        recommended_action="Brzdit nadšení. Nařídit klidový režim (max 3 zprávy denně).",
                        emoji="💥"
                    ))

        # ── 7. Sezonní návrat ──
        if days_inactive == 0:
            total_recent = stats_7d["msg_count"]
            if total_recent > 0 and total_recent <= 3:
                # Check if they had a very long gap
                gap = 0
                for i in range(1, 365):
                    d = (now - timedelta(days=i)).strftime("%Y%m%d")
                    c = await self._get_user_daily_total(r, gid, uid, d)
                    if c > 0:
                        break
                    gap += 1
                if gap >= 180:  # 6+ months gap
                    kw_apology = await self._get_keyword_count(r, gid, uid, "apology_return", 7)
                    alerts.append(PatternAlert(
                        pattern_name="Sezonní návrat",
                        user_id=uid,
                        risk_level="info",
                        description=f"Uživatel se vrátil po {gap} dnech neaktivity. {'Obsahuje omluvu za pauzu.' if kw_apology > 0 else ''}",
                        recommended_action="Automatické 'Vítej zpátky' bez odsuzování délky pauzy.",
                        emoji="🔄"
                    ))

        # ── 8. Pravidelný přispěvatel ──
        if stats_30d["days_active"] >= 4:  # Active 4+ days in last month
            # Check 8-week consistency
            consecutive_weeks = 0
            for week in range(8):
                week_start = week * 7
                week_end = week_start + 7
                week_stats = await self._get_user_msg_stats(r, gid, uid, week_end)
                week_prev = await self._get_user_msg_stats(r, gid, uid, week_start) if week > 0 else {"msg_count": 0}
                week_msgs = week_stats["msg_count"] - week_prev["msg_count"]
                if week_msgs >= 1:
                    consecutive_weeks += 1
                else:
                    break
            if consecutive_weeks >= 8:
                alerts.append(PatternAlert(
                    pattern_name="Pravidelný přispěvatel",
                    user_id=uid,
                    risk_level="info",
                    description=f"Uživatel píše pravidelně již {consecutive_weeks} týdnů po sobě. Jádro komunity.",
                    recommended_action="Ocenit vytrvalost (odznak za milník v deníku).",
                    emoji="⭐"
                ))

        # ── 10. Relapsová únava ──
        relapse_kw_7d = await self._get_keyword_count(r, gid, uid, "relapse_fatigue", 7)
        relapse_kw_30d = await self._get_keyword_count(r, gid, uid, "relapse_fatigue", 30)
        baseline_per_week = relapse_kw_30d / 4 if relapse_kw_30d > 0 else 0
        if relapse_kw_7d >= 3 and (baseline_per_week == 0 or relapse_kw_7d >= baseline_per_week * 2):
            alerts.append(PatternAlert(
                pattern_name="Relapsová únava",
                user_id=uid,
                risk_level="critical",
                description=f"Frekvence slov 'znovu'/'zase' je {relapse_kw_7d}x za 7 dní (baseline: {baseline_per_week:.1f}/týden).",
                recommended_action="Změna narativu. Přesměrovat na analýzu příčin (Small Wins) místo 'zvedání se'.",
                emoji="🔁"
            ))

        # ── 11. Falešný vrchol ──
        euphoria_7d = await self._get_keyword_count(r, gid, uid, "euphoria", 7)
        methodology_7d = await self._get_keyword_count(r, gid, uid, "methodology", 7)
        if euphoria_7d >= 4 and methodology_7d == 0:
            alerts.append(PatternAlert(
                pattern_name="Falešný vrchol",
                user_id=uid,
                risk_level="warning",
                description=f"Euforie bez metodiky: {euphoria_7d}x 'super/zvládnu/dokonalé' za 7 dní, 0x zmínka deníku/parťáka.",
                recommended_action="'Servisní úkol' — zadat uživateli pomoc nováčkovi, aby zůstal ukotven v realitě.",
                emoji="🌸"
            ))

        # ── 12. Tichý boj ──
        if days_inactive == 0 and stats_7d["msg_count"] <= 2:
            restart_kw = await self._get_keyword_count(r, gid, uid, "restart_lang", 7)
            if restart_kw >= 2:
                # Check for long previous silence
                gap = 0
                for i in range(7, 180):
                    d = (now - timedelta(days=i)).strftime("%Y%m%d")
                    c = await self._get_user_daily_total(r, gid, uid, d)
                    if c > 0:
                        break
                    gap += 1
                if gap >= 60:
                    alerts.append(PatternAlert(
                        pattern_name="Tichý boj",
                        user_id=uid,
                        risk_level="critical",
                        description=f"Návrat po {gap}d ticha s restartovacím jazykem ({restart_kw}x 'chtěl bych/zase začal'). Kritický příspěvek.",
                        recommended_action="PRIORITY FLAG. Odpověď musí být vřelá, vítající, bez výčitek za neaktivitu.",
                        emoji="🆘"
                    ))

        # ── 13. Sémantický útlum ──
        if stats_7d["msg_count"] >= 5:
            avg_wpm_7d = stats_7d["avg_words_per_msg"]
            avg_wpm_30d = stats_30d["avg_words_per_msg"]
            if avg_wpm_7d < 4 and avg_wpm_30d > 10:
                alerts.append(PatternAlert(
                    pattern_name="Sémantický útlum",
                    user_id=uid,
                    risk_level="warning",
                    description=f"Průměr slov/zprávu klesl z {avg_wpm_30d:.1f} na {avg_wpm_7d:.1f}. Odpovídá jen 'díky/ok/chápu'.",
                    recommended_action="Přímé oslovení mentorem s otevřenou otázkou vyžadující více než jednoslovnou odpověď.",
                    emoji="📉"
                ))

        # ── 14. Emocionální dumping ──
        absol_7d = await self._get_keyword_count(r, gid, uid, "absolutisms", 7)
        if absol_7d >= 5:
            # Check for single-day spike
            for i in range(7):
                d = (now - timedelta(days=i)).strftime("%Y%m%d")
                day_absol = await r.get(K_KW(gid, uid, d, "absolutisms"))
                day_msgs_data = await r.hgetall(K_MSG(gid, uid, d))
                day_msgs = int(day_msgs_data.get("msg_count", 0)) if day_msgs_data else 0
                if day_absol and int(day_absol) >= 3 and day_msgs >= 5:
                    alerts.append(PatternAlert(
                        pattern_name="Emocionální dumping",
                        user_id=uid,
                        risk_level="warning",
                        description=f"Nárůst absolutismů ('všechno/nikdy/vždy'): {int(day_absol)}x za den s {day_msgs} zprávami.",
                        recommended_action="Přesun do vlákna. Označit jako 'venting' pro snížení tlaku na 'řešení'.",
                        emoji="🌊"
                    ))
                    break

        # ── 15. Zdi odvykání ──
        wall_kw_7d = await self._get_keyword_count(r, gid, uid, "wall_keywords", 7)
        wall_kw_30d = await self._get_keyword_count(r, gid, uid, "wall_keywords", 30)
        wall_baseline = wall_kw_30d / 4 if wall_kw_30d > 0 else 0
        if wall_kw_7d >= 3 and (wall_baseline == 0 or wall_kw_7d >= wall_baseline * 2):
            # Check for message length drop
            if stats_30d["avg_words_per_msg"] > 0:
                length_drop = 1 - (stats_7d["avg_words_per_msg"] / stats_30d["avg_words_per_msg"])
                if length_drop >= 0.3:
                    alerts.append(PatternAlert(
                        pattern_name="Zdi odvykání",
                        user_id=uid,
                        risk_level="warning",
                        description=f"'Nevím/stále' {wall_kw_7d}x za 7d + délka zpráv klesla o {int(length_drop*100)}%. Pocit stagnace.",
                        recommended_action="Výzva ke sdílení jednoho konkrétního detailu dne, nikoliv celkového stavu.",
                        emoji="🧱"
                    ))

        # ── 16. Tiché vyhoření ──
        despair_kw = await self._get_keyword_count(r, gid, uid, "despair", 14)
        if despair_kw >= 2 and days_inactive >= 3 and stats_30d["msg_count"] > 5:
            alerts.append(PatternAlert(
                pattern_name="Tiché vyhoření",
                user_id=uid,
                risk_level="critical",
                description=f"Zmínil odchod/vzdání ({despair_kw}x za 14d) a je {days_inactive}d neaktivní.",
                recommended_action="Okamžitý osobní DM od mentora. Pokud na zpověď nikdo nereagoval do 48h, riziko odchodu +60%.",
                emoji="🕯️"
            ))

        # ── 4. Noční sova ──
        night_msgs = 0
        total_msgs_hourly = 0
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            hour_data = await r.hgetall(f"pat:hour:{gid}:{uid}:{d}")
            for h, c in hour_data.items():
                h_int = int(h)
                c_int = int(c)
                total_msgs_hourly += c_int
                if 1 <= h_int <= 4:
                    night_msgs += c_int

        if total_msgs_hourly >= 10 and night_msgs > 0:
            night_ratio = night_msgs / total_msgs_hourly
            if night_ratio >= 0.4:
                alerts.append(PatternAlert(
                    pattern_name="Noční sova",
                    user_id=uid,
                    risk_level="warning",
                    description=f"{int(night_ratio*100)}% zpráv odesláno mezi 01:00-04:00 (posl. 7 dní). 3x vyšší riziko relapsu.",
                    recommended_action="Upozornění: 'Koukám, že jsi vzhůru pozdě. Zkus odložit telefon a jít spát.'",
                    emoji="🦉"
                ))

        # ── 3. Víkendový propad ──
        if stats_30d["msg_count"] >= 20:
            weekend_msgs = 0
            weekday_msgs = 0
            for i in range(28):
                d = now - timedelta(days=i)
                d_str = d.strftime("%Y%m%d")
                c = await self._get_user_daily_total(r, gid, uid, d_str)
                if d.weekday() >= 5:  # Sat/Sun
                    weekend_msgs += c
                else:
                    weekday_msgs += c

            if weekday_msgs > 0:
                weekday_avg = weekday_msgs / 20
                weekend_avg = weekend_msgs / 8
                if weekday_avg > 0 and weekend_avg < weekday_avg * 0.4:
                    alerts.append(PatternAlert(
                        pattern_name="Víkendový propad",
                        user_id=uid,
                        risk_level="info",
                        description=f"Víkendová aktivita je jen {int(weekend_avg/weekday_avg*100)}% denního průměru.",
                        recommended_action="'Friday Check-in' — moderátor vyžaduje plán na víkend.",
                        emoji="📅"
                    ))

        # ── 9. Osobní investice (edity) ──
        edit_total = 0
        for i in range(30):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            e = await r.get(K_EDIT(gid, uid, d))
            if e:
                edit_total += int(e)
        if edit_total >= 10 and stats_30d["msg_count"] > 0:
            edit_ratio = edit_total / stats_30d["msg_count"]
            if edit_ratio >= 0.3:
                alerts.append(PatternAlert(
                    pattern_name="Osobní investice",
                    user_id=uid,
                    risk_level="info",
                    description=f"Vysoká kognitivní investice: {edit_total} editů na {stats_30d['msg_count']} příspěvků (poměr {edit_ratio:.1f}).",
                    recommended_action="Autor nejkvalitnějšího obsahu. Intelektuální výzva nebo hluboká analýza od mentora.",
                    emoji="✏️"
                ))

        # ── 17. Poslední monolog ──
        diary_entries = await r.lrange(K_DIARY(gid, uid), 0, -1)
        if len(diary_entries) >= 3:
            # All 3+ recent diary posts unanswered
            entries = []
            for e_json in diary_entries:
                try:
                    entries.append(json.loads(e_json))
                except Exception:
                    pass
            if len(entries) >= 3:
                # Check if intervals are growing
                timestamps = sorted([e["ts"] for e in entries], reverse=True)
                alerts.append(PatternAlert(
                    pattern_name="Poslední monolog",
                    user_id=uid,
                    risk_level="critical",
                    description=f"{len(entries)} příspěvků v deníku po sobě bez jediné odpovědi.",
                    recommended_action="No-Post-Left-Behind: Mentor/bot musí reagovat na nepokryté posty v denících.",
                    emoji="📢"
                ))

        # ── 24. Nadšený pomocník ──
        if stats_30d["msg_count"] >= 20:
            help_kw = await self._get_keyword_count(r, gid, uid, "help_others", 30)
            if stats_30d["reply_count"] > stats_30d["msg_count"] * 0.6 and help_kw >= 10:
                alerts.append(PatternAlert(
                    pattern_name="Nadšený pomocník",
                    user_id=uid,
                    risk_level="info",
                    description=f"Vysoký poměr odpovědí ({stats_30d['reply_count']}/{stats_30d['msg_count']}) + {help_kw}x uvítací fráze. Riziko sekundární traumatizace.",
                    recommended_action="Osobní zpráva s oceněním. Pozvání do týmu moderátorů.",
                    emoji="🤝"
                ))

        # ── 26. Komunitní lepidlo ──
        if stats_30d["mention_count"] >= 15 and stats_30d["msg_count"] >= 15:
            help_kw2 = await self._get_keyword_count(r, gid, uid, "help_others", 30)
            if help_kw2 >= 5:
                alerts.append(PatternAlert(
                    pattern_name="Komunitní lepidlo",
                    user_id=uid,
                    risk_level="info",
                    description=f"{stats_30d['mention_count']} zmínek + {help_kw2}x 'vítám/držím palce'. Potenciální moderátor.",
                    recommended_action="Označit rolí 'Aspirující mentor'. Kultivovat, nepotlačovat.",
                    emoji="🏅"
                ))

        # ── 27. Aktivní pozorovatel ──
        if stats_7d["msg_count"] > 0 and stats_7d["msg_count"] <= 3:
            activation_kw = await self._get_keyword_count(r, gid, uid, "activation", 7)
            if activation_kw >= 1:
                # Check if they were previously silent
                prev_stats = await self._get_user_msg_stats(r, gid, uid, 90)
                if prev_stats["msg_count"] - stats_7d["msg_count"] == 0:
                    alerts.append(PatternAlert(
                        pattern_name="Aktivní pozorovatel",
                        user_id=uid,
                        risk_level="warning",
                        description=f"První příspěvek po dlouhém období pozorování. Obsahuje aktivační jazyk.",
                        recommended_action="Okamžité nasměrování na krizový plán. Vnitřní motivace je na vrcholu.",
                        emoji="🌱"
                    ))

        return alerts

    async def _analyze_user_affinity(self, r, gid: int, uid: int, now: datetime, today: str, stats_7d: Dict, stats_30d: Dict, days_inactive: int) -> List[Dict]:
        """Calculate percentage affinity for various patterns."""
        affinities = []

        # 1. Víkendový propad (Target < 0.4)
        if stats_30d["msg_count"] >= 10:
            weekend_msgs, weekday_msgs = 0, 0
            for i in range(28):
                d = now - timedelta(days=i)
                c = await self._get_user_daily_total(r, gid, uid, d.strftime("%Y%m%d"))
                if d.weekday() >= 5: weekend_msgs += c
                else: weekday_msgs += c
            
            if weekday_msgs > 0:
                weekday_avg = weekday_msgs / 20
                weekend_avg = weekend_msgs / 8
                if weekday_avg > 0:
                    ratio = weekend_avg / weekday_avg
                    # 100% = ratio 0.0, 0% = ratio 1.0
                    score = max(0, min(100, int((1.0 - ratio) * 100)))
                    affinities.append({"name": "Víkendový propad", "score": score, "emoji": "📅", "desc": f"Víkendová aktivita je {int(ratio*100)}% průměru.", "hint": "Zkuste zavést 'Friday Check-in'."})

        # 2. Noční sova (Target >= 0.4)
        total_hourly, night_msgs = 0, 0
        for i in range(7):
            d = (now - timedelta(days=i)).strftime("%Y%m%d")
            hour_data = await r.hgetall(f"pat:hour:{gid}:{uid}:{d}")
            for h, c in hour_data.items():
                total_hourly += int(c)
                if 1 <= int(h) <= 4: night_msgs += int(c)
        if total_hourly > 0:
            ratio = night_msgs / total_hourly
            # 100% = ratio 0.6+, 0% = ratio 0.0
            score = max(0, min(100, int((ratio / 0.6) * 100)))
            if score > 10:
                affinities.append({"name": "Noční sova", "score": score, "emoji": "🦉", "desc": f"{int(ratio*100)}% zpráv po půlnoci.", "hint": "Doporučte offline večerní rutinu."})

        # 3. Sémantický útlum (Target: 7d < 4, 30d > 10)
        avg_7d = stats_7d["avg_words_per_msg"]
        avg_30d = stats_30d["avg_words_per_msg"]
        if avg_30d > 5 and stats_7d["msg_count"] > 0:
            drop_ratio = 1.0 - (avg_7d / avg_30d)
            if drop_ratio > 0:
                # 100% = 70% drop, 0% = 0% drop
                score = max(0, min(100, int((drop_ratio / 0.7) * 100)))
                affinities.append({"name": "Sémantický útlum", "score": score, "emoji": "📉", "desc": f"Délka zpráv klesla o {int(drop_ratio*100)}%.", "hint": "Ptejte se otevřenými otázkami."})

        # 4. Jednorázovka (Target: 1 msg, 1+ days inactive)
        if stats_30d["msg_count"] > 0 and stats_30d["msg_count"] <= 3:
            # 100% = 1 msg, 50% = 2 msgs, 25% = 3 msgs
            base_score = 100 if stats_30d["msg_count"] == 1 else (50 if stats_30d["msg_count"] == 2 else 25)
            # Add inactivity multiplier
            multiplier = min(1.0, days_inactive / 3.0) # max out at 3 days
            score = int(base_score * multiplier)
            if score > 0:
                affinities.append({"name": "Jednorázovka", "score": score, "emoji": "👋", "desc": f"Napsal {stats_30d['msg_count']} zpráv před {days_inactive} dny.", "hint": "Pošlete krátkou uvítací zprávu."})

        # 5. Pravidelný přispěvatel (Target: 8 weeks)
        if stats_30d["msg_count"] >= 5:
            consecutive = 0
            for w in range(8):
                ws = w * 7
                we = ws + 7
                st = await self._get_user_msg_stats(r, gid, uid, we)
                pr = await self._get_user_msg_stats(r, gid, uid, ws) if w > 0 else {"msg_count": 0}
                if st["msg_count"] - pr["msg_count"] >= 1: consecutive += 1
                else: break
            score = int((consecutive / 8.0) * 100)
            if score > 20:
                affinities.append({"name": "Pravidelný přispěvatel", "score": score, "emoji": "⭐", "desc": f"Aktivní {consecutive} týdnů po sobě.", "hint": "Oceňte vytrvalost komunitním odznakem."})

        # 6. Relapsová únava (Based on keywords)
        kw_rel = await self._get_keyword_count(r, gid, uid, "relapse_fatigue", 14)
        if kw_rel > 0:
            score = max(0, min(100, int((kw_rel / 4.0) * 100))) # 100% = 4+ mentions
            affinities.append({"name": "Relapsová únava", "score": score, "emoji": "🔁", "desc": f"Signály únavy zaznamenány {kw_rel}x.", "hint": "Přesuňte fokus z počítání dnů na small wins."})
            
        # 7. Tiché vyhoření (despair + inactivity)
        kw_desp = await self._get_keyword_count(r, gid, uid, "despair", 14)
        if kw_desp > 0:
            score = max(0, min(100, int(((kw_desp * 20) + (days_inactive * 10))))) # 100 = 2 hits + 6 days inactive
            affinities.append({"name": "Tiché vyhoření", "score": score, "emoji": "🕯️", "desc": f"{kw_desp}x zmínka o vzdání + {days_inactive}d neaktivita.", "hint": "Okamžitý osobní DM, nevyčítejte ticho."})

        # Sort by score descending and return top 5
        affinities.sort(key=lambda x: x["score"], reverse=True)
        return [a for a in affinities if a["score"] > 0][:5]

    async def _scan_group_patterns(self, r, gid: int, now: datetime,
                                    today: str, user_ids: Set[int]) -> List[PatternAlert]:
        """Detect patterns that require cross-user analysis."""
        alerts = []

        # ── 23. Zrcadlový relaps ──
        # Check if multiple users mentioned "relaps" in last 4 hours
        relapse_users = []
        for uid in user_ids:
            kw_today = await r.get(K_KW(gid, uid, today, "relapse_word"))
            if kw_today and int(kw_today) > 0:
                relapse_users.append(uid)

        if len(relapse_users) >= 2:
            user_mentions = " ".join(f"<@{u}>" for u in relapse_users[:5])
            alerts.append(PatternAlert(
                pattern_name="Zrcadlový relaps",
                user_id=relapse_users[0],  # Primary user for dedup
                risk_level="critical",
                description=f"Kumulace relapsů: {len(relapse_users)} uživatelů zmínilo 'relaps' dnes: {user_mentions}",
                recommended_action="Okamžitý intervenční post moderátora se změnou tématu na pozitivní aktivitu.",
                emoji="🪞"
            ))

        # ── 22. Nenaplněná reciprocita (questions without answers) ──
        cursor = "0"
        while True:
            cursor, keys = await r.scan(cursor=cursor, match=f"pat:question:{gid}:*", count=500)
            for k in keys:
                ts_str = await r.get(k)
                if ts_str:
                    q_ts = int(ts_str)
                    age_hours = (int(time.time()) - q_ts) / 3600
                    if age_hours >= 6:
                        parts = k.split(":")
                        if len(parts) >= 5:
                            q_uid = int(parts[3])
                            alerts.append(PatternAlert(
                                pattern_name="Nenaplněná reciprocita",
                                user_id=q_uid,
                                risk_level="warning",
                                description=f"Otázka bez odpovědi již {int(age_hours)} hodin.",
                                recommended_action="Bot upozorní moderátory na nezodpovězený dotaz.",
                                emoji="❓"
                            ))
                            # Delete to not re-alert
                            await r.delete(k)
            if cursor == 0 or cursor == "0":
                break

        return alerts

    async def _get_recent_alerts(self, r, gid: int, limit: int = 10) -> List[Dict]:
        """Fetch the most recent alerts from both Discord and Discourse."""
        alerts = []
        # Pulse both main guild and Discourse (999)
        sources = [(gid, "Discord"), (999, "Discourse")]
        
        for source_gid, label in sources:
            cursor = "0"
            match_pat = f"pat:alert_sent:{source_gid}:*:*"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=match_pat, count=100)
                for k in keys:
                    parts = k.split(":")
                    if len(parts) >= 5:
                        uid = int(parts[3])
                        pat_name = parts[4]
                        ts_val = await r.get(k)
                        if ts_val:
                            try:
                                # Fallback if value is "1" or invalid
                                ts_int = int(float(ts_val))
                                if ts_int < 1000000: # 1 or very small
                                    ts_int = int(time.time()) - 3600 # Treat as "at least an hour ago"
                            except (ValueError, TypeError):
                                ts_int = int(time.time())
                                
                            alerts.append({
                                "user_id": uid,
                                "pattern": pat_name,
                                "timestamp": ts_int,
                                "source": label
                            })
                if cursor == "0" or cursor == 0:
                    break
        
        alerts.sort(key=lambda x: x["timestamp"], reverse=True)
        return alerts[:limit]

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LAYER 4: Alert System
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    async def _should_send_alert(self, r, gid: int, alert: PatternAlert) -> bool:
        """Check deduplication — same pattern + user = max 1 alert per cooldown period."""
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        exists = await r.exists(key)
        return not exists

    async def _mark_alert_sent(self, r, gid: int, alert: PatternAlert):
        """Mark alert as sent with cooldown TTL and store the timestamp."""
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        ttl = config.PATTERN_ALERT_COOLDOWN_HOURS * 3600
        # Store actual timestamp for dashboard and history
        await r.set(key, str(int(time.time())), ex=ttl)

    async def _send_alert(self, alert: PatternAlert):
        """Send a pattern alert embed to the alert channel."""
        channel = await self._get_alert_channel()
        if not channel:
            logger.warning(f"Alert channel not found for pattern: {alert.pattern_name}")
            return

        embed = discord.Embed(
            title=f"{alert.emoji} {alert.pattern_name}",
            description=alert.description,
            color=alert.color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="👤 Uživatel", value=f"<@{alert.user_id}>", inline=True)
        embed.add_field(name="⚠️ Úroveň", value=alert.level_label, inline=True)
        embed.add_field(name="💡 Doporučení", value=alert.recommended_action, inline=False)
        embed.set_footer(text="Metricord Pattern Engine")

        try:
            await channel.send(embed=embed)
        except Exception as e:
            logger.error(f"Failed to send alert: {e}")

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # LAYER 5: Slash Commands
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    pattern_group = app_commands.Group(name="patterns", description="Detekce vzorců chování")

    @pattern_group.command(name="check", description="Ručně zkontrolovat vzorce a statistiky u konkrétního uživatele.")
    @app_commands.describe(user="Uživatel ke kontrole")
    @app_commands.checks.has_permissions(administrator=True)
    async def check_user(self, itx: discord.Interaction, user: discord.Member):
        if self._is_staff(user):
            await itx.response.send_message(f"⚠️ **{user.display_name}** je členem týmu. U pracovníků vzorce nesledujeme.", ephemeral=True)
            return

        await itx.response.defer(ephemeral=True)

        r = await self._get_redis()
        now = datetime.now(timezone.utc)
        today = self._today()

        try:
            alerts = await self._scan_user(r, self._guild_id, user.id, now, today)
            stats_7d = await self._get_user_msg_stats(r, self._guild_id, user.id, 7)
            stats_30d = await self._get_user_msg_stats(r, self._guild_id, user.id, 30)
            
            # Additional intensities
            intensities = {
                "🔴 Relapsy": await self._get_keyword_count(r, self._guild_id, user.id, "relapse_word", 7),
                "🔁 Únava": await self._get_keyword_count(r, self._guild_id, user.id, "relapse_fatigue", 7),
                "🆘 Beznaděj": await self._get_keyword_count(r, self._guild_id, user.id, "despair", 7),
                "🧱 Stagnace": await self._get_keyword_count(r, self._guild_id, user.id, "wall_keywords", 7),
                "🌸 Euforie": await self._get_keyword_count(r, self._guild_id, user.id, "euphoria", 7),
                "🤝 Pomoc": await self._get_keyword_count(r, self._guild_id, user.id, "help_others", 7),
            }

            days_inactive = await self._days_since_last_activity(r, self._guild_id, user.id, 180)
            affinities = await self._analyze_user_affinity(r, self._guild_id, user.id, now, today, stats_7d, stats_30d, days_inactive)

            embed = discord.Embed(
                title=f"🔍 Diagnostika: {user.display_name}",
                color=0x5865F2,
                timestamp=now
            )
            embed.set_thumbnail(url=user.display_avatar.url)

            # --- 1. Activity Section ---
            act_val = (
                f"**7 dní:** {stats_7d['msg_count']} zpráv ({stats_7d['avg_words_per_msg']:.1f} slov/zpr)\n"
                f"**30 dní:** {stats_30d['msg_count']} zpráv ({stats_30d['avg_words_per_msg']:.1f} slov/zpr)"
            )
            embed.add_field(name="📊 Statistiky aktivity", value=act_val, inline=True)

            # --- 2. Keyword Intensities ---
            int_list = [f"{k}: **{v}x**" for k, v in intensities.items() if v > 0]
            if int_list:
                embed.add_field(name="⚠️ Signály (7d)", value="\n".join(int_list), inline=True)

            embed.add_field(name="\u200B", value="\u200B", inline=True) # Spacer for 3-column layout

            # --- 3. Pattern Affinity ---
            if affinities:
                aff_text = ""
                for af in affinities:
                    aff_text += f"{af['emoji']} **{af['name']}** `{af['score']}%`\n└ 💡 *{af['hint']}*\n"
                embed.add_field(name="🎯 Vzorcová Afinita", value=aff_text.strip(), inline=False)
            elif not alerts:
                embed.add_field(name="✅ Vzorce", value="Uživatel nevykazuje shodu s rizikovými vzorci.", inline=False)

            # --- 4. Detected Patterns (Full Match) ---
            advice = None
            if alerts:
                pat_text = ""
                for a in alerts[:5]:
                    pat_text += f"**{a.emoji} {a.pattern_name}** • {a.level_label}\n"
                embed.add_field(name=f"🚨 Aktivní Poplachy", value=pat_text.strip(), inline=False)
                
                # Synthesize advice from patterns
                advice = alerts[0].recommended_action 
            elif affinities:
                advice = affinities[0]['hint']
            
            if not advice:
                advice = "Uživatel se zdá být v normě. Doporučujeme standardní podporu a udržování kontaktu."

            # --- 5. Mentor Advice ---
            embed.add_field(name="💡 Syntéza doporučení", value=f"> *{advice}*", inline=False)
            
            await itx.followup.send(embed=embed, ephemeral=True)
            
        finally:
            await r.close()

    @pattern_group.command(name="status", description="Zobrazí stav pattern detection enginu.")
    @app_commands.checks.has_permissions(administrator=True)
    async def status(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)

        r = await self._get_redis()
        try:
            gid = self._guild_id
            last_scan = await r.get(K_LAST_SCAN(gid))
            last_scan_str = "Nikdy" if not last_scan else datetime.fromtimestamp(
                int(last_scan), tz=timezone.utc
            ).strftime("%d.%m.%Y %H:%M UTC")

            # Count active alerts today
            alert_count = 0
            cursor = "0"
            while True:
                cursor, keys = await r.scan(cursor=cursor, match=f"pat:alert_sent:{gid}:*", count=500)
                alert_count += len(keys)
                if cursor == 0 or cursor == "0":
                    break

            # Count tracked users
            user_count = 0
            cursor2 = "0"
            while True:
                cursor2, keys2 = await r.scan(cursor=cursor2, match=f"pat:msg:{gid}:*", count=500)
                uids = set()
                for k in keys2:
                    parts = k.split(":")
                    if len(parts) >= 4:
                        uids.add(parts[3])
                user_count += len(uids)
                if cursor2 == 0 or cursor2 == "0":
                    break

            embed = discord.Embed(
                title="⚙️ Pattern Detection Engine",
                color=0x2ECC71 if self.pattern_scanner.is_running() else 0xE74C3C,
            )
            embed.add_field(name="📊 Stav", value="✅ Běží" if self.pattern_scanner.is_running() else "❌ Zastaveno", inline=True)
            embed.add_field(name="⏱️ Interval", value=f"{config.PATTERN_SCAN_INTERVAL_MINUTES} min", inline=True)
            embed.add_field(name="🕐 Poslední scan", value=last_scan_str, inline=True)
            embed.add_field(name="🔔 Aktivní alerty", value=str(alert_count), inline=True)
            embed.add_field(name="👥 Sledovaní uživatelé", value=str(user_count), inline=True)
            embed.add_field(name="🧠 Vzorců", value="27", inline=True)
            embed.set_footer(text="Metricord Pattern Engine v1.0")

            await itx.followup.send(embed=embed, ephemeral=True)
        finally:
            await r.close()

    @pattern_group.command(name="alerts", description="Zobrazit nejnovější detekované vzorce (z Discordu i fóra).")
    @app_commands.describe(limit="Počet záznamů (max 20)")
    @app_commands.checks.has_permissions(administrator=True)
    async def recent_alerts(self, itx: discord.Interaction, limit: int = 10):
        await itx.response.defer(ephemeral=False)
        limit = min(limit, 20)
        
        r = await self._get_redis()
        try:
            alerts = await self._get_recent_alerts(r, self._guild_id, limit)
            
            if not alerts:
                await itx.followup.send("📭 Nebyly nalezeny žádné nedávné výstrahy.")
                return

            embed = discord.Embed(
                title="🔔 Nejnovější detekované vzorce",
                description=f"Posledních **{len(alerts)}** zachycených signálů napříč platformami.",
                color=0x5865F2,
                timestamp=datetime.now(timezone.utc)
            )
            
            for a in alerts:
                src_emoji = "🔵" if a["source"] == "Discord" else "🟢"
                date_str = f"<t:{a['timestamp']}:R>"
                
                # Proactive user resolution
                user_display = f"<@{a['user_id']}>"
                guild = self.bot.get_guild(self._guild_id)
                if guild:
                    member = guild.get_member(a["user_id"])
                    if member:
                        user_display = f"**{member.display_name}** (<@{a['user_id']}>)"
                    else:
                        # Fallback to user_info from Redis (populated by dashboard/other cogs)
                        u_info = await r.hgetall(f"user:info:{a['user_id']}")
                        if u_info and (u_info.get("name") or u_info.get("username")):
                            user_display = f"**{u_info.get('name') or u_info['username']}** (<@{a['user_id']}>)"

                embed.add_field(
                    name=f"{src_emoji} {a['pattern']}",
                    value=f"Uživatel: {user_display}\nZdroj: **{a['source']}** • {date_str}",
                    inline=False
                )
            
            await itx.followup.send(embed=embed)
        finally:
            await r.close()

    @pattern_group.command(name="list", description="Seznam všech detekovaných vzorců chování.")
    @app_commands.checks.has_permissions(administrator=True)
    async def list_patterns(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        # Mapping for the list command (manually compiled from the engine logic)
        patterns = [
            ("Jednorázovka", "👋", "Uživatel napíše 1 zprávu a pak se odmlčí."),
            ("Rytmus 90 dní", "📆", "Pokles aktivity kolem klíčových milníků (21, 60, 90 dní)."),
            ("Explozivní návrat", "💥", "Náhlý výbuch aktivity (15+ zpráv) po 14+ dnech ticha."),
            ("Sezonní návrat", "🔄", "Návrat po velmi dlouhé pauze (6+ měsíců)."),
            ("Pravidelný přispěvatel", "⭐", "Konzistentní psaní po dobu 8+ týdnů."),
            ("Relapsová únava", "🔁", "Zvýšená frekvence slov 'znovu'/'zase'."),
            ("Falešný vrchol", "🌸", "Euforický jazyk bez zmínek o metodice/deníku."),
            ("Tichý boj", "🆘", "Návrat po tichu s omluvným/restartovacím jazykem."),
            ("Sémantický útlum", "📉", "Zkracování průměrné délky zpráv (jednoslovné odpovědi)."),
            ("Emocionální dumping", "🌊", "Nárazové používání absolutismů (vše/nic/vždy)."),
            ("Zdi odvykání", "🧱", "Pocit stagnace ('nevím/stále') doprovázený útlumem."),
            ("Tiché vyhoření", "🕯️", "Zmínky o vzdání se doprovázené následnou neaktivitou."),
            ("Noční sova", "🦉", "Většina zpráv v rizikovém čase 01:00-04:00."),
            ("Víkendový propad", "📅", "Výrazně nižší aktivita o víkendech proti všedním dnům."),
            ("Osobní investice", "✏️", "Vysoký poměr editací zpráv (kvalitní obsah)."),
            ("Poslední monolog", "📢", "Série zpráv v deníku bez jediné reakce komunity."),
            ("Nadšený pomocník", "🤝", "Vysoký poměr odpovědí nováčkům (riziko přehlcení)."),
            ("Komunitní lepidlo", "🏅", "Vysoký počet zmínek a vítání jiných členů."),
            ("Aktivní pozorovatel", "🌱", "Aktivace po dlouhém období pouhého čtení."),
            ("Zrcadlový relaps", "🪞", "Kumulace zmínek o relapsu od více uživatelů najedou."),
            ("Nenaplněná reciprocita", "❓", "Otázka čekající na odpověď více než 6 hodin.")
        ]
        
        # We split into 2 embeds if > 25 (discord limit)
        embed1 = discord.Embed(title="🧠 Knihovna vzorců (1/1)", color=0x3498DB)
        for name, emoji, desc in patterns:
            embed1.add_field(name=f"{emoji} {name}", value=desc, inline=True)
            
        await itx.followup.send(embed=embed1, ephemeral=True)

    @pattern_group.command(name="scan", description="ADMIN: Spustit okamžitý scan vzorců.")
    @app_commands.checks.has_permissions(administrator=True)
    async def force_scan(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        try:
            await self.pattern_scanner()
            await itx.followup.send("✅ Scan dokončen. Zkontrolujte alert kanál.", ephemeral=True)
        except Exception as e:
            await itx.followup.send(f"❌ Chyba při scanu: {e}", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(PatternDetectorCog(bot))
