# commands/emojirole.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import json
import random
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, List

import discord
from discord import app_commands
from discord.ext import commands


CONFIG_PATH = Path("data/challenge_config.json")
CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class ChallengeConfig:
    guild_id: int
    role_id: int | None = None
    channel_id: int | None = None
    emojis: List[str] = field(default_factory=list)

    # UX chování
    react_ok: bool = True
    reply_on_success: bool = True

    # zprávy, ze kterých se náhodně vybírá po úspěchu
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
    ])

    # logika
    allow_extra_chars: bool = True
    require_all: bool = True  # vyžadovat všechny emojis v kombinaci

    def to_json(self) -> dict[str, Any]:
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
            success_messages=list(d.get("success_messages") or []) or [
                "Vítej ve výzvě! ✅",
                "Hotovo — jsi zapsán/a. 💪",
                "Přihláška potvrzena. 🎉",
                "Paráda, vítáme tě! 🙌",
                "Gratuluji, máš to! 🔥",
                "Úspěšně přihlášen/a! 🎊",
                "Skvělá práce! 🏆",
                "Jsi in! 😎",
                "Welcome aboard! 🚀",
                "Máš to za sebou! ✨",
                "Povedlo se! 🎯",
                "Hurá, jsi tady! 🎈",
                "You're in! 🔓",
                "Unlocked! 🗝️",
            ],
            allow_extra_chars=bool(d.get("allow_extra_chars", True)),
            require_all=bool(d.get("require_all", True)),
        )


def _load_db() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_db(db: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")


def _save_config(cfg: ChallengeConfig) -> None:
    db = _load_db()
    db[str(cfg.guild_id)] = cfg.to_json()
    _save_db(db)


def _load_config(guild_id: int) -> ChallengeConfig | None:
    db = _load_db()
    rec = db.get(str(guild_id))
    return ChallengeConfig.from_json(rec) if rec else None


def _parse_channel_any(s: str | discord.abc.GuildChannel | None, guild: discord.Guild) -> discord.TextChannel | None:
    """Podpora: <#123>, číslo, název, nebo rovnou objekt."""
    if s is None:
        return None
    if isinstance(s, discord.TextChannel):
        return s
    if isinstance(s, discord.abc.GuildChannel):
        return s if isinstance(s, discord.TextChannel) else None

    s = str(s).strip()
    m = re.match(r"<#(\d+)>", s)
    if m:
        cid = int(m.group(1))
        ch = guild.get_channel(cid)
        return ch if isinstance(ch, discord.TextChannel) else None
    if s.isdigit():
        ch = guild.get_channel(int(s))
        return ch if isinstance(ch, discord.TextChannel) else None

    s_lower = s.lower()
    for ch in guild.text_channels:
        if ch.name.lower() == s_lower:
            return ch
    return None


def _split_emoji_list(raw: str) -> list[str]:
    """
    Přijme: '🍁 :strongdoge: 🔥' nebo '🍁, :strongdoge:, 🔥' (uvozovky nevadí).
    """
    raw = raw.strip().strip("\"' ")
    raw = raw.replace(",", " ")
    parts = [p for p in raw.split() if p]
    return parts


def _match_custom_emoji(name_or_token: str, content: str) -> bool:
    """
    Ověří přítomnost custom emoji:
    - ':name:' → matchne ':name:' i '<:name:id>' / '<a:name:id>'
    - '<:name:id>' → substring
    """
    token = name_or_token.strip()
    if token.startswith("<") and token.endswith(">"):
        return token in content

    m = re.fullmatch(r":([a-zA-Z0-9_~\-]+):", token)
    if not m:
        return token in content
    name = m.group(1)

    if f":{name}:" in content:
        return True
    pattern = rf"<a?:{re.escape(name)}:\d+>"
    return re.search(pattern, content) is not None


def _message_contains_all_targets(content: str, targets: list[str]) -> bool:
    for t in targets:
        t = t.strip()
        if not t:
            continue
        # unicode emoji — substring
        if not (t.startswith(":") and t.endswith(":")) and not (t.startswith("<") and t.endswith(">")):
            ok = t in content
        else:
            ok = _match_custom_emoji(t, content)
        if not ok:
            return False
    return True


class ChallengeCog(commands.Cog):
    """Reakce na kombinaci emoji v daném kanále → přidá roli + odpoví/potvrdí."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ------------ Slash /challenge ------------

    challenge = app_commands.Group(
        name="challenge",
        description="Nastavení emoji-výzvy (role za kombinaci emoji).",
        default_permissions=discord.Permissions(administrator=True),
    )

    @challenge.command(name="setup", description="Uloží konfiguraci (role, kanál, emoji).")
    @app_commands.describe(
        role="Role, která se má udělit.",
        channel_name="Kanál ve formátu <#id>, ID nebo název (např. npn-vyzva-2025).",
        emojis='Seznam emoji (např. \'🍁 :strongdoge: 🔥\' nebo "🍁, :strongdoge:, 🔥").',
    )
    async def slash_setup(
        self,
        itx: discord.Interaction,
        role: discord.Role,
        channel_name: str,
        emojis: str,
    ):
        await itx.response.defer(ephemeral=True)
        ch = _parse_channel_any(channel_name, itx.guild)
        if not ch:
            await itx.followup.send(f"❌ Kanál `{channel_name}` neexistuje.", ephemeral=True)
            return
        em_list = _split_emoji_list(emojis)
        if not em_list:
            await itx.followup.send("❌ Zadej alespoň jedno emoji.", ephemeral=True)
            return

        cfg = _load_config(itx.guild_id) or ChallengeConfig(guild_id=itx.guild_id)
        cfg.role_id = role.id
        cfg.channel_id = ch.id
        cfg.emojis = em_list
        _save_config(cfg)

        await itx.followup.send(
            f"✅ Uloženo.\n• Role: {role.mention}\n• Kanál: {ch.mention}\n• Emojis: {' '.join(em_list)}",
            ephemeral=True,
        )

    @challenge.command(name="show", description="Zobrazí aktuální konfiguraci.")
    async def slash_show(self, itx: discord.Interaction):
        cfg = _load_config(itx.guild_id)
        if not cfg or not cfg.role_id or not cfg.channel_id or not cfg.emojis:
            await itx.response.send_message("ℹ️ Konfigurace zatím není nastavená.", ephemeral=True)
            return
        role = itx.guild.get_role(cfg.role_id)
        ch = itx.guild.get_channel(cfg.channel_id)
        await itx.response.send_message(
            f"• Role: {role.mention if role else cfg.role_id}\n"
            f"• Kanál: {ch.mention if ch else cfg.channel_id}\n"
            f"• Emojis: {' '.join(cfg.emojis)}",
            ephemeral=True,
        )

    @challenge.command(name="messages", description="Správa přihláškových zpráv.")
    @app_commands.describe(action="add|list|clear", text="Text nové zprávy (pro 'add').")
    async def slash_messages(self, itx: discord.Interaction, action: str, text: str | None = None):
        action = action.lower().strip()
        cfg = _load_config(itx.guild_id) or ChallengeConfig(guild_id=itx.guild_id)

        if action == "add":
            if not text:
                await itx.response.send_message("❌ Zadej text zprávy.", ephemeral=True)
                return
            cfg.success_messages.append(text)
            _save_config(cfg)
            await itx.response.send_message(f"✅ Přidána zpráva.\nCelkem: {len(cfg.success_messages)}", ephemeral=True)
            return

        if action == "list":
            if not cfg.success_messages:
                await itx.response.send_message("Žádné zprávy nejsou uložené.", ephemeral=True)
                return
            bullet = "\n".join(f"{i+1}. {m}" for i, m in enumerate(cfg.success_messages))
            await itx.response.send_message(bullet, ephemeral=True)
            return

        if action == "clear":
            cfg.success_messages.clear()
            _save_config(cfg)
            await itx.response.send_message("🗑️ Zprávy smazány.", ephemeral=True)
            return

        await itx.response.send_message("Použij `add|list|clear`.", ephemeral=True)

    @challenge.command(name="settings", description="Přepínače reakcí/odpovědí.")
    @app_commands.describe(
        react_ok="Reakce na úspěšnou zprávu (✅).",
        reply_on_success="Odpovědět přihláškovou zprávou.",
        require_all="Musí obsahovat všechna emoji (jinak stačí některé).",
    )
    async def slash_settings(
        self,
        itx: discord.Interaction,
        react_ok: bool | None = None,
        reply_on_success: bool | None = None,
        require_all: bool | None = None,
    ):
        cfg = _load_config(itx.guild_id) or ChallengeConfig(guild_id=itx.guild_id)
        if react_ok is not None:
            cfg.react_ok = react_ok
        if reply_on_success is not None:
            cfg.reply_on_success = reply_on_success
        if require_all is not None:
            cfg.require_all = require_all
        _save_config(cfg)

        await itx.response.send_message(
            "✅ Uloženo.\n"
            f"react_ok={cfg.react_ok}, "
            f"reply_on_success={cfg.reply_on_success}, "
            f"require_all={cfg.require_all}",
            ephemeral=True,
        )

    @challenge.command(name="clear", description="Smaže konfiguraci pro tuto guildu.")
    async def slash_clear(self, itx: discord.Interaction):
        db = _load_db()
        if str(itx.guild_id) in db:
            del db[str(itx.guild_id)]
            _save_db(db)
            await itx.response.send_message("🗑️ Konfigurace smazána.", ephemeral=True)
        else:
            await itx.response.send_message("ℹ️ Nebyla nalezena žádná konfigurace.", ephemeral=True)

    # ------------ Prefix *challenge ------------

    @commands.command(name="challenge")
    @commands.has_permissions(administrator=True)
    async def prefix_challenge(self, ctx: commands.Context, *, args: str = ""):
        """
        *challenge setup role:@Role channel_name:<#id|id|nazev> emojis:"🍁 :strongdoge: 🔥"
        *challenge show
        *challenge clear
        *challenge messages add text:"Vítej!"
        *challenge messages list
        *challenge messages clear
        """
        parts = args.strip().split()
        if not parts:
            await ctx.reply("Použití: *challenge setup/show/clear/messages …", mention_author=False)
            return

        sub = parts[0].lower()

        if sub == "show":
            cfg = _load_config(ctx.guild.id)
            if not cfg or not cfg.role_id or not cfg.channel_id or not cfg.emojis:
                await ctx.reply("ℹ️ Konfigurace zatím není nastavená.", mention_author=False)
                return
            role = ctx.guild.get_role(cfg.role_id)
            ch = ctx.guild.get_channel(cfg.channel_id)
            await ctx.reply(
                f"• Role: {role.mention if role else cfg.role_id}\n"
                f"• Kanál: {ch.mention if ch else cfg.channel_id}\n"
                f"• Emojis: {' '.join(cfg.emojis)}",
                mention_author=False,
            )
            return

        if sub == "clear":
            db = _load_db()
            if str(ctx.guild.id) in db:
                del db[str(ctx.guild.id)]
                _save_db(db)
                await ctx.reply("🗑️ Konfigurace smazána.", mention_author=False)
            else:
                await ctx.reply("ℹ️ Nebyla nalezena žádná konfigurace.", mention_author=False)
            return

        if sub == "messages":
            if len(parts) < 2:
                await ctx.reply("Použij: *challenge messages add|list|clear …", mention_author=False)
                return
            action = parts[1].lower()
            cfg = _load_config(ctx.guild.id) or ChallengeConfig(guild_id=ctx.guild.id)
            if action == "add":
                m = re.search(r'text:"([^"]+)"|text:\'([^\']+)\'|text:(.+)$', args, flags=re.I)
                if not m:
                    await ctx.reply("Chybí text. Příklad: *challenge messages add text:\"Vítej!\"", mention_author=False)
                    return
                text = next(g for g in m.groups() if g)
                cfg.success_messages.append(text)
                _save_config(cfg)
                await ctx.reply(f"✅ Přidáno. Celkem: {len(cfg.success_messages)}", mention_author=False)
            elif action == "list":
                if not cfg.success_messages:
                    await ctx.reply("Žádné zprávy nejsou uložené.", mention_author=False)
                else:
                    bullet = "\n".join(f"{i+1}. {m}" for i, m in enumerate(cfg.success_messages))
                    await ctx.reply(bullet, mention_author=False)
            elif action == "clear":
                cfg.success_messages.clear()
                _save_config(cfg)
                await ctx.reply("🗑️ Zprávy smazány.", mention_author=False)
            else:
                await ctx.reply("Použij add|list|clear.", mention_author=False)
            return

        if sub != "setup":
            await ctx.reply("Neznámý subpříkaz. Použij `setup|show|clear|messages`.", mention_author=False)
            return

        m_role = re.search(r"role:(<@&\d+>|@\S+|\d+)", args, flags=re.I)
        m_ch = re.search(r"channel_name:([^\s]+)", args, flags=re.I)
        m_emo = re.search(r'emojis:"([^"]+)"|emojis:\'([^\']+)\'|emojis:([^\s]+)', args, flags=re.I)

        if not (m_role and m_ch and m_emo):
            await ctx.reply(
                "Chybí některý z parametrů. Příklad:\n"
                "`*challenge setup role:@Účastník channel_name:<#1234567890> emojis:\"🍁 :strongdoge: 🔥\"`",
                mention_author=False,
            )
            return

        role_token = (m_role.group(1) or "").strip()
        role_obj = None
        if role_token.startswith("<@&") and role_token.endswith(">"):
            rid = int(role_token[3:-1])
            role_obj = ctx.guild.get_role(rid)
        elif role_token.startswith("@"):
            name = role_token[1:]
            role_obj = discord.utils.get(ctx.guild.roles, name=name)
        elif role_token.isdigit():
            role_obj = ctx.guild.get_role(int(role_token))
        if not role_obj:
            await ctx.reply(f"❌ Role `{role_token}` nenalezena.", mention_author=False)
            return

        ch_token = (m_ch.group(1) or "").strip()
        ch_obj = _parse_channel_any(ch_token, ctx.guild)
        if not ch_obj:
            await ctx.reply(f"❌ Kanál `{ch_token}` nenalezen.", mention_author=False)
            return

        emo_raw = next(g for g in m_emo.groups() if g)
        em_list = _split_emoji_list(emo_raw)
        if not em_list:
            await ctx.reply("❌ Zadej alespoň jedno emoji.", mention_author=False)
            return

        cfg = _load_config(ctx.guild.id) or ChallengeConfig(guild_id=ctx.guild.id)
        cfg.role_id = role_obj.id
        cfg.channel_id = ch_obj.id
        cfg.emojis = em_list
        _save_config(cfg)

        await ctx.reply(
            f"✅ Uloženo.\n• Role: {role_obj.mention}\n• Kanál: {ch_obj.mention}\n• Emojis: {' '.join(em_list)}",
            mention_author=False,
        )

    # ------------ Listener: reaguj na zprávy ------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignoruj bota, DM a systémové
        if message.author.bot or not message.guild or not message.content:
            return

        cfg = _load_config(message.guild.id)
        if not cfg or not cfg.role_id or not cfg.channel_id or not cfg.emojis:
            return
        if message.channel.id != cfg.channel_id:
            return

        content = message.content

        # splněno?
        hit = _message_contains_all_targets(content, cfg.emojis) if cfg.require_all else any(
            _message_contains_all_targets(content, [e]) for e in cfg.emojis
        )

        if hit:
            # reakce checkmarkem + role + přihlášková zpráva
            if cfg.react_ok:
                try:
                    await message.add_reaction("✅")
                except Exception:
                    pass

            role = message.guild.get_role(cfg.role_id)
            if role and role not in message.author.roles:
                try:
                    await message.author.add_roles(role, reason="Challenge: kombinace emoji splněna")
                except Exception:
                    pass

            if cfg.reply_on_success and cfg.success_messages:
                try:
                    txt = random.choice(cfg.success_messages)
                    await message.reply(txt, mention_author=False)
                except Exception:
                    pass
            return

        # nesplněno – ignorujeme zprávy bez kombinace (žádná reakce ani odpověď)

    # ---------- úklid při unloadu ----------
    def cog_unload(self):
        try:
            self.bot.tree.remove_command(self.challenge.name, type=self.challenge.type)
        except Exception:
            pass
        try:
            for g in getattr(self.bot, "guilds", []):
                self.bot.tree.remove_command(self.challenge.name, type=self.challenge.type, guild=g)
        except Exception:
            pass


# ---------- setup: registrace cogu + slash group ----------
async def setup(bot: commands.Bot):
    import config  # kvůli GUILD_ID (pokud používáš per-guild sync)
    cog = ChallengeCog(bot)
    await bot.add_cog(cog)

    guild_id = getattr(config, "GUILD_ID", None)
    if guild_id:
        guild_obj = discord.Object(id=int(guild_id))
        try:
            bot.tree.add_command(cog.challenge, guild=guild_obj)
        except app_commands.CommandAlreadyRegistered:
            pass
    else:
        try:
            bot.tree.add_command(cog.challenge)
        except app_commands.CommandAlreadyRegistered:
            pass
