
import discord
from discord.ext import commands
from discord import app_commands
import redis.asyncio as redis
from config import config
from shared.redis_client import get_redis_client
from datetime import datetime
import time

class AnalyticsTrackingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.voice_join_times = {}

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        guild_id = member.guild.id
        user_id = member.id
        now = time.time()

        
        if before.channel is None and after.channel is not None:
            self.voice_join_times[(guild_id, user_id)] = now

        
        elif before.channel is not None and after.channel is None:
            await self._record_voice_time(guild_id, user_id, now)

        
        elif before.channel is not None and after.channel is not None and before.channel.id != after.channel.id:
            await self._record_voice_time(guild_id, user_id, now)
            self.voice_join_times[(guild_id, user_id)] = now

    async def _record_voice_time(self, guild_id, user_id, now):
        start_time = self.voice_join_times.pop((guild_id, user_id), None)
        if start_time:
            duration = int(now - start_time)
            if duration > 0:
                r = await get_redis_client()
                try:
                    
                    await r.zincrby(f"stats:voice_duration:{guild_id}", duration, str(user_id))
                except Exception as e:
                    print(f"Error recording voice time: {e}")

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command):
        if interaction.guild:
            r = await get_redis_client()
            try:
                
                await r.hincrby(f"stats:commands:{interaction.guild.id}", command.name, 1)
            except Exception as e:
                print(f"Error recording command usage: {e}")

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return

        r = await get_redis_client()
        try:
            emoji_str = str(reaction.emoji)
            
            await r.zincrby(f"stats:emojis:{reaction.message.guild.id}", 1, emoji_str)
        except Exception as e:
            print(f"Error recording reaction usage: {e}")

async def setup(bot):
    await bot.add_cog(AnalyticsTrackingCog(bot))
