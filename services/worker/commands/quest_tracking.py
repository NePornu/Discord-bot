
import discord
from discord.ext import commands
from discord import app_commands
import re
from datetime import datetime, timezone
from shared.python.config import config
from shared.python.redis_client import get_redis_client
import logging

logger = logging.getLogger("QuestTracking")

class QuestTrackingCog(commands.Cog):
    """Tracks Nelednáček habit quest messages and awards roles."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.quest_regex = re.compile(r"^Quest\s*—", re.IGNORECASE)

    def _get_redis_key(self, guild_id: int, user_id: int):
        return f"quest:days:{guild_id}:{user_id}"

    async def _get_user_days(self, r, guild_id: int, user_id: int) -> set[str]:
        """Returns a set of unique days (YYYYMMDD) the user has completed a quest."""
        days = await r.smembers(self._get_redis_key(guild_id, user_id))
        return set(days) if days else set()

    async def _add_quest_day(self, r, guild_id: int, user_id: int, day_str: str):
        """Adds a day to the user's quest history in Redis."""
        await r.sadd(self._get_redis_key(guild_id, user_id), day_str)

    async def _check_and_assign_roles(self, member: discord.Member, day_count: int):
        """Checks if a user reached a milestone and assigns the corresponding role."""
        if day_count in config.HABIT_ROLES:
            role_id = config.HABIT_ROLES[day_count]
            role = member.guild.get_role(role_id)
            if role and role not in member.roles:
                try:
                    await member.add_roles(role, reason=f"Nelednáček milestone: {day_count} dní")
                    logger.info(f"Assigned role {role.name} to {member.display_name} for {day_count} days.")
                    return role
                except Exception as e:
                    logger.error(f"Failed to assign role {role_id} to {member.id}: {e}")
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        # Optional: Restrict to specific channel if configured
        quest_channel_id = getattr(config, "QUEST_CHANNEL_ID", None)
        if quest_channel_id:
             if message.channel.id != quest_channel_id:
                 return

        if self.quest_regex.match(message.content):
            guild_id = message.guild.id
            user_id = message.author.id
            # Use message creation time for dates
            day_str = message.created_at.astimezone(timezone.utc).strftime("%Y%m%d")

            # Check if within challenge period
            start_date = getattr(config, "CHALLENGE_START_DATE", "20260210")
            end_date = getattr(config, "CHALLENGE_END_DATE", "20260310")
            
            if not (start_date <= day_str <= end_date):
                # Optionally send a DM or reply if they are posting outside the challenge period
                return

            r = await get_redis_client()
            try:
                await self._add_quest_day(r, guild_id, user_id, day_str)
                days = await self._get_user_days(r, guild_id, user_id)
                day_count = len(days)

                role_awarded = await self._check_and_assign_roles(message.author, day_count)
                
                # React to confirm processing
                await message.add_reaction("✅")
                if role_awarded:
                    await message.reply(f"🔥 Gratulace! Dosáhl jsi milníku **{day_count} dní** a získáváš roli **{role_awarded.name}**! 👑")
                
            except Exception as e:
                logger.error(f"Error processing quest message from {user_id}: {e}")
            finally:
                if r:
                    await r.aclose()

    @commands.command(name="quest_stats")
    async def quest_stats(self, ctx: commands.Context, member: discord.Member = None):
        """Zobrazí tvůj aktuální pokrok v Nelednáčku."""
        member = member or ctx.author
        r = await get_redis_client()
        try:
            days = await self._get_user_days(r, ctx.guild.id, member.id)
            days_sorted = sorted(list(days))
            count = len(days_sorted)
            
            embed = discord.Embed(
                title=f"📊 Nelednáček — {member.display_name}",
                color=discord.Color.blue(),
                timestamp=datetime.now()
            )
            embed.add_field(name="Splněných dní", value=f"**{count}**", inline=True)
            
            if days_sorted:
                last_day = datetime.strptime(days_sorted[-1], "%Y%m%d").strftime("%d.%m.%Y")
                embed.add_field(name="Poslední quest", value=last_day, inline=True)
            
            # Progress to next role
            milestones = sorted(config.HABIT_ROLES.keys())
            next_milestone = next((m for m in milestones if m > count), None)
            
            if next_milestone:
                progress_bar = "🟢" * (count % 5) + "⚪" * (5 - (count % 5)) # Simple visualization
                embed.add_field(name="Další milník", value=f"{next_milestone} dní ({next_milestone - count} zbývá)", inline=False)
            else:
                embed.add_field(name="Status", value="👑 Habit Boss! Maximální level dosažen.", inline=False)

            await ctx.send(embed=embed)
        except Exception as e:
            await ctx.send(f"❌ Chyba při získávání statistik: {e}")
        finally:
            if r:
                await r.aclose()

    @commands.command(name="quest_backfill")
    @commands.has_permissions(administrator=True)
    async def quest_backfill(self, ctx: commands.Context, channel: discord.TextChannel = None, limit: int = 1000):
        """Prohledá historii kanálu a doplní chybějící questy."""
        channel = channel or ctx.channel
        await ctx.send(f"⏳ Zahajuji zpětné vyhodnocení kanálu {channel.mention} (limit {limit} zpráv)...")
        
        start_date = getattr(config, "CHALLENGE_START_DATE", "20260210")
        end_date = getattr(config, "CHALLENGE_END_DATE", "20260310")
        
        count_added = 0
        r = await get_redis_client()
        try:
            async for message in channel.history(limit=limit):
                if message.author.bot:
                    continue
                
                if self.quest_regex.match(message.content):
                    day_str = message.created_at.astimezone(timezone.utc).strftime("%Y%m%d")
                    if start_date <= day_str <= end_date:
                        await r.sadd(self._get_redis_key(ctx.guild.id, message.author.id), day_str)
                        count_added += 1
            
            await ctx.send(f"✅ Dokončeno. Zpracováno questů: {count_added}")
        except Exception as e:
            await ctx.send(f"❌ Chyba při backfillu: {e}")
        finally:
            if r:
                await r.aclose()

async def setup(bot: commands.Bot):
    await bot.add_cog(QuestTrackingCog(bot))
