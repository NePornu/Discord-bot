from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import traceback
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import discord
from discord import app_commands
from discord.ext import commands, tasks




CHANNEL_MChytréN_LOG_ID = 1404416148077809705     
CHANNEL_PROFILE_LOG_ID = 1404734262485450772  




DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)
LOG_CONFIG_FILE = DATA_DIR / "log_config.json"
CACHE_FILE = DATA_DIR / "member_cache.json"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("LogCog")




@dataclass
class LogConfig:
    enabled: bool = True
    log_messages: bool = True
    log_members: bool = True
    log_channels: bool = True
    log_roles: bool = True
    log_voice: bool = True
    log_moderation: bool = True
    log_reactions: bool = True
    log_invites: bool = True
    log_threads: bool = True
    log_webhooks: bool = True
    log_emojis: bool = True
    log_stickers: bool = True
    log_integrations: bool = True
    log_automod: bool = True
    log_applications: bool = True
    log_presence: bool = False  
    ignored_channels: Set[int] = None
    ignored_users: Set[int] = None

    def __post_init__(self):
        self.ignored_channels = self.ignored_channels or set()
        self.ignored_users = self.ignored_users or set()

def load_log_configs() -> Dict[str, LogConfig]:
    out: Dict[str, LogConfig] = {}
    if LOG_CONFIG_FILE.exists():
        try:
            data = json.loads(LOG_CONFIG_FILE.read_text(encoding="utf-8"))
            for gid, cd in data.items():
                cfg = LogConfig(**{k: v for k, v in cd.items() if k not in ("ignored_channels", "ignored_users")})
                cfg.ignored_channels = set(cd.get("ignored_channels", []))
                cfg.ignored_users = set(cd.get("ignored_users", []))
                out[gid] = cfg
        except Exception as e:
            logger.error(f"Chyba načtení log_config.json: {e}")
    return out

async def save_log_configs(configs: Dict[str, LogConfig]) -> None:
    try:
        data: Dict[str, Any] = {}
        for gid, cfg in configs.items():
            data[gid] = {
                "enabled": cfg.enabled,
                "log_messages": cfg.log_messages,
                "log_members": cfg.log_members,
                "log_channels": cfg.log_channels,
                "log_roles": cfg.log_roles,
                "log_voice": cfg.log_voice,
                "log_moderation": cfg.log_moderation,
                "log_reactions": cfg.log_reactions,
                "log_invites": cfg.log_invites,
                "log_threads": cfg.log_threads,
                "log_webhooks": cfg.log_webhooks,
                "log_emojis": cfg.log_emojis,
                "log_stickers": cfg.log_stickers,
                "log_integrations": cfg.log_integrations,
                "log_automod": cfg.log_automod,
                "log_applications": cfg.log_applications,
                "log_presence": cfg.log_presence,
                "ignored_channels": list(cfg.ignored_channels),
                "ignored_users": list(cfg.ignored_users),
            }
        await asyncio.get_event_loop().run_in_executor(None, lambda: LOG_CONFIG_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"))
    except Exception as e:
        logger.error(f"Chyba ukládání log_config.json: {e}")

class MemberCache:
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cache: Dict[int, Dict[str, Any]] = {}
        self.bot.loop.create_task(self.load())

    async def load(self):
        if CACHE_FILE.exists():
            try:
                text = await asyncio.get_event_loop().run_in_executor(None, lambda: CACHE_FILE.read_text(encoding="utf-8"))
                self.cache = {int(k): v for k, v in json.loads(text).items()}
            except Exception as e:
                logger.error(f"Chyba načtení cache: {e}")

    async def save(self):
        try:
            await asyncio.get_event_loop().run_in_executor(None, lambda: CACHE_FILE.write_text(json.dumps({str(k): v for k, v in self.cache.items()}, ensure_ascii=False, indent=2), encoding="utf-8"))
        except Exception as e:
            logger.error(f"Chyba ukládání cache: {e}")

    def update_member(self, m: discord.Member):
        self.cache[m.id] = {
            "username": str(m),
            "display_name": m.display_name,
            "nick": m.nick,
            "global_name": getattr(m, "global_name", None),
            "roles": [r.id for r in m.roles],
            "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            "avatar_url": str(m.display_avatar.url),
            "status": str(m.status) if hasattr(m, "status") else None,
            "activity": str(m.activity) if hasattr(m, "activity") and m.activity else None,
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

    def get_cached(self, user_id: int) -> Optional[Dict[str, Any]]:
        return self.cache.get(user_id)




def ts(dt: Optional[datetime] = None, style: str = "f") -> str:
    dt = dt or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return f"<t:{int(dt.timestamp())}:{style}>"

def human_delta(delta: timedelta) -> str:
    secs = int(delta.total_seconds())
    if secs < 0:
        secs = 0
    m, s = divmod(secs, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d: parts.append(f"{d} d")
    if h: parts.append(f"{h} h")
    if m: parts.append(f"{m} min")
    if s and not parts: parts.append(f"{s} s")
    return " ".join(parts) if parts else "0 s"

def clamp(s: Optional[str], limit: int, ell: str = "...") -> str:
    s = s or ""
    return s if len(s) <= limit else s[: max(0, limit - len(ell))] + ell

def role_diff(a: List[discord.Role], b: List[discord.Role]) -> Tuple[List[discord.Role], List[discord.Role]]:
    sa, sb = set(a), set(b)
    return [r for r in b if r not in sa], [r for r in a if r not in sb]

def diff_overwrites(before: discord.PermissionOverwrite, after: discord.PermissionOverwrite) -> Dict[str, List[str]]:
    changed = {"allowed": [], "denied": [], "unset": []}
    for name, perm in discord.Permissions.all_channel():
        b = getattr(before, name, None)
        a = getattr(after, name, None)
        if b == a:
            continue
        if a is True:
            changed["allowed"].append(name)
        elif a is False:
            changed["denied"].append(name)
        else:
            changed["unset"].append(name)
    return {k: v for k, v in changed.items() if v}

def fmt_target(t: Union[discord.Member, discord.Role, discord.User]) -> str:
    if isinstance(t, discord.Role):
        return f"{t.mention} (role, ID: {t.id})"
    if isinstance(t, (discord.Member, discord.User)):
        return f"{t.mention} (uživ., ID: {t.id})"
    return str(t)

def format_permissions(perms: discord.Permissions) -> str:
    """Formátuje oprávnění do čitelného formátu"""
    enabled = [name.replace('_', ' ').title() for name, value in perms if value]
    if not enabled:
        return "Žádná oprávnění"
    return ", ".join(enabled[:10]) + (f" (+{len(enabled)-10} dalších)" if len(enabled) > 10 else "")




class LogQueue:
    def __init__(self, max_size: int = 500):
        self.q: List[Tuple[int, discord.Embed, Optional[List[discord.File]]]] = []
        self.max = max_size
        self.processing = False

    def add(self, channel_id: int, embed: discord.Embed, files: Optional[List[discord.File]] = None):
        if len(self.q) >= self.max:
            self.q.pop(0)
        self.q.append((channel_id, embed, files))

    async def process(self, bot: commands.Bot):
        if self.processing or not self.q:
            return
        self.processing = True
        try:
            batch_size = 15  
            processed = 0
            while self.q and processed < batch_size:
                ch_id, emb, files = self.q.pop(0)
                ch = bot.get_channel(ch_id)
                if ch and isinstance(ch, (discord.TextChannel, discord.Thread)):
                    try:
                        await ch.send(embed=emb, files=files or [])
                    except discord.HTTPException as e:
                        if e.status == 429:  
                            
                            self.q.insert(0, (ch_id, emb, files))
                            await asyncio.sleep(5)
                            break
                        else:
                            logger.error(f"HTTP error sending to {ch_id}: {e}")
                    except Exception as e:
                        logger.error(f"Send fail to {ch_id}: {e}")
                processed += 1
                await asyncio.sleep(0.1)
        finally:
            self.processing = False




class LogCog(commands.Cog):
    """Kompletní logging se směrováním do 2 kanálů."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.cfgs = load_log_configs()
        self.cache = MemberCache(bot) 
        self.queue = LogQueue()
        self.stats = defaultdict(int)
        self.started_at = datetime.now(timezone.utc)
        self._synced_once = False

        
        self.message_cd: Dict[int, datetime] = {}
        self.bulk_cd: Dict[int, datetime] = {}
        self.reaction_cd: Dict[int, datetime] = {}

        
        self._queue_worker.start()
        self._cache_saver.start()
        self._housekeeping.start()

    async def ensure_channels_exist(self):
        """Zajistí, že log kanály existují"""
        main_channel = self.bot.get_channel(CHANNEL_MChytréN_LOG_ID)
        profile_channel = self.bot.get_channel(CHANNEL_PROFILE_LOG_ID)
        
        if not main_channel:
            logger.warning(f"Hlavní log kanál {CHANNEL_MChytréN_LOG_ID} neexistuje!")
        
        if not profile_channel:
            logger.warning(f"Profilový log kanál {CHANNEL_PROFILE_LOG_ID} neexistuje!")
            
        return main_channel, profile_channel

    
    def cfg(self, gid: int) -> LogConfig:
        return self.cfgs.get(str(gid), LogConfig())

    async def set_cfg(self, gid: int, cfg: LogConfig):
        self.cfgs[str(gid)] = cfg
        await save_log_configs(self.cfgs)

    def _embed(self, title: str, desc: str = "", color: int = 0x5865F2) -> discord.Embed:
        e = discord.Embed(title=clamp(title, 256), description=clamp(desc, 4000), color=color, timestamp=datetime.now(timezone.utc))
        try:
            if self.bot.user and self.bot.user.display_avatar:
                e.set_footer(text="🔍 Server Logs", icon_url=self.bot.user.display_avatar.url)
            else:
                e.set_footer(text="🔍 Server Logs")
        except Exception:
            e.set_footer(text="🔍 Server Logs")
        return e

    def _prefix_text(self) -> str:
        pfx = self.bot.command_prefix
        if callable(pfx):
            return "<callable prefix>"
        return str(pfx)

    def to_main(self, embed: discord.Embed, files: Optional[List[discord.File]] = None):
        self.queue.add(CHANNEL_MChytréN_LOG_ID, embed, files)
        self.stats["logs_sent"] += 1

    def to_profile(self, embed: discord.Embed, files: Optional[List[discord.File]] = None):
        self.queue.add(CHANNEL_PROFILE_LOG_ID, embed, files)
        self.stats["logs_sent"] += 1

    
    @tasks.loop(seconds=0.5)  
    async def _queue_worker(self):
        await self.queue.process(self.bot)

    @tasks.loop(minutes=3)  
    async def _cache_saver(self):
        await self.cache.save()

    @tasks.loop(minutes=10)
    async def _housekeeping(self):
        now = datetime.now(timezone.utc)
        self.message_cd = {k: v for k, v in self.message_cd.items() if (now - v) < timedelta(minutes=5)}
        self.bulk_cd = {k: v for k, v in self.bulk_cd.items() if (now - v) < timedelta(minutes=10)}
        self.reaction_cd = {k: v for k, v in self.reaction_cd.items() if (now - v) < timedelta(minutes=2)}

    def cog_unload(self):
        self._queue_worker.cancel()
        self._cache_saver.cancel()
        self._housekeeping.cancel()
        self.bot.loop.create_task(self.cache.save())

    
    log_group = app_commands.Group(name="log", description="Nastavení logování")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild is None:
            await interaction.response.send_message("❌ Příkaz jde použít jen na serveru.", ephemeral=True)
            return False
        return True

    @log_group.command(name="status", description="Zobrazí stav logování")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def log_status(self, itx: discord.Interaction):
        cfg = self.cfg(itx.guild_id)
        e = self._embed("🔍 Stav logování")
        
        main_ch, profile_ch = await self.ensure_channels_exist()
        
        e.add_field(name="Prefix", value=self._prefix_text(), inline=True)
        e.add_field(name="Hlavní log", value=f"<#{CHANNEL_MChytréN_LOG_ID}>" if main_ch else "❌ Neexistuje", inline=True)
        e.add_field(name="Profilový log", value=f"<#{CHANNEL_PROFILE_LOG_ID}>" if profile_ch else "❌ Neexistuje", inline=True)
        
        on = "✅" if cfg.enabled else "❌"
        e.add_field(name="Hlavní přepínač", value=on, inline=True)
        
        bits = {
            "messages": cfg.log_messages, "members": cfg.log_members, "channels": cfg.log_channels,
            "roles": cfg.log_roles, "voice": cfg.log_voice, "moderation": cfg.log_moderation,
            "reactions": cfg.log_reactions, "invites": cfg.log_invites, "threads": cfg.log_threads,
            "webhooks": cfg.log_webhooks, "emojis": cfg.log_emojis, "stickers": cfg.log_stickers,
            "integrations": cfg.log_integrations, "automod": cfg.log_automod, 
            "applications": cfg.log_applications, "presence": cfg.log_presence
        }
        
        enabled = ", ".join(k for k, v in bits.items() if v)
        disabled = ", ".join(k for k, v in bits.items() if not v)
        
        if enabled: e.add_field(name="✅ Zapnuto", value=enabled, inline=False)
        if disabled: e.add_field(name="❌ Vypnuto", value=disabled, inline=False)
        
        
        uptime = human_delta(datetime.now(timezone.utc) - self.started_at)
        e.add_field(name="📊 Statistiky", 
                   value=f"Odesláno logů: {self.stats['logs_sent']}\nUptime: {uptime}\nFronta: {len(self.queue.q)}", 
                   inline=True)
        
        await itx.response.send_message(embed=e, ephemeral=True)

    @log_group.command(name="toggle", description="Zap/vyp konkrétní typ logování")
    @app_commands.describe(log_type="Typ logování (messages/members/channels/etc. nebo 'all')", enabled="Zapnout?")
    @app_commands.choices(log_type=[
        app_commands.Choice(name="Vše", value="all"),
        app_commands.Choice(name="Zprávy", value="messages"),
        app_commands.Choice(name="Členové", value="members"),
        app_commands.Choice(name="Kanály", value="channels"),
        app_commands.Choice(name="Role", value="roles"),
        app_commands.Choice(name="Hlasové", value="voice"),
        app_commands.Choice(name="Moderace", value="moderation"),
        app_commands.Choice(name="Reakce", value="reactions"),
        app_commands.Choice(name="Pozvánky", value="invites"),
        app_commands.Choice(name="Vlákna", value="threads"),
        app_commands.Choice(name="Webhooks", value="webhooks"),
        app_commands.Choice(name="Emoji", value="emojis"),
        app_commands.Choice(name="Stickery", value="stickers"),
        app_commands.Choice(name="Integrace", value="integrations"),
        app_commands.Choice(name="AutoMod", value="automod"),
        app_commands.Choice(name="Aplikace", value="applications"),
        app_commands.Choice(name="Status/Aktivita", value="presence"),
    ])
    @app_commands.checks.has_permissions(manage_guild=True)
    async def toggle_logging(self, itx: discord.Interaction, log_type: str, enabled: bool):
        cfg = self.cfg(itx.guild_id)
        
        if log_type == "all":
            cfg.enabled = enabled
            status = "VŠECHNO"
        else:
            attr = f"log_{log_type}"
            if hasattr(cfg, attr):
                setattr(cfg, attr, enabled)
                status = log_type.upper()
            else:
                await itx.response.send_message(f"❌ Neznámý typ: `{log_type}`", ephemeral=True)
                return
                
        await self.set_cfg(itx.guild_id, cfg)
        emoji = "✅" if enabled else "❌"
        await itx.response.send_message(f"{emoji} `{status}` {'ZAPNUTO' if enabled else 'VYPNUTO'}", ephemeral=True)

    
    @commands.Cog.listener()
    async def on_ready(self):
        if not self._synced_once:
            try:
                synced = await self.bot.tree.sync()
                logger.info(f"Synced {len(synced)} slash commands")
            except Exception as e:
                logger.error(f"Sync slash příkazů selhal: {e}")
            self._synced_once = True
            
        await self.ensure_channels_exist()
        
        
        for g in self.bot.guilds:
            for m in g.members:
                self.cache.update_member(m)
                
        logger.info(f"LogCog ready jako {self.bot.user} na {len(self.bot.guilds)} serverech")

    @commands.Cog.listener()
    async def on_error(self, event: str, *args, **kwargs):
        logger.error(f"Chyba v eventu {event}: {traceback.format_exc()}")

    
    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        cfg = self.cfg(after.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        changes = []
        if before.name != after.name:
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if before.description != after.description:
            changes.append(f"**Popis:** `{clamp(before.description or 'Žádný', 100)}` → `{clamp(after.description or 'Žádný', 100)}`")
        if before.icon != after.icon:
            changes.append("**Ikona:** změněna")
        if before.banner != after.banner:
            changes.append("**Banner:** změněn")
        if before.splash != after.splash:
            changes.append("**Splash:** změněn")
        if before.discovery_splash != after.discovery_splash:
            changes.append("**Discovery splash:** změněn")
        if before.system_channel != after.system_channel:
            b_ch = before.system_channel.mention if before.system_channel else "Žádný"
            a_ch = after.system_channel.mention if after.system_channel else "Žádný"
            changes.append(f"**Systémový kanál:** {b_ch} → {a_ch}")
        if before.afk_channel != after.afk_channel:
            b_ch = before.afk_channel.mention if before.afk_channel else "Žádný"
            a_ch = after.afk_channel.mention if after.afk_channel else "Žádný"
            changes.append(f"**AFK kanál:** {b_ch} → {a_ch}")
        if before.afk_timeout != after.afk_timeout:
            changes.append(f"**AFK timeout:** {before.afk_timeout}s → {after.afk_timeout}s")
        if before.verification_level != after.verification_level:
            changes.append(f"**Verification level:** {before.verification_level} → {after.verification_level}")
        if before.explicit_content_filter != after.explicit_content_filter:
            changes.append(f"**Explicit filter:** {before.explicit_content_filter} → {after.explicit_content_filter}")
        if before.default_notifications != after.default_notifications:
            changes.append(f"**Default notifications:** {before.default_notifications} → {after.default_notifications}")
        if before.owner_id != after.owner_id and after.owner:
            changes.append(f"**Nový vlastník:** {after.owner.mention}")
        if before.premium_tier != after.premium_tier:
            changes.append(f"**Boost tier:** {before.premium_tier} → {after.premium_tier}")
        if before.premium_subscription_count != after.premium_subscription_count:
            changes.append(f"**Boost počet:** {before.premium_subscription_count} → {after.premium_subscription_count}")

        if changes:
            e = self._embed("🏠 Server upraven", "\n".join(changes))
            if after.icon:
                e.set_thumbnail(url=after.icon.url)
            e.add_field(name="Server", value=after.name, inline=True)
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        cfg = self.cfg(channel.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        icons = {
            discord.TextChannel: "📝",
            discord.VoiceChannel: "🔊", 
            discord.CategoryChannel: "📁",
            discord.StageChannel: "🎭",
            discord.ForumChannel: "💬",
            discord.NewsChannel: "📢",
        }
        icon = icons.get(type(channel), "📄")
        
        e = self._embed(f"{icon} Kanál vytvořen", f"{getattr(channel, 'mention', f'`{channel.name}`')}")
        e.add_field(name="Název", value=channel.name, inline=True)
        e.add_field(name="Typ", value=type(channel).__name__, inline=True)
        e.add_field(name="ID", value=str(channel.id), inline=True)
        
        if hasattr(channel, "category") and channel.category:
            e.add_field(name="Kategorie", value=channel.category.name, inline=True)
        if hasattr(channel, "topic") and channel.topic:
            e.add_field(name="Téma", value=clamp(channel.topic, 200), inline=False)
        if hasattr(channel, "nsfw"):
            e.add_field(name="NSFW", value="✅" if channel.nsfw else "❌", inline=True)
        if hasattr(channel, "slowmode_delay") and channel.slowmode_delay:
            e.add_field(name="Slowmode", value=f"{channel.slowmode_delay}s", inline=True)
            
        self.to_main(e)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        cfg = self.cfg(channel.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("🗑️ Kanál smazán", f"`{channel.name}`", color=0xED4245)
        e.add_field(name="Typ", value=type(channel).__name__, inline=True)
        e.add_field(name="ID", value=str(channel.id), inline=True)
        if hasattr(channel, "category") and channel.category:
            e.add_field(name="Kategorie", value=channel.category.name, inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return

        changes = []
        if before.name != after.name:
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if hasattr(before, "topic") and hasattr(after, "topic") and before.topic != after.topic:
            changes.append(f"**Téma:** `{clamp(before.topic or 'Žádné', 50)}` → `{clamp(after.topic or 'Žádné', 50)}`")
        if hasattr(before, "category") and before.category != after.category:
            b_cat = before.category.name if before.category else "Žádná"
            a_cat = after.category.name if after.category else "Žádná"
            changes.append(f"**Kategorie:** `{b_cat}` → `{a_cat}`")
        if hasattr(before, "position") and before.position != after.position:
            changes.append(f"**Pozice:** `{before.position}` → `{after.position}`")
        if hasattr(before, "bitrate") and hasattr(after, "bitrate") and before.bitrate != after.bitrate:
            changes.append(f"**Bitrate:** `{before.bitrate}` → `{after.bitrate}`")
        if hasattr(before, "user_limit") and hasattr(after, "user_limit") and before.user_limit != after.user_limit:
            changes.append(f"**Limit:** `{before.user_limit or '∞'}` → `{after.user_limit or '∞'}`")
        if hasattr(before, "nsfw") and hasattr(after, "nsfw") and before.nsfw != after.nsfw:
            changes.append(f"**NSFW:** `{before.nsfw}` → `{after.nsfw}`")
        if hasattr(before, "slowmode_delay") and hasattr(after, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
            changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")

        
        if before.overwrites != after.overwrites:
            b_targets = {getattr(t, "id", t) for t in before.overwrites}
            a_targets = {getattr(t, "id", t) for t in after.overwrites}
            created = a_targets - b_targets
            removed = b_targets - a_targets
            kept = a_targets & b_targets

            perm_changes = []
            
            for t in after.overwrites:
                tid = getattr(t, "id", None)
                if tid in created:
                    perm_changes.append(f"• **Overwrites vytvořeny** pro {fmt_target(t)}")
            for t in before.overwrites:
                tid = getattr(t, "id", None)
                if tid in removed:
                    perm_changes.append(f"• **Overwrites odebrány** pro {fmt_target(t)}")

            
            for t in after.overwrites:
                tid = getattr(t, "id", None)
                if tid in kept:
                    before_po = before.overwrites.get(t)
                    after_po = after.overwrites.get(t)
                    if before_po and after_po and (before_po != after_po):
                        chg = diff_overwrites(before_po, after_po)
                        if chg:
                            txt = []
                            if chg.get("allowed"):
                                txt.append("ALLOW: " + ", ".join(sorted(chg["allowed"])[:5]))
                            if chg.get("denied"):
                                txt.append("DENY: " + ", ".join(sorted(chg["denied"])[:5]))
                            if chg.get("unset"):
                                txt.append("UNSET: " + ", ".join(sorted(chg["unset"])[:5]))
                            perm_changes.append(f"• **Overwrites změněny** pro {fmt_target(t)}: " + ", ".join(txt))

            if perm_changes:
                changes.append("**Oprávnění:**\n" + "\n".join(perm_changes[:5]))

        if changes:
            e = self._embed("⚙️ Kanál upraven", f"{getattr(after, 'mention', f'`{after.name}`')}\n\n" + "\n".join(changes))
            e.add_field(name="ID kanálu", value=str(after.id), inline=True)
            e.add_field(name="Typ", value=type(after).__name__, inline=True)
            self.to_main(e)

    
    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread):
        cfg = self.cfg(thread.guild.id)
        if not (cfg.enabled and cfg.log_threads):
            return
            
        e = self._embed("🧵 Vlákno vytvořeno", f"{thread.mention}")
        e.add_field(name="Název", value=thread.name, inline=True)
        e.add_field(name="ID", value=str(thread.id), inline=True)
        if thread.parent:
            e.add_field(name="Rodičovský kanál", value=thread.parent.mention, inline=True)
        if thread.owner:
            e.add_field(name="Autor", value=thread.owner.mention, inline=True)
        if hasattr(thread, "slowmode_delay") and thread.slowmode_delay:
            e.add_field(name="Slowmode", value=f"{thread.slowmode_delay}s", inline=True)
        e.add_field(name="Archivace", value=f"{thread.auto_archive_duration} min", inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread: discord.Thread):
        cfg = self.cfg(thread.guild.id)
        if not (cfg.enabled and cfg.log_threads):
            return
            
        e = self._embed("🗑️ Vlákno smazáno", f"`{thread.name}`", color=0xED4245)
        e.add_field(name="ID", value=str(thread.id), inline=True)
        if thread.parent:
            e.add_field(name="Rodič", value=thread.parent.mention, inline=True)
        if thread.owner:
            e.add_field(name="Vlastník", value=thread.owner.mention, inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_thread_update(self, before: discord.Thread, after: discord.Thread):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_threads):
            return
            
        changes = []
        if before.name != after.name:
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if before.archived != after.archived:
            changes.append(f"**Archiv:** {'archivováno' if after.archived else 'obnoveno'}")
        if before.locked != after.locked:
            changes.append(f"**Zámek:** {'zamknuto' if after.locked else 'odemknuto'}")
        if hasattr(before, "slowmode_delay") and before.slowmode_delay != after.slowmode_delay:
            changes.append(f"**Slowmode:** `{before.slowmode_delay}s` → `{after.slowmode_delay}s`")
        if before.auto_archive_duration != after.auto_archive_duration:
            changes.append(f"**Auto archiv:** `{before.auto_archive_duration} min` → `{after.auto_archive_duration} min`")
            
        if changes:
            e = self._embed("⚙️ Vlákno upraveno", f"{after.mention}\n\n" + "\n".join(changes))
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    @commands.Cog.listener()
    async def on_thread_join(self, thread: discord.Thread):
        cfg = self.cfg(thread.guild.id)
        if not (cfg.enabled and cfg.log_threads):
            return
            
        e = self._embed("🧵 Bot se připojil k vláknu", f"{thread.mention}")
        e.add_field(name="Název", value=thread.name, inline=True)
        if thread.parent:
            e.add_field(name="Rodič", value=thread.parent.mention, inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_thread_remove(self, thread: discord.Thread):
        cfg = self.cfg(thread.guild.id)
        if not (cfg.enabled and cfg.log_threads):
            return
            
        e = self._embed("🧵 Bot odstraněn z vlákna", f"`{thread.name}`", color=0xED4245)
        e.add_field(name="ID", value=str(thread.id), inline=True)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        cfg = self.cfg(role.guild.id)
        if not (cfg.enabled and cfg.log_roles):
            return
            
        e = self._embed("🎭 Role vytvořena", role.mention)
        e.add_field(name="Název", value=role.name, inline=True)
        e.add_field(name="ID", value=str(role.id), inline=True)
        e.add_field(name="Pozice", value=str(role.position), inline=True)
        e.add_field(name="Barva", value=str(role.color), inline=True)
        e.add_field(name="Oddělené zobrazení", value="✅" if role.hoist else "❌", inline=True)
        e.add_field(name="Zmínitelná", value="✅" if role.mentionable else "❌", inline=True)
        if role.permissions.value:
            e.add_field(name="Oprávnění", value=format_permissions(role.permissions), inline=False)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        cfg = self.cfg(role.guild.id)
        if not (cfg.enabled and cfg.log_roles):
            return
            
        e = self._embed("🗑️ Role smazána", f"`{role.name}`", color=0xED4245)
        e.add_field(name="ID", value=str(role.id), inline=True)
        e.add_field(name="Pozice", value=str(role.position), inline=True)
        e.add_field(name="Barva", value=str(role.color), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_roles):
            return
            
        changes = []
        if before.name != after.name:
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append(f"**Barva:** {before.color} → {after.color}")
        if before.position != after.position:
            changes.append(f"**Pozice:** `{before.position}` → `{after.position}`")
        if before.hoist != after.hoist:
            changes.append(f"**Oddělené zobrazení:** {before.hoist} → {after.hoist}")
        if before.mentionable != after.mentionable:
            changes.append(f"**@mention:** {before.mentionable} → {after.mentionable}")
        if before.permissions != after.permissions:
            before_perms = {p for p, v in before.permissions if v}
            after_perms = {p for p, v in after.permissions if v}
            added = after_perms - before_perms
            removed = before_perms - after_perms
            if added:
                changes.append("**Přidána oprávnění:** " + ", ".join(sorted(added)[:10]))
            if removed:
                changes.append("**Odebrána oprávnění:** " + ", ".join(sorted(removed)[:10]))
                
        if changes:
            e = self._embed("⚙️ Role upravena", f"{after.mention}\n\n" + "\n".join(changes))
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before: List[discord.Emoji], after: List[discord.Emoji]):
        cfg = self.cfg(guild.id)
        if not (cfg.enabled and cfg.log_emojis):
            return
            
        b_dict = {e.id: e for e in before}
        a_dict = {e.id: e for e in after}
        
        created = [e for e in after if e.id not in b_dict]
        deleted = [e for e in before if e.id not in a_dict]
        changed = [e for e in after if e.id in b_dict and e.name != b_dict[e.id].name]
        
        if not (created or deleted or changes):
            return
            
        lines = []
        for e in created: 
            lines.append(f"➕ **Vytvořen:** `:{e.name}:` (ID {e.id})")
            if e.user:
                lines.append(f"   • Autor: {e.user.mention}")
        for e in deleted: 
            lines.append(f"➖ **Smazán:** `:{e.name}:` (ID {e.id})")
        for e in changed: 
            lines.append(f"✏️ **Přejmenován:** `:{b_dict[e.id].name}:` → `:{e.name}:` (ID {e.id})")
            
        if lines:
            emb = self._embed("😃 Emoji změny", "\n".join(lines))
            emb.add_field(name="Server", value=guild.name, inline=True)
            emb.add_field(name="Celkem emoji", value=str(len(after)), inline=True)
            self.to_main(emb)

    @commands.Cog.listener()
    async def on_guild_stickers_update(self, guild: discord.Guild, before: List[discord.GuildSticker], after: List[discord.GuildSticker]):
        cfg = self.cfg(guild.id)
        if not (cfg.enabled and cfg.log_stickers):
            return
            
        b_dict = {s.id: s for s in before}
        a_dict = {s.id: s for s in after}
        
        created = [s for s in after if s.id not in b_dict]
        deleted = [s for s in before if s.id not in a_dict]
        changed = [s for s in after if s.id in b_dict and s.name != b_dict[s.id].name]
        
        if not (created or deleted or changed):
            return
            
        lines = []
        for s in created: 
            lines.append(f"➕ **Sticker vytvořen:** `{s.name}` (ID {s.id})")
            if hasattr(s, 'user') and s.user:
                lines.append(f"   • Autor: {s.user.mention}")
        for s in deleted: 
            lines.append(f"➖ **Sticker smazán:** `{s.name}` (ID {s.id})")
        for s in changed: 
            lines.append(f"✏️ **Sticker přejmenován:** `{b_dict[s.id].name}` → `{s.name}` (ID {s.id})")
            
        if lines:
            emb = self._embed("🔖 Sticker změny", "\n".join(lines))
            emb.add_field(name="Server", value=guild.name, inline=True)
            emb.add_field(name="Celkem stickers", value=str(len(after)), inline=True)
            self.to_main(emb)

    
    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        g = getattr(channel, "guild", None)
        if not g:
            return
        cfg = self.cfg(g.id)
        if not (cfg.enabled and cfg.log_webhooks):
            return
            
        e = self._embed("🔗 Webhooky aktualizovány", f"Kanál: {getattr(channel,'mention', f'`{channel.name}`')}")
        e.add_field(name="ID kanálu", value=str(channel.id), inline=True)
        try:
            webhooks = await channel.webhooks()
            e.add_field(name="Počet webhooků", value=str(len(webhooks)), inline=True)
        except:
            pass
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        g = invite.guild
        if not g or not (self.cfg(g.id).enabled and self.cfg(g.id).log_invites):
            return
            
        e = self._embed("📧 Pozvánka vytvořena", color=0x57F287)
        e.add_field(name="Kód", value=f"`{invite.code}`", inline=True)
        e.add_field(name="Kanál", value=invite.channel.mention if invite.channel else "*neznámý*", inline=True)
        e.add_field(name="Autor", value=invite.inviter.mention if invite.inviter else "*neznámý*", inline=True)
        e.add_field(name="Max použití", value=str(invite.max_uses) if invite.max_uses else "∞", inline=True)
        e.add_field(name="Max věk", value=f"{invite.max_age}s" if invite.max_age else "∞", inline=True)
        e.add_field(name="Dočasné členství", value="✅" if invite.temporary else "❌", inline=True)
        if invite.expires_at:
            e.add_field(name="Vyprší", value=ts(invite.expires_at), inline=True)
        e.add_field(name="URL", value=f"https://discord.gg/{invite.code}", inline=False)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        g = invite.guild
        if not g or not (self.cfg(g.id).enabled and self.cfg(g.id).log_invites):
            return
            
        e = self._embed("🗑️ Pozvánka smazána", color=0xED4245)
        e.add_field(name="Kód", value=f"`{invite.code}`", inline=True)
        if invite.channel:
            e.add_field(name="Kanál", value=invite.channel.mention, inline=True)
        if invite.inviter:
            e.add_field(name="Autor", value=invite.inviter.mention, inline=True)
        if hasattr(invite, 'uses') and invite.uses is not None:
            e.add_field(name="Použito", value=f"{invite.uses}×", inline=True)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_stage_instance_create(self, stage: discord.StageInstance):
        cfg = self.cfg(stage.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("🎭 Stage začal", color=0x57F287)
        e.add_field(name="Téma", value=clamp(stage.topic, 512), inline=False)
        e.add_field(name="Kanál", value=stage.channel.mention, inline=True)
        e.add_field(name="ID", value=str(stage.id), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_stage_instance_delete(self, stage: discord.StageInstance):
        cfg = self.cfg(stage.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("🎭 Stage ukončen", f"Téma: `{clamp(stage.topic, 100)}`", color=0xED4245)
        e.add_field(name="Kanál", value=stage.channel.mention, inline=True)
        e.add_field(name="ID", value=str(stage.id), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_stage_instance_update(self, before: discord.StageInstance, after: discord.StageInstance):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        changes = []
        if before.topic != after.topic:
            changes.append(f"**Téma:** `{clamp(before.topic, 50)}` → `{clamp(after.topic, 50)}`")
        if hasattr(before, 'privacy_level') and before.privacy_level != after.privacy_level:
            changes.append(f"**Privacy level:** {before.privacy_level} → {after.privacy_level}")
            
        if changes:
            e = self._embed("⚙️ Stage upraven", f"{after.channel.mention}\n\n" + "\n".join(changes))
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    @commands.Cog.listener()
    async def on_scheduled_event_create(self, event: discord.ScheduledEvent):
        cfg = self.cfg(event.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("📅 Událost naplánována", f"**{event.name}**", color=0x57F287)
        e.add_field(name="Start", value=ts(event.start_time), inline=True)
        if event.end_time: 
            e.add_field(name="Konec", value=ts(event.end_time), inline=True)
        if event.channel:
            e.add_field(name="Kanál", value=event.channel.mention, inline=True)
        elif event.location:
            e.add_field(name="Místo", value=event.location, inline=True)
        if event.description:
            e.add_field(name="Popis", value=clamp(event.description, 200), inline=False)
        e.add_field(name="Typ", value=str(event.entity_type), inline=True)
        e.add_field(name="ID", value=str(event.id), inline=True)
        if event.creator:
            e.add_field(name="Vytvořil", value=event.creator.mention, inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_scheduled_event_delete(self, event: discord.ScheduledEvent):
        cfg = self.cfg(event.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("🗑️ Událost zrušena", f"**{event.name}**", color=0xED4245)
        e.add_field(name="Měla začít", value=ts(event.start_time), inline=True)
        if event.status != discord.EventStatus.scheduled:
            e.add_field(name="Status", value=str(event.status), inline=True)
        e.add_field(name="ID", value=str(event.id), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_scheduled_event_update(self, before: discord.ScheduledEvent, after: discord.ScheduledEvent):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        changes = []
        if before.name != after.name: 
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if before.description != after.description: 
            changes.append(f"**Popis:** změněn")
        if before.start_time != after.start_time: 
            changes.append(f"**Start:** {ts(before.start_time)} → {ts(after.start_time)}")
        if before.end_time != after.end_time:
            b_end = ts(before.end_time) if before.end_time else "Neurčen"
            a_end = ts(after.end_time) if after.end_time else "Neurčen"
            changes.append(f"**Konec:** {b_end} → {a_end}")
        if before.status != after.status:
            changes.append(f"**Status:** {before.status} → {after.status}")
        if before.location != after.location:
            changes.append(f"**Místo:** `{before.location or 'Neurčeno'}` → `{after.location or 'Neurčeno'}`")
            
        if changes:
            e = self._embed("⚙️ Událost upravena", f"**{after.name}**\n\n" + "\n".join(changes))
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    @commands.Cog.listener()
    async def on_scheduled_event_user_add(self, event: discord.ScheduledEvent, user: discord.User):
        cfg = self.cfg(event.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("📅 Registrace na událost", f"{user.mention} se registroval na **{event.name}**", color=0x57F287)
        e.add_field(name="Událost", value=event.name, inline=True)
        e.add_field(name="Start", value=ts(event.start_time), inline=True)
        e.set_author(name=str(user), icon_url=user.display_avatar.url)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_scheduled_event_user_remove(self, event: discord.ScheduledEvent, user: discord.User):
        cfg = self.cfg(event.guild.id)
        if not (cfg.enabled and cfg.log_channels):
            return
            
        e = self._embed("📅 Zrušení registrace", f"{user.mention} zrušil registraci na **{event.name}**", color=0xED4245)
        e.add_field(name="Událost", value=event.name, inline=True)
        e.add_field(name="Start", value=ts(event.start_time), inline=True)
        e.set_author(name=str(user), icon_url=user.display_avatar.url)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        cfg = self.cfg(member.guild.id)
        if not (cfg.enabled and cfg.log_members):
            return
        if member.id in cfg.ignored_users:
            return
            
        self.cache.update_member(member)
        acct_age = datetime.now(timezone.utc) - member.created_at
        age_txt = human_delta(acct_age)
        
        e = self._embed("📥 Člen se připojil", f"{member.mention} (`{member}`)", color=0x57F287)
        e.add_field(name="Účet vytvořen", value=ts(member.created_at), inline=True)
        e.add_field(name="Stáří účtu", value=age_txt, inline=True)
        e.add_field(name="ID", value=str(member.id), inline=True)
        e.add_field(name="Bot", value="✅" if member.bot else "❌", inline=True)
        e.add_field(name="Celkem členů", value=str(member.guild.member_count), inline=True)
        
        
        if member.system:
            e.add_field(name="Systémový účet", value="✅", inline=True)
            
        
        if member.roles[1:]:  
            e.add_field(name="Auto-role", value=" ".join(r.mention for r in member.roles[1:][:5]), inline=False)
            
        e.set_thumbnail(url=member.display_avatar.url)
        
        
        try:
            invites = await member.guild.invites()
            
            e.add_field(name="Pozvánky serveru", value=f"{len(invites)} aktivních", inline=True)
        except discord.Forbidden:
            pass
            
        self.to_main(e)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        cfg = self.cfg(member.guild.id)
        if not (cfg.enabled and cfg.log_members):
            return
        if member.id in cfg.ignored_users:
            return

        
        kicked_by = None
        banned = False
        reason = None
        
        try:
            
            try:
                ban_info = await member.guild.fetch_ban(member)
                banned = True
            except discord.NotFound:
                pass
                
            if not banned:
                
                async for entry in member.guild.audit_logs(action=discord.AuditLogAction.kick, limit=10):
                    if entry.target.id == member.id and (datetime.now(timezone.utc) - entry.created_at) < timedelta(seconds=60):
                        kicked_by = entry.user
                        reason = entry.reason
                        break
        except discord.Forbidden:
            pass

        if banned:
            
            return
        elif kicked_by:
            e = self._embed("🥾 Kick", f"{member.mention} (`{member}`)", color=0xED4245)
            e.add_field(name="Moderátor", value=kicked_by.mention, inline=True)
            if reason: 
                e.add_field(name="Důvod", value=clamp(reason, 512), inline=False)
        else:
            e = self._embed("📤 Člen odešel", f"{member.mention} (`{member}`)", color=0xED4245)

        if member.joined_at:
            stay = datetime.now(timezone.utc) - member.joined_at
            e.add_field(name="Na serveru", value=human_delta(stay), inline=True)
            e.add_field(name="Připojil se", value=ts(member.joined_at), inline=True)

        e.add_field(name="ID", value=str(member.id), inline=True)
        e.add_field(name="Bot", value="✅" if member.bot else "❌", inline=True)
        
        if member.roles[1:]:
            role_list = [r.mention for r in sorted(member.roles[1:], key=lambda x: x.position, reverse=True)[:10]]
            if len(member.roles) > 11:
                role_list.append(f"+{len(member.roles)-11} dalších")
            e.add_field(name="Role", value=", ".join(role_list), inline=False)
            
        e.set_thumbnail(url=member.display_avatar.url)
        e.add_field(name="Zbývá členů", value=str(member.guild.member_count), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_members):
            return
        if after.id in cfg.ignored_users:
            return
            
        self.cache.update_member(after)

        changes = []
        profile_changes = []  
        
        
        if before.nick != after.nick:
            profile_changes.append(f"**Přezdívka:** `{before.nick or 'Žádná'}` → `{after.nick or 'Žádná'}`")
        
        if before.display_name != after.display_name and before.nick == after.nick:
            profile_changes.append(f"**Zobrazované jméno:** `{before.display_name}` → `{after.display_name}`")

        
        added_roles, removed_roles = role_diff(before.roles, after.roles)
        if added_roles:
            changes.append("**Přidané role:** " + " ".join(r.mention for r in added_roles[:10]))
        if removed_roles:
            changes.append("**Odebrané role:** " + " ".join(r.mention for r in removed_roles[:10]))

        
        if hasattr(before, "timed_out_until") and before.timed_out_until != after.timed_out_until:
            if after.timed_out_until:
                changes.append(f"**Timeout do:** {ts(after.timed_out_until)}")
                
                try:
                    async for entry in after.guild.audit_logs(action=discord.AuditLogAction.member_update, limit=5):
                        if entry.target.id == after.id and (datetime.now(timezone.utc) - entry.created_at) < timedelta(seconds=30):
                            if entry.user:
                                changes.append(f"**Moderátor:** {entry.user.mention}")
                            if entry.reason:
                                changes.append(f"**Důvod:** {clamp(entry.reason, 200)}")
                            break
                except discord.Forbidden:
                    pass
            else:
                changes.append("**Timeout zrušen**")

        
        if hasattr(before, 'pending') and hasattr(after, 'pending') and before.pending != after.pending:
            if after.pending:
                changes.append("**Status:** čeká na schválení")
            else:
                changes.append("**Status:** schválen")

        
        if profile_changes:
            e = self._embed("👤 Profilová změna", f"{after.mention}\n\n" + "\n".join(profile_changes))
            e.set_thumbnail(url=after.display_avatar.url)
            e.add_field(name="ID", value=str(after.id), inline=True)
            e.add_field(name="Server", value=after.guild.name, inline=True)
            self.to_profile(e)  
            
        if changes:
            e = self._embed("⚙️ Člen upraven", f"{after.mention}\n\n" + "\n".join(changes))
            e.set_thumbnail(url=after.display_avatar.url)
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)  

    @commands.Cog.listener()
    async def on_user_update(self, before: discord.User, after: discord.User):
        
        profile_changes = []
        
        if before.name != after.name:
            profile_changes.append(f"**Username:** `{before.name}` → `{after.name}`")
        if before.discriminator != after.discriminator:
            profile_changes.append(f"**Discriminator:** `#{before.discriminator}` → `#{after.discriminator}`")
        if before.global_name != after.global_name:
            profile_changes.append(f"**Globální jméno:** `{before.global_name or 'Žádné'}` → `{after.global_name or 'Žádné'}`")
        if before.avatar != after.avatar:
            profile_changes.append("**Avatar:** změněn")
        if hasattr(before, 'banner') and hasattr(after, 'banner') and before.banner != after.banner:
            profile_changes.append("**Banner:** změněn")
        if hasattr(before, 'accent_color') and hasattr(after, 'accent_color') and before.accent_color != after.accent_color:
            profile_changes.append(f"**Accent color:** {before.accent_color} → {after.accent_color}")
            
        if not profile_changes:
            return

        
        for guild in self.bot.guilds:
            member = guild.get_member(after.id)
            if not member:
                continue
            cfg = self.cfg(guild.id)
            if not (cfg.enabled and cfg.log_members):
                continue
            if member.id in cfg.ignored_users:
                continue
                
            e = self._embed("👤 Globální profil upraven", f"{after.mention}\n\n" + "\n".join(profile_changes))
            e.set_thumbnail(url=after.display_avatar.url)
            e.add_field(name="ID", value=str(after.id), inline=True)
            e.add_field(name="Server", value=guild.name, inline=True)
            if after.global_name:
                e.add_field(name="Zobrazuje se jako", value=after.global_name, inline=True)
            self.to_profile(e)  

    
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_presence):  
            return
        if after.id in cfg.ignored_users or after.bot:
            return

        changes = []
        if before.status != after.status:
            status_emojis = {
                discord.Status.online: "🟢",
                discord.Status.idle: "🟡", 
                discord.Status.dnd: "🔴",
                discord.Status.offline: "⚫"
            }
            b_emoji = status_emojis.get(before.status, "❓")
            a_emoji = status_emojis.get(after.status, "❓")
            changes.append(f"**Status:** {b_emoji} {before.status} → {a_emoji} {after.status}")

        
        if before.activity != after.activity and after.activity:
            if isinstance(after.activity, discord.Game):
                changes.append(f"**Hra:** 🎮 {after.activity.name}")
            elif isinstance(after.activity, discord.Streaming):
                changes.append(f"**Stream:** 📺 {after.activity.name}")
            elif isinstance(after.activity, discord.CustomActivity) and after.activity.name:
                changes.append(f"**Vlastní status:** {after.activity.name}")

        if changes and len(changes) == 1 and "Status:" in changes[0]:  
            
            now = datetime.now(timezone.utc)
            last = self.reaction_cd.get(f"presence_{after.id}")
            if last and (now - last) < timedelta(minutes=5):
                return
            self.reaction_cd[f"presence_{after.id}"] = now
            
            e = self._embed("👋 Status změna", f"{after.mention}\n\n" + "\n".join(changes))
            e.set_author(name=str(after), icon_url=after.display_avatar.url)
            self.to_profile(e)  

    
    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        cfg = self.cfg(guild.id)
        if not (cfg.enabled and cfg.log_moderation):
            return
            
        e = self._embed("🔨 Ban", f"{user.mention} (`{user}`)", color=0xED4245)
        e.add_field(name="ID", value=str(user.id), inline=True)
        e.add_field(name="Bot", value="✅" if user.bot else "❌", inline=True)
        
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.ban, limit=10):
                if entry.target.id == user.id and (datetime.now(timezone.utc) - entry.created_at) < timedelta(seconds=60):
                    if entry.user: 
                        e.add_field(name="Moderátor", value=entry.user.mention, inline=True)
                    if entry.reason: 
                        e.add_field(name="Důvod", value=clamp(entry.reason, 512), inline=False)
                    break
        except discord.Forbidden:
            pass
            
        e.set_thumbnail(url=user.display_avatar.url)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        cfg = self.cfg(guild.id)
        if not (cfg.enabled and cfg.log_moderation):
            return
            
        e = self._embed("✅ Unban", f"{user.mention} (`{user}`)", color=0x57F287)
        e.add_field(name="ID", value=str(user.id), inline=True)
        
        try:
            async for entry in guild.audit_logs(action=discord.AuditLogAction.unban, limit=10):
                if entry.target.id == user.id and (datetime.now(timezone.utc) - entry.created_at) < timedelta(seconds=60):
                    if entry.user: 
                        e.add_field(name="Moderátor", value=entry.user.mention, inline=True)
                    if entry.reason: 
                        e.add_field(name="Důvod", value=clamp(entry.reason, 512), inline=False)
                    break
        except discord.Forbidden:
            pass
            
        e.set_thumbnail(url=user.display_avatar.url)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule):
        cfg = self.cfg(rule.guild.id)
        if not (cfg.enabled and cfg.log_automod):
            return
            
        e = self._embed("🛡️ AutoMod pravidlo vytvořeno", f"**{rule.name}**", color=0x57F287)
        e.add_field(name="ID", value=str(rule.id), inline=True)
        e.add_field(name="Aktivní", value="✅" if rule.enabled else "❌", inline=True)
        if rule.creator:
            e.add_field(name="Vytvořil", value=rule.creator.mention, inline=True)
        if hasattr(rule, 'trigger_type') and rule.trigger_type:
            e.add_field(name="Typ triggeru", value=str(rule.trigger_type), inline=True)
        if hasattr(rule, 'actions') and rule.actions:
            actions = [str(action.type) for action in rule.actions[:3]]
            e.add_field(name="Akce", value=", ".join(actions), inline=False)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_automod_rule_update(self, before, after):
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_automod):
            return
            
        changes = []
        if before.name != after.name:
            changes.append(f"**Název:** `{before.name}` → `{after.name}`")
        if before.enabled != after.enabled:
            changes.append(f"**Status:** {'aktivní' if after.enabled else 'neaktivní'}")
            
        if changes:
            e = self._embed("🛡️ AutoMod pravidlo upraveno", f"**{after.name}**\n\n" + "\n".join(changes))
            e.add_field(name="ID", value=str(after.id), inline=True)
            self.to_main(e)

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule):
        cfg = self.cfg(rule.guild.id)
        if not (cfg.enabled and cfg.log_automod):
            return
            
        e = self._embed("🛡️ AutoMod pravidlo smazáno", f"**{rule.name}**", color=0xED4245)
        e.add_field(name="ID", value=str(rule.id), inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_automod_action(self, execution):
        cfg = self.cfg(execution.guild.id)
        if not (cfg.enabled and cfg.log_automod):
            return
            
        e = self._embed("🛡️ AutoMod akce", f"Pravidlo **{execution.rule_name}** aktivováno", color=0xFEE75C)
        e.add_field(name="Uživatel", value=execution.user.mention, inline=True)
        e.add_field(name="Kanál", value=execution.channel.mention, inline=True)
        if execution.content:
            e.add_field(name="Obsah", value=f"```{clamp(execution.content, 200)}```", inline=False)
        if execution.matched_keyword:
            e.add_field(name="Klíčové slovo", value=f"`{execution.matched_keyword}`", inline=True)
        e.add_field(name="Akce", value=str(execution.action.type), inline=True)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        cfg = self.cfg(message.guild.id)
        if not (cfg.enabled and cfg.log_messages):
            return
        if message.channel.id in cfg.ignored_channels or message.author.id in cfg.ignored_users:
            return
            
        
        now = datetime.now(timezone.utc)
        last = self.message_cd.get(message.channel.id)
        if last and (now - last) < timedelta(seconds=1.5):
            return
        self.message_cd[message.channel.id] = now

        content = clamp(message.content or "*bez textu*", 1000)
        e = self._embed("🗑️ Zpráva smazána", color=0xED4245)
        e.add_field(name="Autor", value=f"{message.author.mention} (`{message.author}`)", inline=True)
        e.add_field(name="Kanál", value=message.channel.mention, inline=True)
        e.add_field(name="ID zprávy", value=str(message.id), inline=True)
        
        if message.created_at:
            age = datetime.now(timezone.utc) - message.created_at
            e.add_field(name="Stáří zprávy", value=human_delta(age), inline=True)
            e.add_field(name="Vytvořena", value=ts(message.created_at), inline=True)

        if content != "*bez textu*":
            e.add_field(name="Obsah", value=f"```{content}```", inline=False)

        files: List[discord.File] = []
        if message.attachments:
            info = []
            for att in message.attachments[:5]:
                size_mb = round(att.size / 1024 / 1024, 2) if att.size else 0
                info.append(f"📎 `{att.filename}` ({size_mb} MB)")
                
                if att.size and att.size < 8 * 1024 * 1024:
                    try:
                        data = await att.read()
                        files.append(discord.File(io.BytesIO(data), filename=f"deleted_{att.filename}"))
                    except Exception as ex:
                        logger.warning(f"Nepodařilo se uložit přílohu: {ex}")
            e.add_field(name="Přílohy", value="\n".join(info), inline=False)
            
        if message.embeds:
            embed_info = []
            for i, emb in enumerate(message.embeds[:3]):
                embed_info.append(f"#{i+1}: {emb.title or 'Bez názvu'}")
            e.add_field(name="Embedy", value="\n".join(embed_info), inline=True)

        if message.reference and message.reference.message_id:
            e.add_field(name="Odpověď na", value=f"[Zpráva](https://discord.com/channels/{message.guild.id}/{message.channel.id}/{message.reference.message_id})", inline=True)

        e.set_author(name=str(message.author), icon_url=message.author.display_avatar.url)
        self.to_main(e, files)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages: List[discord.Message]):
        if not messages or not messages[0].guild:
            return
        g = messages[0].guild
        cfg = self.cfg(g.id)
        if not (cfg.enabled and cfg.log_messages):
            return
            
        ch_id = messages[0].channel.id
        if ch_id in cfg.ignored_channels:
            return
            
        now = datetime.now(timezone.utc)
        last = self.bulk_cd.get(ch_id)
        if last and (now - last) < timedelta(seconds=8):
            return
        self.bulk_cd[ch_id] = now

        channel = messages[0].channel
        user_msgs = [m for m in messages if not m.author.bot]
        bot_msgs = [m for m in messages if m.author.bot]
        
        e = self._embed("🗑️ Hromadné mazání zpráv", color=0xED4245)
        e.add_field(name="Kanál", value=channel.mention, inline=True)
        e.add_field(name="Celkem", value=str(len(messages)), inline=True)
        e.add_field(name="Uživatelské", value=str(len(user_msgs)), inline=True)
        e.add_field(name="Bot zprávy", value=str(len(bot_msgs)), inline=True)
        
        if user_msgs:
            counts: Dict[discord.abc.User, int] = {}
            for m in user_msgs:
                counts[m.author] = counts.get(m.author, 0) + 1
            top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:7]
            e.add_field(name="Top autoři", value="\n".join(f"{a.mention}: {c}" for a, c in top), inline=False)
            
        
        times = [m.created_at for m in messages if m.created_at]
        if times:
            oldest = min(times)
            newest = max(times)
            timespan = newest - oldest
            e.add_field(name="Časový rozsah", value=f"{ts(oldest, 'R')} - {ts(newest, 'R')}\n({human_delta(timespan)})", inline=False)
            
        self.to_main(e)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not after.guild or after.author.bot or (before.content == after.content):
            return
        cfg = self.cfg(after.guild.id)
        if not (cfg.enabled and cfg.log_messages):
            return
        if after.channel.id in cfg.ignored_channels or after.author.id in cfg.ignored_users:
            return
            
        now = datetime.now(timezone.utc)
        last = self.message_cd.get(after.channel.id)
        if last and (now - last) < timedelta(seconds=0.8):
            return
        self.message_cd[after.channel.id] = now

        e = self._embed("✏️ Zpráva upravena", color=0xFEE75C)
        e.add_field(name="Autor", value=f"{after.author.mention} (`{after.author}`)", inline=True)
        e.add_field(name="Kanál", value=after.channel.mention, inline=True)
        e.add_field(name="ID zprávy", value=str(after.id), inline=True)
        
        before_content = clamp(before.content or '*prázdné*', 500)
        after_content = clamp(after.content or '*prázdné*', 500)
        
        e.add_field(name="Před", value=f"```{before_content}```", inline=False)
        e.add_field(name="Po", value=f"```{after_content}```", inline=False)
        e.add_field(name="Odkaz", value=f"[Přejít na zprávu]({after.jump_url})", inline=True)
        
        if after.edited_at:
            e.add_field(name="Upraveno", value=ts(after.edited_at), inline=True)
        
        e.set_author(name=str(after.author), icon_url=after.author.display_avatar.url)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction: discord.Reaction, user: discord.User):
        g = reaction.message.guild
        if not g or user.bot:
            return
        cfg = self.cfg(g.id)
        if not (cfg.enabled and cfg.log_reactions):
            return
        if reaction.message.channel.id in cfg.ignored_channels or user.id in cfg.ignored_users:
            return
            
        
        now = datetime.now(timezone.utc)
        key = f"reaction_{reaction.message.id}_{user.id}"
        last = self.reaction_cd.get(key)
        if last and (now - last) < timedelta(seconds=10):
            return
        self.reaction_cd[key] = now
        
        e = self._embed("👍 Reakce přidána", color=0x57F287)
        e.add_field(name="Uživatel", value=user.mention, inline=True)
        e.add_field(name="Kanál", value=reaction.message.channel.mention, inline=True)
        e.add_field(name="Reakce", value=str(reaction.emoji), inline=True)
        e.add_field(name="Zpráva", value=f"[Odkaz]({reaction.message.jump_url})", inline=True)
        
        if reaction.message.content:
            e.add_field(name="Obsah zprávy", value=clamp(reaction.message.content, 200), inline=False)
        
        e.set_author(name=str(user), icon_url=user.display_avatar.url)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction: discord.Reaction, user: discord.User):
        g = reaction.message.guild
        if not g or user.bot:
            return
        cfg = self.cfg(g.id)
        if not (cfg.enabled and cfg.log_reactions):
            return
        if reaction.message.channel.id in cfg.ignored_channels or user.id in cfg.ignored_users:
            return
            
        e = self._embed("👎 Reakce odebrána", color=0xED4245)
        e.add_field(name="Uživatel", value=user.mention, inline=True)
        e.add_field(name="Kanál", value=reaction.message.channel.mention, inline=True)
        e.add_field(name="Reakce", value=str(reaction.emoji), inline=True)
        e.add_field(name="Zpráva", value=f"[Odkaz]({reaction.message.jump_url})", inline=True)
        e.set_author(name=str(user), icon_url=user.display_avatar.url)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_reaction_clear(self, message: discord.Message, reactions: List[discord.Reaction]):
        if not message.guild:
            return
        cfg = self.cfg(message.guild.id)
        if not (cfg.enabled and cfg.log_reactions):
            return
            
        e = self._embed("🧹 Všechny reakce odstraněny", color=0xED4245)
        e.add_field(name="Kanál", value=message.channel.mention, inline=True)
        e.add_field(name="Zpráva", value=f"[Odkaz]({message.jump_url})", inline=True)
        e.add_field(name="Počet reakcí", value=str(len(reactions)), inline=True)
        
        if reactions:
            reaction_list = " ".join(str(r.emoji) for r in reactions[:15])
            if len(reactions) > 15:
                reaction_list += f" (+{len(reactions)-15})"
            e.add_field(name="Reakce", value=reaction_list, inline=False)
            
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        cfg = self.cfg(member.guild.id)
        if not (cfg.enabled and cfg.log_voice):
            return
        if member.id in cfg.ignored_users or member.bot:
            return
            
        changes = []
        emoji = "🔊"
        color = 0x5865F2
        
        
        if before.channel != after.channel:
            if before.channel is None and after.channel:
                changes.append(f"**Připojil se do:** {after.channel.mention}")
                emoji, color = "📞", 0x57F287
            elif before.channel and after.channel is None:
                changes.append(f"**Odpojil se z:** {before.channel.mention}")
                emoji, color = "📴", 0xED4245
            else:
                changes.append(f"**Přesun:** {before.channel.mention} → {after.channel.mention}")
                emoji, color = "🔄", 0xFEE75C
                
        
        if after.channel:
            
            if before.mute != after.mute: 
                changes.append(f"**Server mute:** {'ztišen' if after.mute else 'odtišen'}")
            if before.deaf != after.deaf: 
                changes.append(f"**Server deaf:** {'ohlušen' if after.deaf else 'odhlušen'}")
                
            
            if before.self_mute != after.self_mute: 
                changes.append(f"**Self mute:** {'zap' if after.self_mute else 'vyp'}")
            if before.self_deaf != after.self_deaf: 
                changes.append(f"**Self deaf:** {'zap' if after.self_deaf else 'vyp'}")
                
            
            if before.self_stream != after.self_stream:
                changes.append(f"**Stream:** {'začal streamovat' if after.self_stream else 'skončil stream'}"); 
                if after.self_stream: emoji = "📺"
            if before.self_video != after.self_video:
                changes.append(f"**Kamera:** {'zapnul kameru' if after.self_video else 'vypnul kameru'}"); 
                if after.self_video: emoji = "📹"
                
            
            if hasattr(before, 'suppress') and hasattr(after, 'suppress') and before.suppress != after.suppress:
                changes.append(f"**Stage suppress:** {'potlačen' if after.suppress else 'nepotlačen'}")
                
            
            if hasattr(before, 'requested_to_speak_at') and hasattr(after, 'requested_to_speak_at'):
                if before.requested_to_speak_at != after.requested_to_speak_at:
                    if after.requested_to_speak_at:
                        changes.append("**Žádost o mluvení:** požádal")
                    else:
                        changes.append("**Žádost o mluvení:** zrušena")

        if changes:
            e = self._embed(f"{emoji} Voice aktivita", f"{member.mention}\n\n" + "\n".join(changes), color=color)
            e.set_author(name=str(member), icon_url=member.display_avatar.url)
            
            current_channel = after.channel or before.channel
            if current_channel:
                e.add_field(name="Kanál", value=current_channel.mention, inline=True)
                e.add_field(name="Uživatelů v kanálu", value=str(len(current_channel.members)), inline=True)
                if hasattr(current_channel, 'bitrate'):
                    e.add_field(name="Bitrate", value=f"{current_channel.bitrate}bps", inline=True)
                    
            self.to_main(e)

    
    @commands.Cog.listener()
    async def on_integration_create(self, integration):
        cfg = self.cfg(integration.guild.id)
        if not (cfg.enabled and cfg.log_integrations):
            return
            
        e = self._embed("🔗 Integrace přidána", f"**{integration.name}**", color=0x57F287)
        e.add_field(name="Typ", value=str(integration.type), inline=True)
        e.add_field(name="ID", value=str(integration.id), inline=True)
        if integration.user:
            e.add_field(name="Přidal", value=integration.user.mention, inline=True)
        if hasattr(integration, 'account') and integration.account:
            e.add_field(name="Účet", value=f"{integration.account.name} ({integration.account.id})", inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_integration_update(self, integration):
        cfg = self.cfg(integration.guild.id)
        if not (cfg.enabled and cfg.log_integrations):
            return
            
        e = self._embed("🔗 Integrace upravena", f"**{integration.name}**", color=0xFEE75C)
        e.add_field(name="Typ", value=str(integration.type), inline=True)
        e.add_field(name="ID", value=str(integration.id), inline=True)
        if integration.user:
            e.add_field(name="Upravil", value=integration.user.mention, inline=True)
        self.to_main(e)

    @commands.Cog.listener()
    async def on_integration_delete(self, integration):
        cfg = self.cfg(integration.guild.id)
        if not (cfg.enabled and cfg.log_integrations):
            return
            
        e = self._embed("🔗 Integrace smazána", f"**{integration.name}**", color=0xED4245)
        e.add_field(name="Typ", value=str(integration.type), inline=True)
        e.add_field(name="ID", value=str(integration.id), inline=True)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: discord.app_commands.Command):
        if not interaction.guild:
            return
        cfg = self.cfg(interaction.guild.id)
        if not (cfg.enabled and cfg.log_applications):
            return
        if interaction.user.id in cfg.ignored_users:
            return
            
        e = self._embed("⚡ Slash příkaz použit", color=0x5865F2)
        e.add_field(name="Uživatel", value=interaction.user.mention, inline=True)
        e.add_field(name="Kanál", value=interaction.channel.mention if interaction.channel else "DM", inline=True)
        e.add_field(name="Příkaz", value=f"`/{command.name}`", inline=True)
        
        
        if hasattr(interaction, 'data') and 'options' in interaction.data:
            options = []
            for opt in interaction.data['options'][:5]:  
                options.append(f"`{opt['name']}`: {opt.get('value', 'N/A')}")
            if options:
                e.add_field(name="Parametry", value="\n".join(options), inline=False)
                
        e.add_field(name="ID interakce", value=str(interaction.id), inline=True)
        e.set_author(name=str(interaction.user), icon_url=interaction.user.display_avatar.url)
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_audit_log_entry_create(self, entry: discord.AuditLogEntry):
        cfg = self.cfg(entry.guild.id)
        if not (cfg.enabled and cfg.log_moderation):
            return
            
        
        interesting_actions = {
            discord.AuditLogAction.message_delete: "🗑️ Moderace - zpráva smazána",
            discord.AuditLogAction.message_bulk_delete: "🗑️ Moderace - bulk delete",
            discord.AuditLogAction.message_pin: "📌 Zpráva připnuta",
            discord.AuditLogAction.message_unpin: "📌 Zpráva odepnuta",
            discord.AuditLogAction.member_prune: "🧹 Prune členů",
            discord.AuditLogAction.bot_add: "🤖 Bot přidán",
            discord.AuditLogAction.integration_create: "🔗 Integrace vytvořena",
            discord.AuditLogAction.integration_delete: "🔗 Integrace smazána",
        }
        
        if entry.action not in interesting_actions:
            return
            
        e = self._embed(interesting_actions[entry.action], color=0xFEE75C)
        
        if entry.user:
            e.add_field(name="Moderátor", value=entry.user.mention, inline=True)
        if entry.target:
            e.add_field(name="Cíl", value=str(entry.target), inline=True)
        if entry.reason:
            e.add_field(name="Důvod", value=clamp(entry.reason, 300), inline=False)
            
        e.add_field(name="Čas", value=ts(entry.created_at), inline=True)
        e.add_field(name="ID", value=str(entry.id), inline=True)
        
        
        if entry.action == discord.AuditLogAction.member_prune and hasattr(entry, 'extra'):
            if hasattr(entry.extra, 'delete_member_days'):
                e.add_field(name="Dny neaktivity", value=str(entry.extra.delete_member_days), inline=True)
            if hasattr(entry.extra, 'members_removed'):
                e.add_field(name="Odstraněno členů", value=str(entry.extra.members_removed), inline=True)
                
        self.to_main(e)

    
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError):
        cfg = self.cfg(ctx.guild.id) if ctx.guild else LogConfig()
        if not (cfg.enabled and cfg.log_moderation):
            return
            
        
        if isinstance(error, (commands.CommandNotFound, commands.CheckFailure)):
            return
            
        e = self._embed("⚠️ Chyba příkazu", f"Příkaz: `{ctx.command}`", color=0xED4245)
        e.add_field(name="Uživatel", value=ctx.author.mention, inline=True)
        e.add_field(name="Kanál", value=ctx.channel.mention, inline=True)
        e.add_field(name="Chyba", value=f"```{type(error).__name__}```", inline=True)
        
        if len(str(error)) < 500:
            e.add_field(name="Detail", value=f"```{str(error)}```", inline=False)
            
        e.set_author(name=str(ctx.author), icon_url=ctx.author.display_avatar.url)
        self.to_main(e)

    
    @log_group.command(name="ignore", description="Přidá/odebere kanál nebo uživatele z ignorování")
    @app_commands.describe(
        target_type="Co ignorovat",
        target_id="ID kanálu nebo uživatele", 
        action="Přidat nebo odebrat"
    )
    @app_commands.choices(
        target_type=[
            app_commands.Choice(name="Kanál", value="channel"),
            app_commands.Choice(name="Uživatel", value="user")
        ],
        action=[
            app_commands.Choice(name="Přidat", value="add"),
            app_commands.Choice(name="Odebrat", value="remove")
        ]
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def ignore_target(self, itx: discord.Interaction, target_type: str, target_id: str, action: str):
        try:
            tid = int(target_id)
        except ValueError:
            await itx.response.send_message("❌ Neplatné ID", ephemeral=True)
            return
            
        cfg = self.cfg(itx.guild_id)
        
        if target_type == "channel":
            target_set = cfg.ignored_channels
            name = "kanál"
        else:
            target_set = cfg.ignored_users  
            name = "uživatel"
            
        if action == "add":
            target_set.add(tid)
            emoji = "✅"
            verb = "přidán do"
        else:
            target_set.discard(tid)
            emoji = "❌" 
            verb = "odebrán z"
            
        self.set_cfg(itx.guild_id, cfg)
        await itx.response.send_message(f"{emoji} {name.title()} `{tid}` {verb} ignorovaných", ephemeral=True)

    @log_group.command(name="stats", description="Statistiky logování")
    async def log_stats(self, itx: discord.Interaction):
        e = self._embed("📊 Statistiky logování")
        
        uptime = human_delta(datetime.now(timezone.utc) - self.started_at)
        e.add_field(name="Uptime", value=uptime, inline=True)
        e.add_field(name="Odesláno logů", value=str(self.stats["logs_sent"]), inline=True)
        e.add_field(name="Fronta", value=f"{len(self.queue.q)}/{self.queue.max}", inline=True)
        
        
        e.add_field(name="Cache členů", value=str(len(self.cache.cache)), inline=True)
        e.add_field(name="Aktivních serverů", value=str(len([gid for gid, cfg in self.cfgs.items() if cfg.enabled])), inline=True)
        e.add_field(name="Celkem serverů", value=str(len(self.bot.guilds)), inline=True)
        
        
        active_cooldowns = len([cd for cd in self.message_cd.values() if (datetime.now(timezone.utc) - cd) < timedelta(minutes=5)])
        e.add_field(name="Aktivní cooldowny", value=str(active_cooldowns), inline=True)
        
        main_ch, profile_ch = await self.ensure_channels_exist()
        e.add_field(name="Kanály", value=f"Main: {'✅' if main_ch else '❌'}\nProfile: {'✅' if profile_ch else '❌'}", inline=True)
        
        await itx.response.send_message(embed=e, ephemeral=True)

    @log_group.command(name="test", description="Testovací zpráva do logů")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test_log(self, itx: discord.Interaction):
        
        e1 = self._embed("🧪 Test hlavního logu", "Toto je testovací zpráva do hlavního log kanálu", color=0x00FF00)
        e1.add_field(name="Iniciátor", value=itx.user.mention, inline=True)
        e1.add_field(name="Čas", value=ts(), inline=True)
        self.to_main(e1)
        
        
        e2 = self._embed("🧪 Test profilového logu", "Toto je testovací zpráva do profilového log kanálu", color=0x00FF00)
        e2.add_field(name="Iniciátor", value=itx.user.mention, inline=True)
        e2.add_field(name="Čas", value=ts(), inline=True)
        self.to_profile(e2)
        
        await itx.response.send_message("✅ Testovací zprávy odeslány do obou log kanálů", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(LogCog(bot))
    logger.info("✅ LogCog nahrán - OPTIMALIZOVANÁ VERZE s rozšířeným logováním")
