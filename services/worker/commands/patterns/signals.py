import json
import logging
from datetime import datetime, timezone
import discord
from discord.ext import commands
from .common import K_MSG, K_KW, K_FIRST, K_REPLY, K_DIARY, K_QUESTION, K_JOIN, K_STAFF_RESPONSE, K_MSG_LEN, K_LAST_ACTIVITY, PAT_TTL, get_today, is_staff, is_diary_channel
from shared.python.pattern_logic import KEYWORD_GROUPS, count_keywords, count_words, is_analytical_style

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
            
        r = await self._get_redis()
        try:
            gid = message.guild.id
            uid = message.author.id
            today = get_today()
            text = message.content or ""
            wc = count_words(text)
            is_reply = message.reference is not None
            mentions = len(message.mentions)
            author_is_staff = isinstance(message.author, discord.Member) and is_staff(message.author)

            # --- Klient Thread Note Capturing ---
            if isinstance(message.channel, discord.Thread) and author_is_staff:
                from .common import K_THREAD_UID, K_NOTES
                uid_str = await r.get(K_THREAD_UID(message.channel.id))
                if uid_str:
                    target_uid = int(uid_str)
                    notes_data = await r.get(K_NOTES(gid, target_uid))
                    notes_list = json.loads(notes_data) if notes_data else []
                    notes_list.append({
                        "ts": int(message.created_at.timestamp()),
                        "author": message.author.display_name,
                        "content": text
                    })
                    await r.set(K_NOTES(gid, target_uid), json.dumps(notes_list[-50:]), ex=PAT_TTL)
                    try: await message.add_reaction("📝")
                    except: pass
                    # We don't need to process this message for other patterns
                    return

            pipe = r.pipeline()

            # --- Aggregate message stats (Skip staff for some metrics) ---
            if not author_is_staff:
                msg_key = K_MSG(gid, uid, today)
                pipe.hincrby(msg_key, "word_count", wc)
                pipe.hincrby(msg_key, "msg_count", 1)
                pipe.hincrby(msg_key, "char_count", len(text))
                if is_reply:
                    pipe.hincrby(msg_key, "reply_count", 1)
                if mentions > 0:
                    pipe.hincrby(msg_key, "mention_count", mentions)
                pipe.expire(msg_key, PAT_TTL)
                # Track last activity for follow-ups
                pipe.set(K_LAST_ACTIVITY(gid, uid), str(int(message.created_at.timestamp())), ex=PAT_TTL)

            # --- Keyword scanning & Analytical style ---
            if len(text) > 3:
                for group in KEYWORD_GROUPS:
                    hits = count_keywords(text, group)
                    if hits > 0:
                        kw_key = K_KW(gid, uid, today, group)
                        pipe.incrby(kw_key, hits)
                        pipe.expire(kw_key, PAT_TTL)
                
                if is_analytical_style(text):
                    pipe.incr(K_KW(gid, uid, today, "analytical_hits"))
                    pipe.expire(K_KW(gid, uid, today, "analytical_hits"), PAT_TTL)

            # --- Message length caching (for deletion tracking) ---
            mlen_key = K_MSG_LEN(gid, message.id)
            pipe.set(mlen_key, str(len(text)), ex=3600) # Only cache for 1 hour

            # --- First message tracking ---
            if not author_is_staff:
                first_key = K_FIRST(gid, uid)
                pipe.hsetnx(first_key, "msg_id", str(message.id))
                pipe.hsetnx(first_key, "timestamp", str(int(message.created_at.timestamp())))
                pipe.hsetnx(first_key, "channel_id", str(message.channel.id))
                pipe.expire(first_key, PAT_TTL)

            # --- Staff Response Tracking ---
            if author_is_staff and is_reply and message.reference.message_id:
                try:
                    ref_msg = message.reference.cached_message or await message.channel.fetch_message(message.reference.message_id)
                    if ref_msg and not is_staff(ref_msg.author) and not ref_msg.author.bot:
                        # Check if this was a response to their FIRST message
                        first_data = await r.hgetall(K_FIRST(gid, ref_msg.author.id))
                        if first_data.get("msg_id") == str(ref_msg.id):
                            # Record time to respond
                            diff = int(message.created_at.timestamp()) - int(first_data["timestamp"])
                            pipe.setnx(K_STAFF_RESPONSE(gid, ref_msg.author.id), str(diff))
                            pipe.expire(K_STAFF_RESPONSE(gid, ref_msg.author.id), PAT_TTL)
                except Exception:
                    pass

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
                            pipe.lrem(diary_key, 0, json.dumps({"msg_id": str(ref_msg.id), "ts": int(ref_msg.created_at.timestamp())}, sort_keys=True))
                    except Exception:
                        pass
                else:
                    diary_key = K_DIARY(gid, uid)
                    entry = json.dumps({"msg_id": str(message.id), "ts": int(message.created_at.timestamp())}, sort_keys=True)
                    pipe.lpush(diary_key, entry)
                    pipe.ltrim(diary_key, 0, 9)
                    pipe.expire(diary_key, PAT_TTL)

            # --- Question tracking ---
            if text.rstrip().endswith("?") and len(text) > 10:
                q_key = K_QUESTION(gid, uid, message.id)
                pipe.set(q_key, str(int(message.created_at.timestamp())), ex=24 * 3600)

            # --- Join date tracking ---
            if isinstance(message.author, discord.Member) and message.author.joined_at and not author_is_staff:
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
            gid, uid, today = message.guild.id, message.author.id, get_today()
            
            # Record standard deletion
            key = f"pat:del:{gid}:{uid}:{today}"
            await r.incr(key)
            await r.expire(key, PAT_TTL)
            
            # Check if it was a LONG message (for Post-dumping Shame)
            mlen_val = await r.get(K_MSG_LEN(gid, message.id))
            if mlen_val and int(mlen_val) > 500: # Over 500 chars 
                long_del_key = f"pat:del_long:{gid}:{uid}:{today}"
                await r.incr(long_del_key)
                await r.expire(long_del_key, PAT_TTL)
                
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
            key = f"pat:edit:{payload.guild_id}:{uid}:{get_today()}"
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
