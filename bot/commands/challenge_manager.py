"""
Unified Challenge Manager
- emoji-role configuration and reaction handling
- quest tracking (text and emoji patterns)
- evaluation (converted from vyzva)

One slash group: /challenge
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, List, Dict, Optional, Tuple

import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timedelta, date
import os
import redis.asyncio as redis

DATA_PATH = Path("data")
CONFIG_PATH = DATA_PATH / "challenge_config.json"
DATA_PATH.mkdir(parents=True, exist_ok=True)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")


@dataclass
class ChallengeConfig:
    guild_id: int
    role_id: Optional[int] = None
    channel_id: Optional[int] = None
    emojis: List[str] = field(default_factory=list)
    react_ok: bool = True
    reply_on_success: bool = True
    success_messages: List[str] = field(default_factory=lambda: ["Hotovo! ✅"]) 
    allow_extra_chars: bool = True
    require_all: bool = True
    quest_pattern: str = "Quest —"
    enabled: bool = True

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict[str, Any]) -> "ChallengeConfig":
        return ChallengeConfig(
            guild_id=int(d.get("guild_id", 0)),
            role_id=d.get("role_id"),
            channel_id=d.get("channel_id"),
            emojis=list(d.get("emojis") or []),
            react_ok=bool(d.get("react_ok", True)),
            reply_on_success=bool(d.get("reply_on_success", True)),
            success_messages=list(d.get("success_messages") or ["Hotovo! ✅"]),
            allow_extra_chars=bool(d.get("allow_extra_chars", True)),
            require_all=bool(d.get("require_all", True)),
            quest_pattern=d.get("quest_pattern", "Quest —"),
            enabled=bool(d.get("enabled", True)),
        )


def _split_emoji_list(raw: str) -> list[str]:
    raw = raw.strip().strip("\"' ")
    raw = raw.replace(",", " ")
    parts = [p for p in raw.split() if p]
    return parts


class ChallengeManager(commands.Cog):
    """Unified manager for emoji-role, quests and evaluation."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.configs: Dict[int, ChallengeConfig] = {}
        self._load_configs()

        # redis for streaks
        self.pool = redis.ConnectionPool.from_url(REDIS_URL, decode_responses=True)
        self.r = redis.Redis(connection_pool=self.pool)
        self.check_streaks.start()

    def _load_configs(self):
        if not CONFIG_PATH.exists():
            return
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            for k, v in raw.items():
                self.configs[int(k)] = ChallengeConfig.from_json(v)
            print(f"📦 Challenge config loaded ({len(self.configs)} guilds).")
        except Exception as e:
            print(f"❌ Error loading config: {e}")

    def _save_configs(self):
        data = {str(gid): cfg.to_json() for gid, cfg in self.configs.items()}
        CONFIG_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def get_config(self, guild_id: int) -> Optional[ChallengeConfig]:
        return self.configs.get(guild_id)

    def set_config(self, guild_id: int, cfg: ChallengeConfig):
        self.configs[guild_id] = cfg
        self._save_configs()

    def delete_config(self, guild_id: int):
        if guild_id in self.configs:
            del self.configs[guild_id]
            self._save_configs()
            return True
        return False

    # --------------------- helpers for streaks ---------------------
    async def get_user_streak(self, guild_id: int, challenge_id: str, user_id: int) -> Dict:
        key = f"challenge:{guild_id}:{challenge_id}:streak:{user_id}"
        j = await self.r.get(key)
        if not j:
            return {"days": 0, "last_update": None, "completed_dates": []}
        return json.loads(j)

    async def update_user_streak(self, guild_id: int, challenge_id: str, user_id: int, data: Dict):
        key = f"challenge:{guild_id}:{challenge_id}:streak:{user_id}"
        await self.r.set(key, json.dumps(data))

    # --------------------- slash group ---------------------
    challenge = app_commands.Group(name="challenge", description="Unified challenge commands")

    @challenge.command(name="setup", description="Nastav výzvu v aktuálním kanálu")
    @app_commands.describe(name="Jméno výzvy (bez mezer)")
    @commands.has_permissions(administrator=True)
    async def setup(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        channel_id = interaction.channel.id
        cid = name.lower().replace(" ", "_")
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.channel_id = channel_id
        cfg.quest_pattern = cfg.quest_pattern or "Quest —"
        cfg.enabled = True
        cfg.role_id = cfg.role_id
        # store under guild key (we keep single config per guild for simplicity)
        self.set_config(guild_id, cfg)
        await interaction.followup.send(f"✅ Výzva **{name}** nastavena na <#{channel_id}>", ephemeral=True)

    @challenge.command(name="role", description="Nastav role pro milník (jedna role pro celý challenge)")
    @app_commands.describe(role="Role k přidání při milníku")
    @commands.has_permissions(administrator=True)
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.role_id = role.id
        self.set_config(guild_id, cfg)
        await interaction.followup.send(f"✅ Role pro vyzvu nastavena: {role.mention}", ephemeral=True)

    @challenge.command(name="pattern", description="Nastav pattern pro text nebo emoji (.emoji)")
    @app_commands.describe(pattern="Text pattern (contains 'Quest') nebo .emoji")
    @commands.has_permissions(administrator=True)
    async def set_pattern(self, interaction: discord.Interaction, pattern: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.quest_pattern = pattern
        self.set_config(guild_id, cfg)
        await interaction.followup.send(f"✅ Pattern nastaven na `{pattern}`", ephemeral=True)

    @challenge.command(name="info", description="Zobraz info o výzvě v kanálu")
    @commands.has_permissions(administrator=True)
    async def info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id)
        if not cfg or not cfg.channel_id:
            await interaction.followup.send("❌ Žádná výzva nenastavena.", ephemeral=True)
            return
        embed = discord.Embed(title="Výzva", color=discord.Color.blue())
        embed.add_field("Kanál", f"<#{cfg.channel_id}>")
        embed.add_field("Pattern", f"`{cfg.quest_pattern}`")
        embed.add_field("Role ID", str(cfg.role_id) if cfg.role_id else "_není_")
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --------------------- listeners ---------------------
    def _is_emoji_pattern(self, pattern: str) -> bool:
        return pattern and (pattern.startswith(".") or pattern.startswith(":"))

    def _matches_text_pattern(self, content: str, pattern: str) -> bool:
        return ("✅" in content) and (pattern.lower() in content.lower())

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        cfg = self.get_config(message.guild.id)
        if not cfg or not cfg.enabled or cfg.channel_id != message.channel.id:
            return
        pattern = cfg.quest_pattern or "Quest —"
        if self._is_emoji_pattern(pattern):
            return
        if self._matches_text_pattern(message.content, pattern):
            # treat as quest submit
            await self._handle_quest_submission(message.guild, message.author, cfg)

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        if user.bot or not reaction.message.guild:
            return
        cfg = self.get_config(reaction.message.guild.id)
        if not cfg or not cfg.enabled or cfg.channel_id != reaction.message.channel.id:
            return
        pattern = cfg.quest_pattern or ""
        if not self._is_emoji_pattern(pattern):
            return
        expected = pattern.lstrip(".: ")
        if str(reaction.emoji) != expected:
            return
        # reaction equals pattern -> count quest
        await self._handle_quest_submission(reaction.message.guild, user, cfg)

    async def _handle_quest_submission(self, guild: discord.Guild, user: discord.User, cfg: ChallengeConfig):
        guild_id = guild.id
        challenge_id = f"default"
        user_id = user.id
        today = date.today().isoformat()
        streak = await self.get_user_streak(guild_id, challenge_id, user_id)
        completed = streak.get("completed_dates", [])
        last = streak.get("last_update")
        days = streak.get("days", 0)
        if today in completed:
            return
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        if last == yesterday or last is None:
            days += 1
        else:
            days = 1
            completed = []
        completed.append(today)
        new = {"days": days, "last_update": today, "completed_dates": completed}
        await self.update_user_streak(guild_id, challenge_id, user_id, new)
        member = guild.get_member(user_id)
        # add role when threshold reached (simple single-role behavior)
        if member and cfg.role_id:
            try:
                role = guild.get_role(cfg.role_id)
                if role and role not in member.roles:
                    # add role when days == 5 as example, or any threshold; keep simple: add on 5
                    if days in (5, 12, 20, 29):
                        await member.add_roles(role)
                        try:
                            await member.send(f"Gratuluji! Dosáhl/a jsi {days} dní ve výzvě.")
                        except:
                            pass
            except Exception as e:
                print(f"Role assign error: {e}")

    # --------------------- daily maintenance ---------------------
    @tasks.loop(hours=24)
    async def check_streaks(self):
        await self.bot.wait_until_ready()
        try:
            keys = await self.r.keys("challenge:*:streak:*")
            today = date.today().isoformat()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            for k in keys:
                j = await self.r.get(k)
                if not j:
                    continue
                s = json.loads(j)
                last = s.get("last_update")
                if last not in (today, yesterday):
                    s["days"] = 0
                    await self.r.set(k, json.dumps(s))
        except Exception as e:
            print(f"check_streaks error: {e}")

    @check_streaks.before_loop
    async def before_check(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(ChallengeManager(bot))
