

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
        
        
        
        
    async def _get_formula(self):
        r = await get_redis_client()
        conf = await r.hgetall("config:xp_formula")
        return (
            int(conf.get("a", 50)),
            int(conf.get("b", 200)), 
            int(conf.get("c", 100)),
            int(conf.get("min", 15)),
            int(conf.get("max", 25)),
            int(conf.get("voice_min", 5)),
            int(conf.get("voice_max", 10))
        )

    async def _calculate_level(self, xp: int) -> int:
        
        
        a, b, c_base, _, _, _, _ = await self._get_formula()
        
        if xp < c_base: return 0
        c = c_base - xp
        
        d = (b**2) - (4*a*c)
        if d < 0: return 0
        level = (-b + math.sqrt(d)) / (2*a)
        return int(level)

    async def _xp_for_level(self, level: int) -> int:
        a, b, c, _, _, _, _ = await self._get_formula()
        return a * (level ** 2) + b * level + c

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        
        gid = message.guild.id
        uid = message.author.id
        
        
        r = await get_redis_client()
        cooldown_key = f"levels:cooldown:{gid}:{uid}"
        if await r.get(cooldown_key):
            return 
            
        
        
        _, _, _, min_xp, max_xp, _, _ = await self._get_formula()
        
        if min_xp > max_xp: min_xp, max_xp = max_xp, min_xp
        xp_gain = random.randint(min_xp, max_xp)
        
        xp_key = f"levels:xp:{gid}" 
        
        
        new_xp = await r.zincrby(xp_key, xp_gain, str(uid))
        
        
        await r.setex(cooldown_key, 60, "1")
        
        
        current_level = await self._calculate_level(int(new_xp))
        prev_xp = int(new_xp) - xp_gain
        prev_level = await self._calculate_level(prev_xp)
        


    

    @app_commands.command(name="rank", description="Zobrazí tvůj aktuální level a XP.")
    async def rank(self, itx: discord.Interaction, user: discord.Member = None):
        if not user: user = itx.user
        gid = itx.guild.id
        uid = user.id
        
        r = await get_redis_client()
        xp_key = f"levels:xp:{gid}"
        
        score = await r.zscore(xp_key, str(uid))
        total_xp = int(score) if score else 0
        level = await self._calculate_level(total_xp)
        
        
        rank = await r.zrevrank(xp_key, str(uid))
        rank_display = f"#{rank + 1}" if rank is not None else "N/A"
        
        
        next_level_xp = await self._xp_for_level(level + 1)
        prev_level_xp = await self._xp_for_level(level) if level > 0 else 0
        
        
        
        
        
        
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
        
        
        top_users = await r.zrevrange(xp_key, 0, 9, withscores=True)
        
        if not top_users:
            await itx.response.send_message("Žádná data pro leaderboard.")
            return
            
        desc = []
        for i, (uid, xp) in enumerate(top_users, 1):
            level = await self._calculate_level(int(xp))
            desc.append(f"**{i}.** <@{uid}> — **Lvl {level}** ({int(xp)} XP)")
            
        e = discord.Embed(title="🏆 XP Leaderboard", description="\n".join(desc), color=discord.Color.gold())
        await itx.response.send_message(embed=e)

    async def cog_load(self):
        self.voice_xp_loop.start()

    async def cog_unload(self):
        self.voice_xp_loop.cancel()

    @tasks.loop(minutes=1)
    async def voice_xp_loop(self):
        """Award XP to users in voice channels every minute."""
        try:
            
            _, _, _, _, _, voice_min, voice_max = await self._get_formula()
            
            
            if voice_max <= 0: return

            r = await get_redis_client()
            
            
            for guild in self.bot.guilds:
                xp_key = f"levels:xp:{guild.id}"
                
                
                for vc in guild.voice_channels:
                    
                    if guild.afk_channel and vc.id == guild.afk_channel.id:
                        continue
                        
                    
                    for member in vc.members:
                        if member.bot: continue
                        
                        
                        
                        
                        gain = random.randint(voice_min, voice_max)
                        await r.zincrby(xp_key, gain, str(member.id))
                        
                        
                        
                        
                        
                        
                        
                        new_xp = await r.zscore(xp_key, str(member.id)) 
                        new_xp = int(float(new_xp)) 
                        
                        prev_xp = new_xp - gain
                        
                        
                        cur_lvl = await self._calculate_level(new_xp)
                        prev_lvl = await self._calculate_level(prev_xp)
                        
                        if cur_lvl > prev_lvl:
                            
                            
                            
                            pass

        except Exception as e:
            print(f"Error in voice_xp_loop: {e}")

    @voice_xp_loop.before_loop
    async def before_voice_loop(self):
        await self.bot.wait_until_ready()

async def setup(bot: commands.Bot):
    await bot.add_cog(Levels(bot))
