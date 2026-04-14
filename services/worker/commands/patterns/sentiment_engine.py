import asyncio
import json
import logging
import httpx
import os
import discord
from discord.ext import commands
from shared.python.redis_client import get_redis_client
from .common import K_SENTIMENT, get_today, is_staff, PAT_TTL

logger = logging.getLogger("SentimentEngine")

class SentimentEngine(commands.Cog):
    def __init__(self, bot, guild_id):
        self.bot = bot
        self._guild_id = guild_id
        # Semaphore to ensure we don't slam the CPU with multiple local LLM calls
        self._llm_semaphore = asyncio.Semaphore(1)
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
        # Use SmollM-135M for fast, local, lightweight analysis
        self.model = "smollm2:135m"

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild or message.guild.id != self._guild_id:
            return
            
        if is_staff(message.author):
            return

        text = message.content or ""
        # Only analyze messages with some substance
        if len(text) < 10 or len(text) > 2000:
            return

        # Trigger analysis in background so we don't block other listeners
        asyncio.create_task(self.analyze_sentiment(message))

    async def analyze_sentiment(self, message: discord.Message):
        async with self._llm_semaphore:
            try:
                logger.info(f"Analyzing sentiment for user {message.author.id}...")
                sentiment = await self._call_ollama(message.content)
                if sentiment:
                    logger.info(f"Sentiment detected: {sentiment} for user {message.author.id}")
                    await self._save_sentiment(message.guild.id, message.author.id, sentiment)
                    if sentiment == "URGENT":
                        await self._handle_crisis(message)
            except Exception as e:
                logger.error(f"Sentiment analysis failed for message {message.id}: {e}")

    async def _call_ollama(self, text: str) -> str:
        prompt = (
            "Analyze the sentiment of this message from a user in a recovery community. "
            "Respond with EXACTLY one of these words: POSITIVE, NEUTRAL, NEGATIVE, or URGENT.\n\n"
            f"Message: {text[:500]}"
        )
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    f"{self.ollama_host}/api/generate",
                    json={
                        "model": self.model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": 0.1,
                            "num_predict": 5
                        }
                    }
                )
                response.raise_for_status()
                result = response.json().get("response", "").strip().upper()
                
                # Clean up response in case it returned more text
                for word in ["POSITIVE", "NEUTRAL", "NEGATIVE", "URGENT"]:
                    if word in result:
                        return word
                return "NEUTRAL"
        except Exception as e:
            logger.debug(f"Ollama sentiment call failed: {e}")
            return None

    async def _save_sentiment(self, gid: int, uid: int, sentiment: str):
        r = await get_redis_client()
        try:
            today = get_today()
            key = K_SENTIMENT(gid, uid, today)
            await r.hincrby(key, sentiment, 1)
            await r.expire(key, PAT_TTL)
        finally:
            await r.aclose()

    async def _handle_crisis(self, message: discord.Message):
        """Logs a potential crisis detected by local AI."""
        logger.warning(f"Potential CRISIS detected for user {message.author.id} in {message.channel.name}")
        # Optional: Add to a specialized Redis queue for moderator attention
        r = await get_redis_client()
        try:
            await r.lpush(f"pat:crisis_queue:{message.guild.id}", json.dumps({
                "uid": message.author.id,
                "msg_id": message.id,
                "ts": int(message.created_at.timestamp()),
                "content_preview": message.content[:200]
            }))
        finally:
            await r.aclose()

async def setup(bot):
    # This setup is usually called from PatternDetectorCog directly if we want to integrate it
    pass
