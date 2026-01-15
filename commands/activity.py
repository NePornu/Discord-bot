# commands/activity.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands
import time
from datetime import datetime, timedelta
import redis.asyncio as redis
import math
from collections import defaultdict

# Redis Stats Keys
# activity:stats:{guild_id}:{user_id}:chat_time  (Total seconds in chat sessions)
# activity:stats:{guild_id}:{user_id}:voice_time (Total seconds in voice)
# activity:stats:{guild_id}:{user_id}:messages   (Total message count)

# Redis State Keys (Ephemeral)
# activity:state:{guild_id}:{user_id}:chat_start  (Timestamp of current session start)
# activity:state:{guild_id}:{user_id}:chat_last   (Timestamp of last message)
# activity:state:{guild_id}:{user_id}:voice_start (Timestamp of join voice)

SESSION_TIMEOUT = 900  # 15 minutes in seconds
REDIS_URL = "redis://redis-hll:6379/0"

class ActivityMonitor(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        self.r = redis.Redis(connection_pool=self.pool)

    async def cog_unload(self):
        await self.pool.disconnect()

    def _k_stats(self, gid: int, uid: int, metric: str) -> str:
        return f"activity:stats:{gid}:{uid}:{metric}"

    def _k_state(self, gid: int, uid: int, key: str) -> str:
        return f"activity:state:{gid}:{uid}:{key}"

    async def _update_session(self, gid: int, uid: int):
        """Standardized logic to update/start chat session"""
        now = time.time()
        k_start = self._k_state(gid, uid, "chat_start")
        k_last = self._k_state(gid, uid, "chat_last")

        last_seen = await self.r.get(k_last)
        
        async with self.r.pipeline() as pipe:
            if last_seen:
                last_seen = float(last_seen)
                if now - last_seen > SESSION_TIMEOUT:
                    # Session timed out -> Close previous session
                    start_time_str = await self.r.get(k_start)
                    if start_time_str:
                        start_time = float(start_time_str)
                        # Duration is from start to LAST seen message (not now)
                        duration = last_seen - start_time
                        if duration > 0:
                            pipe.incrbyfloat(self._k_stats(gid, uid, "chat_time"), duration)
                    
                    # Start NEW session
                    pipe.set(k_start, now)
            else:
                # First activity ever
                pipe.set(k_start, now)
            
            # Always update last seen
            pipe.set(k_last, now)
            # Expire state keys after 24h
            pipe.expire(k_start, 86400)
            pipe.expire(k_last, 86400)
            
            await pipe.execute()

    # --- LISTENER: CHAT ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Update message count (always)
        await self.r.incr(self._k_stats(message.guild.id, message.author.id, "messages"))

        # Update Session
        await self._update_session(message.guild.id, message.author.id)

    # --- LISTENER: REACTION ---
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.Union[discord.Member, discord.User]):
        if user.bot or not reaction.message.guild:
            return
        
        # Adding a reaction counts as activity -> extends session
        await self._update_session(reaction.message.guild.id, user.id)

    # --- LISTENER: INTERACTION ---
    @commands.Cog.listener()
    async def on_interaction(self, itx: discord.Interaction):
        if itx.user.bot or not itx.guild:
            return
            
        # Clicking button / using command -> extends session
        await self._update_session(itx.guild.id, itx.user.id)

    # --- LISTENER: VOICE ---
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot: return
        
        gid = member.guild.id
        uid = member.id
        now = time.time()
        k_voice = self._k_state(gid, uid, "voice_start")

        # Check effective state (considering mute/deafen as inactive? Or just verified?)
        # For moderation, being in voice usually counts, even if muted (listening).
        # We only stop tracking if they leave or are completely disconnected.
        
        is_in_voice = after.channel is not None
        was_in_voice = before.channel is not None
        
        # Determine if we should treat this as "Active"
        # Optional: We could filter for specific channels here.
        
        if is_in_voice and not was_in_voice:
            # JOINED
            await self.r.set(k_voice, now)
        elif was_in_voice and not is_in_voice:
            # LEFT
            start_str = await self.r.get(k_voice)
            if start_str:
                start = float(start_str)
                duration = now - start
                if duration > 0:
                    await self.r.incrbyfloat(self._k_stats(gid, uid, "voice_time"), duration)
                await self.r.delete(k_voice)

    # --- PERIODIC: FLUSH SESSIONS (Optional) ---
    # To make sure stats are updated even if user doesn't logout or stop talking.
    # For now, we rely on lazy updates or on-demand calculation.

    async def get_current_session_time(self, gid: int, uid: int, now: float) -> float:
        """Calculate pending time in current open sessions"""
        pending = 0.0
        
        # Chat / Activity
        k_start = self._k_state(gid, uid, "chat_start")
        k_last = self._k_state(gid, uid, "chat_last")
        start = await self.r.get(k_start)
        last = await self.r.get(k_last)
        
        if start and last:
            s, l = float(start), float(last)
            if now - l < SESSION_TIMEOUT:
                 # Session is still active, add time so far (start to last)
                 # Note: We technically add (last - start). The time between last and now is "idle" until they talk again.
                 pending += (l - s)
        
        # Voice
        k_voice = self._k_state(gid, uid, "voice_start")
        v_start = await self.r.get(k_voice)
        if v_start:
            # Voice is continuous, so add (now - start)
            pending += (now - float(v_start))
            
        return pending

    def fmt_time(self, seconds: float) -> str:
        if seconds < 60: return f"{int(seconds)}s"
        m, s = divmod(int(seconds), 60)
        h, m = divmod(m, 60)
        if h > 0: return f"{h}h {m}m"
        return f"{m}m"

    # --- COMMANDS ---
    act_group = app_commands.Group(name="activity", description="Sledování aktivity moderátorů")

    @act_group.command(name="stats", description="Zobrazí aktivitu uživatele.")
    @app_commands.describe(user="Uživatel (default: ty)")
    async def stats(self, itx: discord.Interaction, user: discord.Member = None):
        await itx.response.defer()
        
        if not user: user = itx.user
        gid = itx.guild.id
        uid = user.id
        
        # Fetch stored stats
        chat_t = float(await self.r.get(self._k_stats(gid, uid, "chat_time")) or 0)
        voice_t = float(await self.r.get(self._k_stats(gid, uid, "voice_time")) or 0)
        msgs = int(await self.r.get(self._k_stats(gid, uid, "messages")) or 0)
        
        # Add pending current session times
        pending = await self.get_current_session_time(gid, uid, time.time())
        # We can't easily split pending into chat/voice without querying redis twice more or refactoring
        # For simplicity, we'll list stored + note "Current active session"
        
        # Wait, get_current_session_time returned total. Let's do it properly.
        # Re-querying state for display correctness.
        now = time.time()
        
        # Chat Pending
        k_cs = self._k_state(gid, uid, "chat_start")
        k_cl = self._k_state(gid, uid, "chat_last")
        cs = await self.r.get(k_cs)
        cl = await self.r.get(k_cl)
        if cs and cl and (now - float(cl) < SESSION_TIMEOUT):
            chat_t += (float(cl) - float(cs))
            
        # Voice Pending
        k_vs = self._k_state(gid, uid, "voice_start")
        vs = await self.r.get(k_vs)
        if vs:
            voice_t += (now - float(vs))

        e = discord.Embed(title=f"📊 Aktivita: {user.display_name}", color=discord.Color.green())
        e.set_thumbnail(url=user.display_avatar.url)
        
        e.add_field(name="💬 Chat Time", value=self.fmt_time(chat_t), inline=True)
        e.add_field(name="🎙️ Voice Time", value=self.fmt_time(voice_t), inline=True)
        e.add_field(name="📩 Zpráv", value=str(msgs), inline=True)
        
        total_h = (chat_t + voice_t) / 3600
        e.add_field(name="⏱️ Celkem", value=f"{total_h:.1f} hodin", inline=False)
        
        await itx.followup.send(embed=e)

    @act_group.command(name="leaderboard", description="TOP 10 nejaktivnějších (Chat + Voice).")
    async def leaderboard(self, itx: discord.Interaction):
        await itx.response.defer()
        gid = itx.guild.id
        
        # Scan all users in redis for this guild
        # Warning: SCAN can be slow on huge DBs, but for a bot specific DB it's fine.
        # Pattern: activity:stats:{gid}:*:chat_time
        
        users_stats = defaultdict(float)
        
        # Helper to sum up
        async def sum_metric(metric):
            async for key in self.r.scan_iter(f"activity:stats:{gid}:*:{metric}"):
                # key format: activity:stats:GID:UID:METRIC
                try:
                    parts = key.split(":")
                    uid = int(parts[3])
                    val = float(await self.r.get(key) or 0)
                    users_stats[uid] += val
                except: pass

        await sum_metric("chat_time")
        await sum_metric("voice_time")
        
        # Sort
        sorted_users = sorted(users_stats.items(), key=lambda x: x[1], reverse=True)[:10]
        
        desc = []
        for i, (uid, total_sec) in enumerate(sorted_users, 1):
            line = f"**{i}.** <@{uid}> — `{self.fmt_time(total_sec)}`"
            desc.append(line)
            
        if not desc:
            desc = ["Žádná data."]
            
        e = discord.Embed(title="🏆 Leaderboard Aktivity (Chat + Voice)", description="\n".join(desc), color=discord.Color.gold())
        await itx.followup.send(embed=e)

    @act_group.command(name="backfill", description="ADMIN: Zpětně dopočítá statistiky z historie chatu.")
    @app_commands.describe(days="Počet dní zpětně (např. 365).")
    @app_commands.checks.has_permissions(administrator=True)
    async def backfill(self, itx: discord.Interaction, days: int = 30):
        await itx.response.defer(thinking=True)
        
        gid = itx.guild.id
        limit_date = datetime.now() - timedelta(days=days)
        
        await itx.followup.send(f"⏳ Začínám backfill historie za {days} dní...\nProcházím kanály, může to trvat několik minut.")
        
        # 1. Reset Chat Stats (ONLY chat)
        # We need to be careful not to delete Voice stats
        # Scan and delete chat_time and messages keys
        keys_to_delete = []
        async for k in self.r.scan_iter(f"activity:stats:{gid}:*:chat_time"): keys_to_delete.append(k)
        async for k in self.r.scan_iter(f"activity:stats:{gid}:*:messages"): keys_to_delete.append(k)
        
        if keys_to_delete:
            await self.r.delete(*keys_to_delete)
            
        # 2. Iterate channels
        total_msgs = 0
        user_msgs = defaultdict(list)  # {uid: [timestamp, timestamp...]}
        
        channels = [c for c in itx.guild.text_channels if c.permissions_for(itx.guild.me).read_message_history]
        
        for ch in channels:
            try:
                # History iterator
                async for msg in ch.history(limit=None, after=limit_date):
                    if msg.author.bot: continue
                    
                    uid = msg.author.id
                    t = msg.created_at.timestamp()
                    user_msgs[uid].append(t)
                    total_msgs += 1
                    
            except Exception as e:
                print(f"Error reading {ch.name}: {e}")
                
        # 3. Calculate Sessions per User
        # This is CPU bound, but for typical server sizes ( < 1M msgs) it's fine in python
        # sessions logic: sort timestamps -> diff < 5min -> sum
        
        async with self.r.pipeline() as pipe:
            for uid, timestamps in user_msgs.items():
                timestamps.sort()
                
                chat_time = 0.0
                msg_count = len(timestamps)
                
                if msg_count > 0:
                    current_start = timestamps[0]
                    last_seen = timestamps[0]
                    
                    for t in timestamps[1:]:
                        if t - last_seen <= SESSION_TIMEOUT:
                            # Extend session
                            last_seen = t
                        else:
                            # End session
                            duration = last_seen - current_start
                            # Optional: Add minimum session time per message? No, strict session logic.
                            # If single message session, duration is 0 for that session.
                            chat_time += duration
                            
                            # Start new
                            current_start = t
                            last_seen = t
                            
                    # End final session
                    chat_time += (last_seen - current_start)
                
                # Update Redis
                pipe.set(self._k_stats(gid, uid, "chat_time"), chat_time)
                pipe.set(self._k_stats(gid, uid, "messages"), msg_count)
            
            await pipe.execute()
            
        await itx.followup.send(f"✅ **Backfill dokončen!**\nZpracováno zpráv: {total_msgs}\nUnikátních uživatelů: {len(user_msgs)}\n\nNyní můžeš použít `/activity stats`.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ActivityMonitor(bot))
