# commands/activity.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from datetime import datetime, timedelta, date
import redis.asyncio as redis
import math
from collections import defaultdict
import re

# Redis Stats Keys (Daily Buckets)
# activity:day:{YYYY-MM-DD}:{guild_id}:{user_id}:{metric}
# Metrics: chat_time, voice_time, messages, bans, kicks, timeouts, unbans, verifications, msg_deleted, role_updates

# Redis State Keys (Ephemeral - Session Tracking)
# activity:state:{guild_id}:{user_id}:chat_start
# activity:state:{guild_id}:{user_id}:chat_last
# activity:state:{guild_id}:{user_id}:voice_start

SESSION_TIMEOUT = 900  # 15 minutes
MIN_SESSION_TIME = 60 # Minimum time for a session (even single message)
# Lead-In Constants for Content-Aware Tracking
LEAD_IN_BASE = 180.0  # 3 minutes base per session start
LEAD_IN_CHAR = 1.0    # 1.0s per character (every message)
LEAD_IN_REPLY = 60.0  # 1 minute bonus for replies (new session context)

REDIS_URL = "redis://redis-hll:6379/0"

ACTION_WEIGHTS = {
    "bans": 300,
    "kicks": 180,
    "timeouts": 180,
    "unbans": 120,
    "verifications": 120,
    "msg_deleted": 60,
    "role_updates": 30
}

class ActivityMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        self.r = redis.Redis(connection_pool=self.pool)

    async def cog_unload(self):
        await self.pool.disconnect()

    def _get_today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _timestamp_to_day(self, ts: float) -> str:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")

    def _k_day_stats(self, day: str, gid: int, uid: int, metric: str) -> str:
        return f"activity:day:{day}:{gid}:{uid}:{metric}"

    def _k_state(self, gid: int, uid: int, key: str) -> str:
        return f"activity:state:{gid}:{uid}:{key}"

    def _calc_lead_in(self, length: int, is_reply: bool) -> float:
        """Calculate Lead-In time for NEW SESSION start."""
        bonus = LEAD_IN_REPLY if is_reply else 0
        # Base + Bonus. Character time is added SEPARATELY now for consistency.
        return LEAD_IN_BASE + bonus

    async def _update_session(self, gid: int, uid: int, message: discord.Message = None):
        """
        Update session state.
        1. Always add CHAR TIME for the message.
        2. If New Session -> Add LEAD_IN_BASE (+ Reply Bonus).
        3. If Continue -> Update timestamp (natural gap adds up later).
        """
        now = time.time()
        day_now = self._get_today()
        
        # 1. Always add Character Time
        if message:
            char_time = len(message.content) * LEAD_IN_CHAR
            await self.r.incrbyfloat(self._k_day_stats(day_now, gid, uid, "chat_time"), char_time)

        k_start = self._k_state(gid, uid, "chat_start")
        k_last = self._k_state(gid, uid, "chat_last")

        last_seen = await self.r.get(k_last)
        
        async with self.r.pipeline() as pipe:
            if last_seen:
                last_seen_f = float(last_seen)
                
                if now - last_seen_f > SESSION_TIMEOUT:
                    # Time out -> Close previous
                    start_str = await self.r.get(k_start)
                    if start_str:
                        start_f = float(start_str)
                        raw_duration = last_seen_f - start_f
                        # Max with 0, since Lead-In covers the base time now.
                        duration = max(raw_duration, 0)
                        
                        day_prev = self._timestamp_to_day(last_seen_f)
                        pipe.incrbyfloat(self._k_day_stats(day_prev, gid, uid, "chat_time"), duration)
                    
                    # Start NEW session
                    pipe.set(k_start, now)
                    
                    # Add Lead-In (Base + Reply Bonus)
                    if message:
                        is_reply = (message.reference is not None)
                        lead_in = self._calc_lead_in(len(message.content), is_reply)
                        pipe.incrbyfloat(self._k_day_stats(day_now, gid, uid, "chat_time"), lead_in)
                
                # Else: Continue session. Just update last_seen.
                
            else:
                # First ever
                pipe.set(k_start, now)
                if message:
                    is_reply = (message.reference is not None)
                    lead_in = self._calc_lead_in(len(message.content), is_reply)
                    pipe.incrbyfloat(self._k_day_stats(day_now, gid, uid, "chat_time"), lead_in)
            
            pipe.set(k_last, now)
            pipe.expire(k_start, 86400)
            pipe.expire(k_last, 86400)
            await pipe.execute()

    # --- LISTENERS ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild: return
        # Increment daily message count
        day = self._get_today()
        await self.r.incr(self._k_day_stats(day, message.guild.id, message.author.id, "messages"))
        await self._update_session(message.guild.id, message.author.id, message)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Union[discord.Member, discord.User]):
        if user.bot or not reaction.message.guild: return
        await self._update_session(reaction.message.guild.id, user.id)

    @commands.Cog.listener()
    async def on_interaction(self, itx: discord.Interaction):
        if itx.user.bot or not itx.guild: return
        await self._update_session(itx.guild.id, itx.user.id)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        gid = member.guild.id
        uid = member.id
        now = time.time()
        k_voice = self._k_state(gid, uid, "voice_start")

        is_in = after.channel is not None
        was_in = before.channel is not None
        
        if is_in and not was_in:
            await self.r.set(k_voice, now)
        elif was_in and not is_in:
            start_str = await self.r.get(k_voice)
            if start_str:
                start = float(start_str)
                duration = now - start
                if duration > 0:
                    day = self._timestamp_to_day(now) # Attribute to leave time
                    await self.r.incrbyfloat(self._k_day_stats(day, gid, uid, "voice_time"), duration)
                await self.r.delete(k_voice)

    # --- HELPERS ---
    def fmt_time(self, seconds: float) -> str:
        if seconds < 60: return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h}h {m}m"
        return f"{m}m"

    async def get_aggregated_stats(self, gid: int, uid: int, start_date: date = None, end_date: date = None):
        """Sum stats for a user within a date range."""
        agg = defaultdict(float)
        
        # Pattern: activity:day:YYYY-MM-DD:GID:UID:METRIC
        # We can iterate specifically if the range is small, but SCAN is safer for sparse data.
        # Actually, if we have huge history, scanning "activity:day:*" might be slow.
        # BUT, since we store GID/UID in the key, we can scan `activity:day:*:GID:UID:*`
        pattern = f"activity:day:*:*:{gid}:{uid}:*" # Wait, format is activity:day:{day}:{gid}:{uid}:{metric}
        # Correct scan pattern for specific user:
        pattern = f"activity:day:*:{gid}:{uid}:*"
        
        async for key in self.r.scan_iter(pattern):
            # Key: activity:day:2025-01-16:123:456:bans
            parts = key.split(":")
            if len(parts) != 6: continue
            
            day_str = parts[2]
            metric = parts[5]
            
            # Date Filter
            if start_date or end_date:
                try:
                    d = datetime.strptime(day_str, "%Y-%m-%d").date()
                    if start_date and d < start_date: continue
                    if end_date and d > end_date: continue
                except: continue
                
            val = float(await self.r.get(key) or 0)
            agg[metric] += val
            
        return agg

    # --- COMMANDS ---
    act_group = app_commands.Group(name="activity", description="Sledování aktivity moderátorů")

    @act_group.command(name="stats", description="Zobrazí statistiky (lze filtrovat datem).")
    @app_commands.describe(
        user="Uživatel (default: ty)",
        after="Od data (DD-MM-YYYY)",
        before="Do data (DD-MM-YYYY)"
    )
    async def stats(self, itx: discord.Interaction, user: discord.Member = None, after: str = None, before: str = None):
        await itx.response.defer()
        if not user: user = itx.user
        gid = itx.guild.id
        uid = user.id
        
        # Parse dates
        d_after = None
        d_before = None
        date_info = "Celková historie"
        
        try:
            if after:
                d_after = datetime.strptime(after, "%d-%m-%Y").date()
            if before:
                d_before = datetime.strptime(before, "%d-%m-%Y").date()
            
            if d_after and d_before:
                date_info = f"{d_after.strftime('%d.%m.%Y')} — {d_before.strftime('%d.%m.%Y')}"
            elif d_after:
                date_info = f"Od {d_after.strftime('%d.%m.%Y')}"
            elif d_before:
                date_info = f"Do {d_before.strftime('%d.%m.%Y')}"
        except ValueError:
            await itx.followup.send("❌ Špatný formát data. Použij `DD-MM-YYYY` (např. 01-01-2025).")
            return

        # Fetch Data
        data = await self.get_aggregated_stats(gid, uid, d_after, d_before)
        
        # Pending Session
        today = date.today()
        include_pending = True
        if d_before and d_before < today: include_pending = False
        if d_after and d_after > today: include_pending = False
        
        if include_pending:
            now = time.time()
            # Chat
            k_cs = self._k_state(gid, uid, "chat_start")
            k_cl = self._k_state(gid, uid, "chat_last")
            cs = await self.r.get(k_cs)
            cl = await self.r.get(k_cl)
            if cs and cl and (now - float(cl) < SESSION_TIMEOUT):
                # Only add the duration between start and last, as char_time is added instantly
                data["chat_time"] += (float(cl) - float(cs))
            # Voice
            k_vs = self._k_state(gid, uid, "voice_start")
            vs = await self.r.get(k_vs)
            if vs:
                data["voice_time"] += (now - float(vs))

        # Calculate Breakdown
        chat_t = data["chat_time"]
        voice_t = data["voice_time"]
        msgs = int(data["messages"])
        
        action_time = 0
        for m, w in ACTION_WEIGHTS.items():
            action_time += (data[m] * w)
            
        total_time = chat_t + voice_t + action_time
        
        # Embed
        e = discord.Embed(title=f"📊 Aktivita: {user.display_name}", description=f"📅 **Období:** {date_info}", color=discord.Color.blue())
        e.set_thumbnail(url=user.display_avatar.url)
        
        e.add_field(name="💬 Chat Time", value=self.fmt_time(chat_t), inline=True)
        e.add_field(name="🎙️ Voice Time", value=self.fmt_time(voice_t), inline=True)
        e.add_field(name="🛠️ Action Time", value=self.fmt_time(action_time), inline=True)
        e.add_field(name="📩 Zpráv", value=str(msgs), inline=True)
        
        bans = int(data["bans"])
        kicks = int(data["kicks"])
        timeouts = int(data["timeouts"])
        dels = int(data["msg_deleted"])
        roles = int(data["role_updates"])
        unbans = int(data["unbans"])
        verifs = int(data["verifications"])
        
        e.add_field(name="🔨 Bany", value=str(bans), inline=True)
        e.add_field(name="👢 Kicky", value=str(kicks), inline=True)
        e.add_field(name="🤐 Timeouts", value=str(timeouts), inline=True)
        e.add_field(name="🗑️ Smazáno", value=str(dels), inline=True)
        e.add_field(name="🎭 Role", value=str(roles), inline=True)
        e.add_field(name="🔓 Unbany", value=str(unbans), inline=True)
        e.add_field(name="✅ Verifikace", value=str(verifs), inline=True)
        
        total_h = total_time / 3600
        e.add_field(name="⏱️ Celkový vážený čas", value=f"**{total_h:.1f} hodin**", inline=False)
        
        await itx.followup.send(embed=e)

    @act_group.command(name="leaderboard", description="TOP 10 nejaktivnějších (s filtrem data).")
    @app_commands.describe(after="Od data (DD-MM-YYYY)", before="Do data (DD-MM-YYYY)")
    async def leaderboard(self, itx: discord.Interaction, after: str = None, before: str = None):
        await itx.response.defer()
        gid = itx.guild.id
        
        d_after = None
        d_before = None
        date_info = "Celková historie"
        try:
            if after: d_after = datetime.strptime(after, "%d-%m-%Y").date()
            if before: d_before = datetime.strptime(before, "%d-%m-%Y").date()
            
            if d_after and d_before:
                date_info = f"{d_after.strftime('%d.%m.%Y')} — {d_before.strftime('%d.%m.%Y')}"
            elif d_after:
                date_info = f"Od {d_after.strftime('%d.%m.%Y')}"
            elif d_before:
                date_info = f"Do {d_before.strftime('%d.%m.%Y')}"
        except ValueError:
            await itx.followup.send("❌ Špatný formát data.")
            return

        user_scores = defaultdict(float) # uid -> total_weighted_seconds
        
        # Scan ALL daily keys for this guild
        pattern = f"activity:day:*:{gid}:*:*"
        async for key in self.r.scan_iter(pattern):
            # activity:day:YYYY-MM-DD:GID:UID:METRIC
            parts = key.split(":")
            if len(parts) != 6: continue
            
            day_str = parts[2]
            uid = int(parts[4])
            metric = parts[5]
            
            # Filter
            if d_after or d_before:
                try:
                    d = datetime.strptime(day_str, "%Y-%m-%d").date()
                    if d_after and d < d_after: continue
                    if d_before and d > d_before: continue
                except: continue
                
            val = float(await self.r.get(key) or 0)
            
            # Add to score
            weight = 1.0
            if metric in ACTION_WEIGHTS:
                weight = ACTION_WEIGHTS[metric]
            elif metric == "messages":
                weight = 0 # Messages don't add time directly, chat_time does
            
            user_scores[uid] += (val * weight)

        sorted_users = sorted(user_scores.items(), key=lambda x: x[1], reverse=True)[:10]
        
        desc = []
        for i, (uid, sec) in enumerate(sorted_users, 1):
            desc.append(f"**{i}.** <@{uid}> — `{self.fmt_time(sec)}`")
            
        if not desc: desc = ["Žádná data pro toto období."]
        
        e = discord.Embed(title=f"🏆 Leaderboard ({date_info})", description="\n".join(desc), color=discord.Color.gold())
        e.set_footer(text="Řazeno podle váženého času")
        await itx.followup.send(embed=e)

    @act_group.command(name="backfill", description="ADMIN: Resetuje a přepočítá data do denních statistik.")
    @app_commands.describe(days="Počet dní zpětně (např. 365).")
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill(self, itx: discord.Interaction, days: int = 30):
        await itx.response.defer(thinking=True)
        gid = itx.guild.id
        
        # 1. DELETE OLD DATA
        await itx.followup.send("🗑️ Mazání staré databáze aktivity...")
        
        keys = []
        # Support deletion of both schemas just in case
        async for k in self.r.scan_iter(f"activity:stats:{gid}:*"): keys.append(k)
        async for k in self.r.scan_iter(f"activity:day:*:{gid}:*"): keys.append(k)
        
        if keys:
            chunk_size = 500
            for i in range(0, len(keys), chunk_size):
                await self.r.delete(*keys[i:i+chunk_size])
                
        # 2. START BACKFILL
        discord_epoch = datetime(2015, 1, 1)
        limit_date = datetime.now() - timedelta(days=days)
        if limit_date < discord_epoch: limit_date = discord_epoch
        
        await itx.followup.send(f"⏳ Začínám Backfill od {limit_date.date()}... (Režim: 3min Base + Chars)")
        
        # A. CHAT
        total_msgs = 0
        user_msgs = defaultdict(list) # {uid: [(ts, len, is_reply), ...]}
        channels = [c for c in itx.guild.text_channels if c.permissions_for(itx.guild.me).read_message_history]
        
        for ch in channels:
            try:
                async for msg in ch.history(limit=None, after=limit_date):
                    if msg.author.bot: continue
                    ts = msg.created_at.timestamp()
                    length = len(msg.content)
                    is_reply = (msg.reference is not None)
                    user_msgs[msg.author.id].append((ts, length, is_reply))
                    total_msgs += 1
            except: pass
            
        async with self.r.pipeline() as pipe:
            for uid, msgs in user_msgs.items():
                if not msgs: continue
                msgs.sort(key=lambda x: x[0])
                
                curr_start_ts = msgs[0][0]
                last_seen_ts = msgs[0][0]
                
                # First Message: Lead-In (Base + Reply) + Chars
                # Note: Chars are added for EVERY message now.
                
                # 1. Add Lead-In for the very first session
                first_li = self._calc_lead_in(msgs[0][1], msgs[0][2]) # Base + Reply only?
                # _calc_lead_in was updated to be Base + Reply in this snippet.
                day0 = self._timestamp_to_day(curr_start_ts)
                pipe.incrbyfloat(self._k_day_stats(day0, gid, uid, "chat_time"), first_li)
                
                # Loop all messages
                for i in range(len(msgs)):
                    (t, length, is_reply) = msgs[i]
                    day = self._timestamp_to_day(t)
                    
                    # A. Always add Message Count
                    pipe.incr(self._k_day_stats(day, gid, uid, "messages"))
                    
                    # B. Always add Character Time
                    char_t = length * LEAD_IN_CHAR
                    pipe.incrbyfloat(self._k_day_stats(day, gid, uid, "chat_time"), char_t)
                    
                    # C. Session Logic
                    if i > 0:
                        if t - last_seen_ts <= SESSION_TIMEOUT:
                            # Continue Session
                            last_seen_ts = t
                        else:
                            # End Previous Session
                            dur = last_seen_ts - curr_start_ts
                            day_prev = self._timestamp_to_day(last_seen_ts)
                            pipe.incrbyfloat(self._k_day_stats(day_prev, gid, uid, "chat_time"), dur)
                            
                            # Start NEW Session
                            curr_start_ts = t
                            last_seen_ts = t
                            
                            # Add Lead-In for New Session
                            li = self._calc_lead_in(length, is_reply)
                            pipe.incrbyfloat(self._k_day_stats(day, gid, uid, "chat_time"), li)
                            
                # Final Session End
                dur = last_seen_ts - curr_start_ts
                day_end = self._timestamp_to_day(last_seen_ts)
                pipe.incrbyfloat(self._k_day_stats(day_end, gid, uid, "chat_time"), dur)
            
            await pipe.execute()

        # B. AUDIT LOGS
        audit_ops = 0
        try:
            async for entry in itx.guild.audit_logs(limit=None, after=limit_date):
                if entry.user and not entry.user.bot:
                    metric = None
                    if entry.action == discord.AuditLogAction.ban: metric = "bans"
                    elif entry.action == discord.AuditLogAction.kick: metric = "kicks"
                    elif entry.action == discord.AuditLogAction.unban: metric = "unbans"
                    elif entry.action == discord.AuditLogAction.message_delete: metric = "msg_deleted"
                    elif entry.action == discord.AuditLogAction.member_role_update: metric = "role_updates"
                    elif entry.action == discord.AuditLogAction.member_update:
                        if hasattr(entry.after, "communication_disabled_until") and entry.after.communication_disabled_until:
                            metric = "timeouts"
                            
                    if metric:
                        day = self._timestamp_to_day(entry.created_at.timestamp())
                        await self.r.incr(self._k_day_stats(day, gid, entry.user.id, metric))
                        audit_ops += 1
        except Exception as e:
            print(f"Audit error: {e}")

        # C. VERIFICATIONS
        verifs = 0
        VERIFICATION_LOG_CHANNEL_ID = 1404416148077809705
        log_ch = itx.guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
        if log_ch:
            re_approve = re.compile(r"Schválil <@!?(\d+)>")
            re_bypass = re.compile(r"Manuální bypass - <@!?(\d+)>")
            try:
                async for msg in log_ch.history(limit=None, after=limit_date):
                    if msg.author.id == self.bot.user.id:
                        uid = None
                        m = re_approve.search(msg.content)
                        if m: uid = int(m.group(1))
                        else:
                            m = re_bypass.search(msg.content)
                            if m: uid = int(m.group(1))
                            
                        if uid:
                            day = self._timestamp_to_day(msg.created_at.timestamp())
                            await self.r.incr(self._k_day_stats(day, gid, uid, "verifications"))
                            verifs += 1
            except: pass

        await itx.followup.send(f"✅ **Hotovo!**\n"
                                f"Zpracováno: {total_msgs} zpráv, {audit_ops} audit akcí, {verifs} verifikací.\n"
                                f"Režim: 3 min base + 1s/znak.\n"
                                f"Zkus: `/activity stats after:01-01-2025`.")

    @act_group.command(name="report", description="Zobrazí report aktivity týmu (7 a 30 dní).")
    @app_commands.checks.has_permissions(administrator=True) # Admin only for full report
    async def report(self, itx: discord.Interaction):
        await itx.response.defer()
        gid = itx.guild.id
        today = date.today()
        
        # Ranges
        d_week = today - timedelta(days=7)
        d_month = today - timedelta(days=30)
        
        # We need efficient fetching for ALL users.
        # Scanning all keys is the only way with current Redis structure.
        
        scores_week = defaultdict(float)
        scores_month = defaultdict(float)
        
        # Scan once, bucket into week/month
        pattern = f"activity:day:*:{gid}:*:*"
        async for key in self.r.scan_iter(pattern):
            parts = key.split(":")
            if len(parts) != 6: continue
            
            day_str = parts[2]
            uid = int(parts[4])
            metric = parts[5]
            
            try:
                d = datetime.strptime(day_str, "%Y-%m-%d").date()
            except: continue
            
            val = float(await self.r.get(key) or 0)
            
            w = 1.0
            if metric in ACTION_WEIGHTS: w = ACTION_WEIGHTS[metric]
            elif metric == "messages": w = 0
            
            weighted_val = val * w
            
            # Week
            if d >= d_week:
                scores_week[uid] += weighted_val
            
            # Month
            if d >= d_month:
                scores_month[uid] += weighted_val

        # Sort
        top_week = sorted(scores_week.items(), key=lambda x: x[1], reverse=True)
        top_month = sorted(scores_month.items(), key=lambda x: x[1], reverse=True)
        
        # Format Helper
        def fmt_list(data_list):
            lines = []
            for i, (uid, sec) in enumerate(data_list, 1):
                # We can't easily get names for ALL without fetching members, which might be slow.
                # Use mention to be safe/fast.
                lines.append(f"**{i}.** <@{uid}> — `{self.fmt_time(sec)}`")
            return "\n".join(lines) if lines else "Žádná data."

        # Since lists can be long, we might need to limit them or handle display carefully.
        # User asked for "all", but Discord limits. Let's do TOP 25 per category.
        limit = 25
        
        desc_week = fmt_list(top_week[:limit])
        desc_month = fmt_list(top_month[:limit])
        
        e = discord.Embed(title="📊 Report Aktivity Týmu", color=discord.Color.purple())
        e.add_field(name="📅 Posledních 7 dní", value=desc_week, inline=True)
        e.add_field(name="📅 Posledních 30 dní", value=desc_month, inline=True)
        e.set_footer(text=f"Zobrazeno TOP {limit}. Vygenerováno: {today}")
        
        await itx.followup.send(embed=e)

async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityMonitor(bot))
