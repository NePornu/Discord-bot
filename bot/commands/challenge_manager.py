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
import random
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
    success_messages: List[str] = field(default_factory=lambda: [
        "Vítej ve výzvě! ✅",
        "Hotovo — jsi zapsán/a. 💪",
        "Přihláška potvrzena. 🎉",
        "Paráda, vítáme tě! 🙌",
        "Gratuluji, máš to! 🔥",
        "Úspěšně přihlášen/a! 🎊",
        "Perfektní kombinace! ⭐",
        "Skvělá práce! 🏆",
        "Jsi in! 😎",
        "Welcome aboard! 🚀",
        "Máš to za sebou! ✨",
        "Povedlo se! 🎯",
        "Hurá, jsi tady! 🎈",
        "Přidán/a do party! 🎪",
        "Respect! 👊",
        "Top! 💎",
        "Nice! 🌟",
        "Legendární tah! 🦾",
        "Mission complete! ✔️",
        "Bingo! 🎲",
        "You're in! 🔓",
        "Unlocked! 🗝️",
    ])
    allow_extra_chars: bool = True
    require_all: bool = True
    quest_pattern: str = "Quest —"
    enabled: bool = True
    milestones: Dict[int, int] = field(default_factory=dict)  # {days: role_id}
    send_dm: bool = False  # Vypnuto defaultně

    def to_json(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_json(d: dict[str, Any]) -> "ChallengeConfig":
        milestones_raw = d.get("milestones", {})
        # Convert string keys to int
        milestones = {int(k): int(v) for k, v in milestones_raw.items()} if milestones_raw else {}
        
        return ChallengeConfig(
            guild_id=int(d.get("guild_id", 0)),
            role_id=d.get("role_id"),
            channel_id=d.get("channel_id"),
            emojis=list(d.get("emojis") or []),
            react_ok=bool(d.get("react_ok", True)),
            reply_on_success=bool(d.get("reply_on_success", True)),
            success_messages=list(d.get("success_messages") or []) or [
                "Vítej ve výzvě! ✅",
                "Hotovo — jsi zapsán/a. 💪",
                "Přihláška potvrzena. 🎉",
            ],
            allow_extra_chars=bool(d.get("allow_extra_chars", True)),
            require_all=bool(d.get("require_all", True)),
            quest_pattern=d.get("quest_pattern", "Quest —"),
            enabled=bool(d.get("enabled", True)),
            milestones=milestones,
            send_dm=bool(d.get("send_dm", False)),
        )


def _split_emoji_list(raw: str) -> list[str]:
    """
    Přijme: '🍁 :strongdoge: 🔥' nebo '🍁, :strongdoge:, 🔥' (uvozovky nevadí).
    """
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

    @challenge.command(name="setup", description="Nastav výzvu (role, kanál, emoji)")
    @app_commands.describe(
        role="Role, která se má udělit",
        channel="Kanál (mention nebo název)",
        emojis="Seznam emoji (např. '🍁 :strongdoge: 🔥')"
    )
    @commands.has_permissions(administrator=True)
    async def setup(
        self, 
        interaction: discord.Interaction, 
        role: discord.Role,
        channel: discord.TextChannel,
        emojis: str
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        em_list = _split_emoji_list(emojis)
        if not em_list:
            await interaction.followup.send("❌ Zadej alespoň jedno emoji.", ephemeral=True)
            return
        
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.role_id = role.id
        cfg.channel_id = channel.id
        cfg.emojis = em_list
        cfg.quest_pattern = cfg.quest_pattern or "Quest —"
        cfg.enabled = True
        
        self.set_config(guild_id, cfg)
        
        await interaction.followup.send(
            f"✅ Výzva nastavena!\n• Role: {role.mention}\n• Kanál: {channel.mention}\n• Emojis: {' '.join(em_list)}",
            ephemeral=True
        )

    @challenge.command(name="role", description="Nastav role pro výzvu")
    @app_commands.describe(role="Role k přidání při splnění")
    @commands.has_permissions(administrator=True)
    async def set_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.role_id = role.id
        self.set_config(guild_id, cfg)
        await interaction.followup.send(f"✅ Role pro výzvu nastavena: {role.mention}", ephemeral=True)

    @challenge.command(name="pattern", description="Nastav pattern pro text nebo emoji (.emoji)")
    @app_commands.describe(pattern="Text pattern (obsahuje 'Quest') nebo .emoji")
    @commands.has_permissions(administrator=True)
    async def set_pattern(self, interaction: discord.Interaction, pattern: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.quest_pattern = pattern
        self.set_config(guild_id, cfg)
        await interaction.followup.send(f"✅ Pattern nastaven na `{pattern}`", ephemeral=True)

    @challenge.command(name="emojis", description="Nastav seznam emoji pro výzvu")
    @app_commands.describe(emojis="Seznam emoji (např. '🍁 :strongdoge: 🔥')")
    @commands.has_permissions(administrator=True)
    async def set_emojis(self, interaction: discord.Interaction, emojis: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        
        em_list = _split_emoji_list(emojis)
        if not em_list:
            await interaction.followup.send("❌ Zadej alespoň jedno emoji.", ephemeral=True)
            return
            
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        cfg.emojis = em_list
        self.set_config(guild_id, cfg)
        
        await interaction.followup.send(f"✅ Emojis nastaveny: {' '.join(em_list)}", ephemeral=True)

    @challenge.command(name="milestone", description="Přidej nebo odeber milník (streak → role)")
    @app_commands.describe(
        action="add|remove|list",
        days="Počet dní pro milník",
        role="Role k přidělení"
    )
    @commands.has_permissions(administrator=True)
    async def milestone(
        self, 
        interaction: discord.Interaction, 
        action: str,
        days: Optional[int] = None,
        role: Optional[discord.Role] = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        
        action = action.lower()
        
        if action == "list":
            if not cfg.milestones:
                await interaction.followup.send("📋 Žádné milníky nejsou nastaveny.", ephemeral=True)
                return
            
            lines = ["📋 **Milníky:**"]
            for day_count in sorted(cfg.milestones.keys()):
                role_id = cfg.milestones[day_count]
                role_obj = interaction.guild.get_role(role_id)
                role_name = role_obj.mention if role_obj else f"<neznámá role {role_id}>"
                lines.append(f"• **{day_count} dní** → {role_name}")
            
            await interaction.followup.send("\n".join(lines), ephemeral=True)
            return
        
        if action == "add":
            if days is None or role is None:
                await interaction.followup.send("❌ Pro přidání zadej: days a role", ephemeral=True)
                return
            
            if days < 1:
                await interaction.followup.send("❌ Počet dní musí být alespoň 1.", ephemeral=True)
                return
            
            cfg.milestones[days] = role.id
            self.set_config(guild_id, cfg)
            
            await interaction.followup.send(
                f"✅ Milník přidán: **{days} dní** → {role.mention}", 
                ephemeral=True
            )
            return
        
        if action == "remove":
            if days is None:
                await interaction.followup.send("❌ Pro odebrání zadej: days", ephemeral=True)
                return
            
            if days in cfg.milestones:
                del cfg.milestones[days]
                self.set_config(guild_id, cfg)
                await interaction.followup.send(f"✅ Milník pro {days} dní odstraněn.", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Milník pro {days} dní neexistuje.", ephemeral=True)
            return
        
        await interaction.followup.send("❌ Neznámá akce. Použij: add|remove|list", ephemeral=True)

    @challenge.command(name="info", description="Zobraz info o výzvě v kanálu")
    @commands.has_permissions(administrator=True)
    async def info(self, interaction: discord.Interaction):
        await self._send_info(interaction)

    @challenge.command(name="show", description="(alias) Zobraz info o výzvě")
    @commands.has_permissions(administrator=True)
    async def show(self, interaction: discord.Interaction):
        await self._send_info(interaction)

    async def _send_info(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id)
        if not cfg or not cfg.channel_id:
            await interaction.followup.send("❌ Žádná výzva nenastavena.", ephemeral=True)
            return
            
        embed = discord.Embed(title="📋 Výzva - konfigurace", color=discord.Color.blue())
        
        role = interaction.guild.get_role(cfg.role_id) if cfg.role_id else None
        channel = interaction.guild.get_channel(cfg.channel_id) if cfg.channel_id else None
        
        embed.add_field(name="Kanál", value=channel.mention if channel else "_není_", inline=False)
        embed.add_field(name="Role (legacy)", value=role.mention if role else "_není_", inline=False)
        embed.add_field(name="Pattern", value=f"`{cfg.quest_pattern}`", inline=False)
        embed.add_field(name="Emojis", value=" ".join(cfg.emojis) if cfg.emojis else "_není_", inline=False)
        
        # Milestones
        if cfg.milestones:
            milestone_lines = []
            for day_count in sorted(cfg.milestones.keys()):
                role_id = cfg.milestones[day_count]
                role_obj = interaction.guild.get_role(role_id)
                role_name = role_obj.mention if role_obj else f"<role {role_id}>"
                milestone_lines.append(f"{day_count}d → {role_name}")
            embed.add_field(
                name="🏆 Milníky (streaky)", 
                value="\n".join(milestone_lines), 
                inline=False
            )
        
        embed.add_field(name="Require all", value="✅" if cfg.require_all else "❌", inline=True)
        embed.add_field(name="React OK", value="✅" if cfg.react_ok else "❌", inline=True)
        embed.add_field(name="Reply on success", value="✅" if cfg.reply_on_success else "❌", inline=True)
        embed.add_field(name="Send DM", value="✅" if cfg.send_dm else "❌", inline=True)
        embed.add_field(name="Enabled", value="✅" if cfg.enabled else "❌", inline=True)
        
        await interaction.followup.send(embed=embed, ephemeral=True)

    # --------------------- emoji-role logic (improved from emoji_role.py) ---------------------
    def _normalize_emoji_list(self, raw: List[str]) -> List[str]:
        return [r.strip() for r in raw if r and r.strip()]

    def _match_custom_emoji(self, name_or_token: str, content: str) -> bool:
        """
        Ověří přítomnost custom emoji:
        - 'name_or_token' může být ':name:' nebo '<:name:id>'
        - Matchuje ':name:', '<:name:any_id>', '<:name:specific_id>'
        """
        token = name_or_token.strip()
        
        # CASE A: Config is full object <...:id>
        if token.startswith("<") and token.endswith(">"):
            if token in content:
                return True
            
            # Try matching by name (ignoring ID) or alias
            m = re.match(r"<a?:([^:]+):\d+>", token)
            if m:
                name = m.group(1)
                # 1. Check text alias :name:
                if f":{name}:" in content:
                    return True
                # 2. Check any ID with same name <a:name:...>
                if re.search(rf"<a?:{re.escape(name)}:\d+>", content):
                    return True
            return False

        # CASE B: Config is just :name:
        m = re.fullmatch(r":([a-zA-Z0-9_~\-]+):", token)
        if not m:
            return token in content

        name = m.group(1)
        # 1. Text alias :name:
        if f":{name}:" in content:
            return True
        # 2. Full object <a:name:id>
        pattern = rf"<a?:{re.escape(name)}:\d+>"
        return re.search(pattern, content) is not None

    def _message_contains_all_targets(self, content: str, targets: List[str]) -> bool:
        """Kontroluje, zda zpráva obsahuje všechny cílové emoji (normalizuje Unicode)"""
        # Normalize content: remove VS16 (\ufe0f) for easier unicode matching
        content_norm = content.replace("\ufe0f", "")

        for t in targets:
            t = t.strip()
            if not t:
                continue
            
            # Normalize target too
            t_norm = t.replace("\ufe0f", "")
            
            if not (t.startswith(":") and t.endswith(":")) and not (t.startswith("<") and t.endswith(">")):
                # Standard emoji check -> use normalized
                ok = t_norm in content_norm
            else:
                # Custom emoji check -> use original content
                ok = self._match_custom_emoji(t, content)
                
            if not ok:
                return False
        return True

    def _message_contains_all_emojis(self, message: discord.Message, target: List[str]) -> bool:
        """Kontroluje zprávu + reakce na přítomnost všech emoji"""
        text = message.content or ""
        
        # check content with improved matching
        if self._message_contains_all_targets(text, target):
            return True
        
        # check reactions
        present = [str(r.emoji) for r in message.reactions]
        reaction_content = " ".join(present)
        if self._message_contains_all_targets(reaction_content, target):
            return True
        
        return False

    async def _assign_role_immediate(self, guild: discord.Guild, member: discord.Member, cfg: ChallengeConfig) -> bool:
        """Okamžité přiřazení role po splnění emoji kombinace"""
        if not cfg.role_id or not member:
            return False
        role = guild.get_role(cfg.role_id)
        if not role:
            return False
        if role in member.roles:
            return False
        try:
            await member.add_roles(role, reason="Challenge: kombinace emoji splněna")
            
            # Send success message only if enabled
            if cfg.send_dm and cfg.reply_on_success and cfg.success_messages:
                try:
                    msg = random.choice(cfg.success_messages)
                    await member.send(f"{msg}\n(Role {role.name} přidána)")
                except:
                    pass
            
            return True
        except Exception as e:
            print(f"Immediate role assign error: {e}")
            return False

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
        
        # --- EMOJI-ROLE MODE ---
        if cfg.emojis:
            content = message.content.strip()
            hit = self._message_contains_all_targets(content, cfg.emojis) if cfg.require_all else any(
                self._message_contains_all_targets(content, [e]) for e in cfg.emojis
            )

            if hit:
                if cfg.react_ok:
                    try:
                        await message.add_reaction("✅")
                    except Exception:
                        pass

                member = message.guild.get_member(message.author.id)
                assigned = await self._assign_role_immediate(message.guild, member, cfg)

                if assigned and cfg.reply_on_success and cfg.success_messages:
                    try:
                        txt = random.choice(cfg.success_messages)
                        await message.reply(txt, mention_author=False)
                    except Exception:
                        pass
                return
        
        # --- QUEST MODE (text pattern) ---
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
        
        # Check milestones and assign roles
        if member and cfg.milestones:
            try:
                # Check if user reached any milestone
                if days in cfg.milestones:
                    role_id = cfg.milestones[days]
                    role = guild.get_role(role_id)
                    if role and role not in member.roles:
                        await member.add_roles(role, reason=f"Challenge: dosaženo {days} dní")
                        
                        # Send DM only if enabled
                        if cfg.send_dm:
                            try:
                                await member.send(f"🎉 Gratuluji! Dosáhl/a jsi **{days} dní** ve výzvě a získáváš roli **{role.name}**!")
                            except:
                                pass
            except Exception as e:
                print(f"Role assign error: {e}")
        
        # Legacy support: single role_id with hardcoded milestones (deprecated)
        elif member and cfg.role_id and not cfg.milestones:
            try:
                role = guild.get_role(cfg.role_id)
                if role and role not in member.roles:
                    if days in (5, 12, 20, 29):
                        await member.add_roles(role)
                        if cfg.send_dm:
                            try:
                                await member.send(f"Gratuluji! Dosáhl/a jsi {days} dní ve výzvě.")
                            except:
                                pass
            except Exception as e:
                print(f"Role assign error: {e}")

    # --------------------- admin messages management ---------------------
    @challenge.command(name="messages", description="Správa zpráv pro potvrzení (add|list|clear)")
    @app_commands.describe(action="add|list|clear", text="Text nové potvrzovací zprávy (pro add)")
    @commands.has_permissions(administrator=True)
    async def messages(self, interaction: discord.Interaction, action: str, text: Optional[str] = None):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        action = action.lower()
        if action == "add":
            if not text:
                await interaction.followup.send("❌ Musíš zadat text pro přidání.", ephemeral=True)
                return
            cfg.success_messages.append(text)
            self.set_config(guild_id, cfg)
            await interaction.followup.send("✅ Zpráva přidána.", ephemeral=True)
            return
        if action == "list":
            lines = "\n".join(f"{i+1}. {m}" for i, m in enumerate(cfg.success_messages[:50]))
            await interaction.followup.send(f"Zprávy:\n{lines}", ephemeral=True)
            return
        if action == "clear":
            cfg.success_messages = []
            self.set_config(guild_id, cfg)
            await interaction.followup.send("✅ Seznam potvrzovacích zpráv smazán.", ephemeral=True)
            return
        await interaction.followup.send("❌ Neznámá akce. Použij add|list|clear.", ephemeral=True)

    @challenge.command(name="settings", description="Nastavení chování výzvy")
    @app_commands.describe(
        react_ok="Povolit reakce jako potvrzení?", 
        reply_on_success="Posílat zprávu po úspěchu?", 
        require_all="Požadovat všechny emoji? (jinak stačí některé)",
        send_dm="Posílat DM při získání role?"
    )
    @commands.has_permissions(administrator=True)
    async def settings(
        self, 
        interaction: discord.Interaction, 
        react_ok: Optional[bool] = None, 
        reply_on_success: Optional[bool] = None, 
        require_all: Optional[bool] = None,
        send_dm: Optional[bool] = None
    ):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id) or ChallengeConfig(guild_id=guild_id)
        changed = []
        if react_ok is not None:
            cfg.react_ok = react_ok
            changed.append(f"react_ok={react_ok}")
        if reply_on_success is not None:
            cfg.reply_on_success = reply_on_success
            changed.append(f"reply_on_success={reply_on_success}")
        if require_all is not None:
            cfg.require_all = require_all
            changed.append(f"require_all={require_all}")
        if send_dm is not None:
            cfg.send_dm = send_dm
            changed.append(f"send_dm={send_dm}")
        self.set_config(guild_id, cfg)
        await interaction.followup.send(
            f"✅ Nastavení aktualizováno: {', '.join(changed) if changed else 'žádné změny'}", 
            ephemeral=True
        )

    @challenge.command(name="claim", description="Ruční nárok na výzvu (zadej emoji kombinaci)")
    @app_commands.describe(emojis="Seznam emoji oddělený mezerami (např. '❄️ :panda:')")
    async def claim(self, interaction: discord.Interaction, emojis: str):
        await interaction.response.defer(ephemeral=True)
        if not interaction.guild:
            await interaction.followup.send("❌ Tento příkaz funguje pouze na serveru.", ephemeral=True)
            return
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id)
        if not cfg or not cfg.channel_id:
            await interaction.followup.send("❌ Výzva v tomto kanálu není nakonfigurována.", ephemeral=True)
            return
        
        # Optional: check channel
        if cfg.channel_id and interaction.channel_id != cfg.channel_id:
            ch = interaction.guild.get_channel(cfg.channel_id)
            ch_mention = ch.mention if ch else f"<#{cfg.channel_id}>"
            await interaction.followup.send(
                f"❌ Tento příkaz lze použít pouze v kanálu {ch_mention}.", 
                ephemeral=True
            )
            return
        
        provided = _split_emoji_list(emojis)
        target = self._normalize_emoji_list(cfg.emojis)
        
        content = emojis.strip()
        hit = self._message_contains_all_targets(content, target) if cfg.require_all else any(
            self._message_contains_all_targets(content, [e]) for e in target
        )
        
        if not hit:
            debug_received = f"'{content}'"
            debug_expected = " ".join(target)
            await interaction.followup.send(
                f"❌ **Nesprávná kombinace**\n"
                f"📝 Zadal jsi: {debug_received}\n"
                f"🎯 Očekávám: {debug_expected}\n\n"
                "💡 *Tip: Pro vlastní emoji použij přesný název (např. `:panda:`) nebo je vyber z menu.*", 
                ephemeral=True
            )
            return
        
        member = interaction.guild.get_member(interaction.user.id)
        assigned = await self._assign_role_immediate(interaction.guild, member, cfg)
        if assigned:
            msg = cfg.success_messages[0] if cfg.success_messages else "Hotovo!"
            if cfg.reply_on_success:
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.followup.send("✅ Nárok přijat.", ephemeral=True)
        else:
            await interaction.followup.send("✅ Již máte roli nebo nastala chyba.", ephemeral=True)

    @challenge.command(name="evaluate", description="ADMIN: Vyhodnotí kanál a přiřadí role podle emoji/config")
    @app_commands.describe(limit="Kolik posledních zpráv zkontrolovat")
    @commands.has_permissions(administrator=True)
    async def evaluate(self, interaction: discord.Interaction, limit: Optional[int] = 200):
        await interaction.response.defer(ephemeral=True)
        guild_id = interaction.guild.id
        cfg = self.get_config(guild_id)
        if not cfg or not cfg.channel_id:
            await interaction.followup.send("❌ Výzva nenastavena.", ephemeral=True)
            return
        channel = interaction.guild.get_channel(cfg.channel_id)
        if not channel:
            await interaction.followup.send("❌ Kanál nenalezen.", ephemeral=True)
            return
        checked = 0
        assigned_count = 0
        target = self._normalize_emoji_list(cfg.emojis)
        async for msg in channel.history(limit=limit):
            checked += 1
            # check content or reactions
            if self._message_contains_all_emojis(msg, target) if cfg.require_all else any(
                e in (msg.content or "") or e in [str(r.emoji) for r in msg.reactions] for e in target
            ):
                member = interaction.guild.get_member(msg.author.id)
                if member:
                    if await self._assign_role_immediate(interaction.guild, member, cfg):
                        assigned_count += 1
        await interaction.followup.send(
            f"Hotovo. Zkontrolováno {checked} zpráv, přiřazeno {assigned_count} rolí.", 
            ephemeral=True
        )

    @challenge.command(name="clear", description="Smaže konfiguraci pro tuto guildu")
    @commands.has_permissions(administrator=True)
    async def clear(self, interaction: discord.Interaction):
        if self.delete_config(interaction.guild.id):
            await interaction.response.send_message("🗑️ Konfigurace smazána.", ephemeral=True)
        else:
            await interaction.response.send_message("ℹ️ Nebyla nalezena žádná konfigurace.", ephemeral=True)

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