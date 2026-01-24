# commands/levels.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands
import random
import math
import redis.asyncio as redis
import time
from shared.redis_client import get_redis_client

class Levels(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # Redis is handled via shared client per-call or pool, 
        # but for high-throughput messaging we might want a local reference if possible, 
        # or just use get_redis_client() every time.
        
    def _calculate_level(self, xp: int) -> int:
        # Formula: XP = 5 * (lvl ^ 2) + 50 * lvl + 100
        # This is difficult to inverse precisely for level from XP without iteration or quadratic formula.
        # Quadratic: 5x^2 + 50x + (100 - XP) = 0
        # x = (-b + sqrt(b^2 - 4ac)) / 2a
        # a=5, b=50, c=100-XP
        if xp < 100: return 0
        a, b, c = 5, 50, 100 - xp
        d = (b**2) - (4*a*c)
        if d < 0: return 0
        level = (-b + math.sqrt(d)) / (2*a)
        return int(level)

    def _xp_for_level(self, level: int) -> int:
        return 5 * (level ** 2) + 50 * level + 100

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # XP Logic
        gid = message.guild.id
        uid = message.author.id
        
        # 1. Check Cooldown
        r = await get_redis_client()
        cooldown_key = f"levels:cooldown:{gid}:{uid}"
        if await r.get(cooldown_key):
            return # On cooldown
            
        # 2. Award XP
        xp_gain = random.randint(15, 25)
        xp_key = f"levels:xp:{gid}" # Sorted Set: Member=UID, Score=TotalXP
        
        # Increment
        new_xp = await r.zincrby(xp_key, xp_gain, str(uid))
        
        # Set Cooldown (60s)
        await r.setex(cooldown_key, 60, "1")
        
        # 3. Check Level Up
        current_level = self._calculate_level(int(new_xp))
        prev_xp = int(new_xp) - xp_gain
        prev_level = self._calculate_level(prev_xp)
        
        if current_level > prev_level:
            # Level Up!
            # Notify (Check config?)
            # For now, simplistic reaction or message if enabled
            # Just react with 🎉 to minimalize spam
            try:
                await message.add_reaction("🎉")
            except: pass

    # --- COMMANDS ---

    @app_commands.command(name="rank", description="Zobrazí tvůj aktuální level a XP.")
    async def rank(self, itx: discord.Interaction, user: discord.Member = None):
        if not user: user = itx.user
        gid = itx.guild.id
        uid = user.id
        
        r = await get_redis_client()
        xp_key = f"levels:xp:{gid}"
        
        score = await r.zscore(xp_key, str(uid))
        total_xp = int(score) if score else 0
        level = self._calculate_level(total_xp)
        
        # Rank position
        rank = await r.zrevrank(xp_key, str(uid))
        rank_display = f"#{rank + 1}" if rank is not None else "N/A"
        
        # Next level progress
        next_level_xp = self._xp_for_level(level + 1)
        prev_level_xp = self._xp_for_level(level) if level > 0 else 0
        
        # Ensure progress bar logic handles negative/0 correctly
        # Needed for current level progress: (Current - PrevBase) / (NextBase - PrevBase)
        # But generic formula is total based.
        # Actually total_xp is cumulative.
        
        xp_needed = next_level_xp - total_xp
        
        e = discord.Embed(title=f"Rank: {user.display_name}", color=discord.Color.green())
        e.set_thumbnail(url=user.display_avatar.url)
        e.add_field(name="Level", value=str(level), inline=True)
        e.add_field(name="Rank", value=rank_display, inline=True)
        e.add_field(name="XP", value=f"{total_xp} / {next_level_xp}", inline=False)
        e.set_footer(text=f"Do dalšího levelu chybí {xp_needed} XP")
        
        await itx.response.send_message(embed=e)

    @app_commands.command(name="leaderboard", description="TOP 10 uživatelů podle XP.")
    async def leaderboard_xp(self, itx: discord.Interaction):
        gid = itx.guild.id
        r = await get_redis_client()
        xp_key = f"levels:xp:{gid}"
        
        # Get top 10
        top_users = await r.zrevrange(xp_key, 0, 9, withscores=True)
        
        if not top_users:
            await itx.response.send_message("Žádná data pro leaderboard.")
            return
            
        desc = []
        for i, (uid, xp) in enumerate(top_users, 1):
            level = self._calculate_level(int(xp))
            desc.append(f"**{i}.** <@{uid}> — **Lvl {level}** ({int(xp)} XP)")
            
        e = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(desc), color=discord.Color.gold())
        await itx.response.send_message(embed=e)

async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
