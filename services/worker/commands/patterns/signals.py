import json
import logging
from datetime import datetime, timezone
import discord
from discord.ext import commands
from .common import K_MSG, K_KW, K_FIRST, K_REPLY, K_DIARY, K_QUESTION, K_JOIN, PAT_TTL, get_today, is_staff, is_diary_channel
from shared.python.pattern_logic import KEYWORD_GROUPS, count_keywords, count_words

logger = logging.getLogger("PatternDetector")

class PatternSignals(commands.Cog):
    def __init__(self, bot, guild_id, redis_getter):
        self.bot = bot
        self._guild_id = guild_id
        self._get_redis = redis_getter

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        if message.guild.id != self._guild_id:
            return
            
        if isinstance(message.author, discord.Member) and is_staff(message.author):
            return

        r = await self._get_redis()
        try:
            gid = message.guild.id
            uid = message.author.id
            today = get_today()
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
            if is_diary_channel(message.channel):
                if is_reply and message.reference.message_id:
                    try:
                        ref_msg = message.reference.cached_message
                        if ref_msg is None:
                            try:
                                ref_msg = await message.channel.fetch_message(message.reference.message_id)
                            except Exception:
                                ref_msg = None
                        if ref_msg and ref_msg.author.id != uid:
                            diary_key = K_DIARY(gid, ref_msg.author.id)
                            pipe.lrem(diary_key, 0, str(ref_msg.id))
                    except Exception:
                        pass
                else:
                    diary_key = K_DIARY(gid, uid)
                    entry = json.dumps({"msg_id": str(message.id), "ts": int(message.created_at.timestamp())})
                    pipe.lpush(diary_key, entry)
                    pipe.ltrim(diary_key, 0, 9)
                    pipe.expire(diary_key, PAT_TTL)

            # --- Question tracking ---
            if text.rstrip().endswith("?") and len(text) > 10:
                q_key = K_QUESTION(gid, uid, message.id)
                pipe.set(q_key, str(int(message.created_at.timestamp())), ex=24 * 3600)

            # --- Join date tracking ---
            if isinstance(message.author, discord.Member) and message.author.joined_at:
                join_key = K_JOIN(gid, uid)
                pipe.setnx(join_key, str(int(message.author.joined_at.timestamp())))
                pipe.expire(join_key, PAT_TTL)

            # --- Hour tracking ---
            hour = message.created_at.hour
            hour_key = f"pat:hour:{gid}:{uid}:{today}"
            pipe.hincrby(hour_key, str(hour), 1)
            pipe.expire(hour_key, PAT_TTL)

            await pipe.execute()
        except Exception as e:
            logger.error(f"on_message signal error: {e}")
        finally:
            await r.aclose()

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.author or message.author.bot or not message.guild:
            return
        if message.guild.id != self._guild_id:
            return
        try:
            r = await self._get_redis()
            key = K_DEL(message.guild.id, message.author.id, get_today())
            await r.incr(key)
            await r.expire(key, PAT_TTL)
            await r.aclose()
        except Exception as e:
            logger.error(f"on_message_delete signal error: {e}")

    @commands.Cog.listener()
    async def on_raw_message_edit(self, payload: discord.RawMessageUpdateEvent):
        if not payload.guild_id or payload.guild_id != self._guild_id:
            return
        data = payload.data
        author = data.get("author", {})
        if author.get("bot", False):
            return
        uid = int(author.get("id", 0))
        if uid == 0:
            return
        try:
            r = await self._get_redis()
            key = K_EDIT(payload.guild_id, uid, get_today())
            await r.incr(key)
            await r.expire(key, PAT_TTL)
            await r.aclose()
        except Exception as e:
            logger.error(f"on_raw_message_edit signal error: {e}")

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        import os
        if os.getenv("BOT_LITE_MODE") == "1":
            return
        if member.bot or member.guild.id != self._guild_id:
            return
        try:
            r = await self._get_redis()
            join_key = K_JOIN(member.guild.id, member.id)
            await r.set(join_key, str(int(member.joined_at.timestamp())), ex=PAT_TTL)
            await r.aclose()
        except Exception as e:
            logger.error(f"on_member_join signal error: {e}")
