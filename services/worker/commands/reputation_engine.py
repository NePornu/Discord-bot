import discord
from discord.ext import commands, tasks
import json
import time
import math
import logging
from shared.python.redis_client import get_redis_client
from shared.python.config import config

logger = logging.getLogger("ReputationEngine")

class ReputationEngine(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.recalculation_task.start()

    def cog_unload(self):
        self.recalculation_task.cancel()

    @tasks.loop(minutes=10)
    async def recalculation_task(self):
        """Periodically recaliculates Trust Scores and identifies abuse patterns across all guilds."""
        r = await get_redis_client()
        try:
            # 1. Get all guilds the bot is in
            guild_ids = await r.smembers("bot:guilds")
            for gid in guild_ids:
                # 2. Identify active users in the reputation system for this guild
                # We can use the leaderboard ZSET to find relevant users
                lb_key = f"rep:leaderboard:{gid}"
                active_users = await r.zrange(lb_key, 0, -1)
                
                for uid in active_users:
                    try:
                        await self.calculate_user_trust(r, gid, uid)
                    except Exception as e:
                        logger.error(f"Error calculating trust for user {uid} in guild {gid}: {e}")
        except Exception as e:
            logger.error(f"Reputation recalculation loop error: {e}")
        finally:
            await r.aclose()

    async def calculate_user_trust(self, r, guild_id, user_id):
        """Calculates a trust score based on unique givers, weighted rep, and donor concentration."""
        
        # Keys
        events_key = f"rep:events:{user_id}"
        givers_key = f"rep:givers:{user_id}"
        profile_key = f"rep:profile:{user_id}"
        
        # 1. Fetch data
        # Fetch unique givers count
        unique_givers_count = await r.scard(givers_key)
        if unique_givers_count == 0:
            return

        # Fetch last 100 events
        events_raw = await r.lrange(events_key, 0, -1)
        events = [json.loads(e) for e in events_raw]
        
        # 2. Weighted Reputation Calculation
        total_weighted_rep = 0.0
        donor_counts = {}
        
        for ev in events:
            giver_id = ev.get("giver_id")
            if not giver_id: continue
            
            # Get giver's reputation for weighting
            giver_rep_raw = await r.get(f"rep:total:{giver_id}")
            giver_rep = int(giver_rep_raw) if giver_rep_raw else 0
            
            # Weight formula: log10(rep + 10) * base_multiplier
            # Someone with 100 rep gives ~2x weight of someone with 0 rep.
            weight = math.log10(giver_rep + 10)
            total_weighted_rep += weight
            
            # Donor concentration tracking
            donor_counts[giver_id] = donor_counts.get(giver_id, 0) + 1

        # 3. Abuse Detection
        # A. Donor Concentration: One person giving too many scores
        max_from_one = max(donor_counts.values()) if donor_counts else 0
        concentration_ratio = max_from_one / len(events) if events else 0
        
        abuse_score = 0.0
        if concentration_ratio > 0.4: # More than 40% from one person
            abuse_score += (concentration_ratio - 0.4) * 5
            
        # B. Clique Detection (Reciprocity)
        # Check if the user also gave rep back to top givers recently
        top_donors = sorted(donor_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        for donor_id, count in top_donors:
            donor_events_key = f"rep:events:{donor_id}"
            donor_events_raw = await r.lrange(donor_events_key, 0, 50) # check last 50
            gave_back = any(json.loads(e).get("giver_id") == user_id for e in donor_events_raw)
            if gave_back and count > 2:
                abuse_score += 1.0 # Reciprocal giving penalty

        # 4. Final Trust Score Formula
        # (Total Weighted Rep * log(unique_givers + 1)) / (1 + abuse_score)
        # log increases trust as more unique people recognize the user.
        social_multiplier = math.log(unique_givers_count + 1, 2)
        trust_score = (total_weighted_rep * social_multiplier) / (1 + abuse_score)
        
        # 5. Determine Rank
        rank = "New Member"
        if trust_score > 50: rank = "Trusted Legend"
        elif trust_score > 25: rank = "Master Helper"
        elif trust_score > 10: rank = "Active Helper"
        elif trust_score > 2: rank = "Contributor"

        # 6. Save to Profile Hash
        await r.hset(profile_key, mapping={
            "trust_score": str(round(trust_score, 2)),
            "abuse_score": str(round(abuse_score, 2)),
            "rank": rank,
            "unique_givers": unique_givers_count,
            "weighted_rep": str(round(total_weighted_rep, 2)),
            "last_recalc": int(time.time())
        })
        
        # Add to trust leaderboard
        await r.zadd(f"rep:trust_leaderboard:{guild_id}", {user_id: trust_score})

    @commands.group(name="rep_admin")
    @commands.has_permissions(administrator=True)
    async def rep_admin(self, ctx):
        """Administrace reputačního systému."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Použij /rep_admin recalc nebo /rep_admin flag")

    @rep_admin.command(name="recalc")
    async def recalc(self, ctx):
        """Ručně spustí přepočet trust scores pro aktuální server."""
        await ctx.send("⏳ Spouštím přepočet reputačních skóre...")
        r = await get_redis_client()
        try:
            lb_key = f"rep:leaderboard:{ctx.guild.id}"
            active_users = await r.zrange(lb_key, 0, -1)
            for uid in active_users:
                await self.calculate_user_trust(r, ctx.guild.id, uid)
            await ctx.send(f"✅ Přepočteno {len(active_users)} uživatelů.")
        finally:
            await r.aclose()

async def setup(bot):
    await bot.add_cog(ReputationEngine(bot))
