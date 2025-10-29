# commands/server_report.py  (původní název klidně ponech)
# -*- coding: utf-8 -*-
from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction
import json
import config
from datetime import datetime, date, timedelta, time, timezone
import os

# pokus o moderní zoneinfo (pro správné DST); pokud není dostupné, fallback na UTC+1
try:
    from zoneinfo import ZoneInfo
    PRAGUE_TZ = ZoneInfo("Europe/Prague")
except Exception:
    PRAGUE_TZ = timezone(timedelta(hours=1))

# české názvy měsíců
CZECH_MONTHS = [
    "leden", "únor", "březen", "duben", "květen", "červen",
    "červenec", "srpen", "září", "říjen", "listopad", "prosinec"
]

class ServerReport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Setup data folder
        self.data_folder = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(self.data_folder, exist_ok=True)

        self.member_file = os.path.join(self.data_folder, 'member_counts.json')
        self.active_file = os.path.join(self.data_folder, 'active_users.json')

        self.guild_id = config.GUILD_ID
        # preferovaně REPORT_CHANNEL_ID, fallback na staré CONSOLE_CHANNEL_ID pokud existuje
        self.report_channel_id = getattr(config, "REPORT_CHANNEL_ID", getattr(config, "CONSOLE_CHANNEL_ID", None))

        self.load_member_data()
        self.load_active_data()
        self.daily_report_check.start()

    # ====== původní načítání/ukládání ======
    def load_member_data(self):
        try:
            with open(self.member_file, 'r', encoding='utf-8') as f:
                self.member_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.member_data = {}

    def save_member_data(self):
        print(f"📁 Ukládám do: {os.path.abspath(self.member_file)}")
        with open(self.member_file, 'w', encoding='utf-8') as f:
            json.dump(self.member_data, f, ensure_ascii=False, indent=4)

    def load_active_data(self):
        try:
            with open(self.active_file, 'r', encoding='utf-8') as f:
                self.active_data = {k: set(v) for k, v in json.load(f).items()}
        except (FileNotFoundError, json.JSONDecodeError):
            self.active_data = {}

    def save_active_data(self):
        print(f"📁 Ukládám do: {os.path.abspath(self.active_file)}")
        serializable = {k: list(v) for k, v in self.active_data.items()}
        with open(self.active_file, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=4)

    # ====== původní posluchače ======
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild and message.guild.id == self.guild_id and not message.author.bot:
            today = date.today().isoformat()
            users = self.active_data.setdefault(today, set())
            users.add(message.author.id)
            self.save_active_data()

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.guild_id:
            return
        month_key = datetime.utcnow().strftime('%Y-%m')
        self.member_data.setdefault(month_key, {'joins': 0, 'leaves': 0})
        self.member_data[month_key]['joins'] += 1
        self.save_member_data()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != self.guild_id:
            return
        month_key = datetime.utcnow().strftime('%Y-%m')
        self.member_data.setdefault(month_key, {'joins': 0, 'leaves': 0})
        self.member_data[month_key]['leaves'] += 1
        self.save_member_data()

    # ====== původní task ======
    @tasks.loop(time=time(hour=0, minute=5))
    async def daily_report_check(self):
        now = datetime.utcnow()
        print(f"🕐 Spouštím kontrolu: {now}")
        if now.day != 1:
            return
        await self.send_report()

    @daily_report_check.before_loop
    async def before_daily_report(self):
        await self.bot.wait_until_ready()

    # ====== pomocné: výpočet období ======
    def _period_from_year_month(self, year: int | None, month: int | None):
        """Vrátí (start_date, end_date, title_month_name, title_year). Pokud není dáno, vezme předchozí měsíc."""
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        if year and month:
            start_prev = date(year, month, 1)
            # první den dalšího měsíce - 1 den
            if month == 12:
                end_prev = date(year + 1, 1, 1) - timedelta(days=1)
            else:
                end_prev = date(year, month + 1, 1) - timedelta(days=1)
        else:
            # default: minulý měsíc
            last_month_last_day = (now.replace(day=1) - timedelta(days=1)).date()
            start_prev = last_month_last_day.replace(day=1)
            end_prev = last_month_last_day
        month_idx = start_prev.month - 1
        return start_prev, end_prev, CZECH_MONTHS[month_idx].capitalize(), start_prev.year, now

    # ====== rozšířená verze o parametry (zachována kompatibilita) ======
    async def send_report(
        self,
        ctx: commands.Context | None = None,
        *,
        year: int | None = None,
        month: int | None = None,
        target_channel: discord.TextChannel | None = None
    ):
        start_prev, end_prev, month_name_cz, title_year, now = self._period_from_year_month(year, month)

        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            if ctx:
                await ctx.send("❌ Nelze najít cílový server.")
            return

        current_total = guild.member_count

        last_month_key = start_prev.strftime('%Y-%m')
        join_stats = self.member_data.get(last_month_key, {'joins': 0, 'leaves': 0})
        new_members = join_stats.get('joins', 0)
        leaves = join_stats.get('leaves', 0)

        daily_counts = []
        mau_set = set()
        for day_str, users in self.active_data.items():
            try:
                day = datetime.fromisoformat(day_str).date()
            except Exception:
                continue
            if start_prev <= day <= end_prev:
                count = len(users)
                daily_counts.append(count)
                mau_set.update(users)
        avg_dau = sum(daily_counts) / len(daily_counts) if daily_counts else 0
        mau = len(mau_set)
        ratio = f"{(avg_dau / mau * 100):.2f}%" if mau > 0 else 'N/A'

        bots = sum(1 for m in guild.members if m.bot)
        humans = current_total - bots
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        roles = len(guild.roles)

        # zajistí existenci aktuálního klíče pro pokračující měření
        this_month_key = now.strftime('%Y-%m')
        self.member_data.setdefault(this_month_key, {'joins': 0, 'leaves': 0})
        self.save_member_data()

        embed_title = f"Server Report — {month_name_cz} {title_year}"

        try:
            prague_now = now.astimezone(PRAGUE_TZ)
        except Exception:
            prague_now = now

        generated_str = prague_now.strftime('%d.%m.%Y %H:%M')

        embed = discord.Embed(
            title=embed_title,
            timestamp=now,  # UTC
            color=discord.Color.blurple()
        )
        embed.add_field(name="📈 Noví členové", value=str(new_members), inline=True)
        embed.add_field(name="📉 Odchody", value=str(leaves), inline=True)
        embed.add_field(name="👥 Celkem členů", value=str(current_total), inline=True)
        embed.add_field(name="📊 Průměrné DAU", value=f"{avg_dau:.2f}", inline=True)
        embed.add_field(name="📅 MAU", value=str(mau), inline=True)
        embed.add_field(name="📈 DAU/MAU", value=ratio, inline=True)
        embed.add_field(name="🤖 Boti", value=str(bots), inline=True)
        embed.add_field(name="🧑‍🤝‍🧑 Lidé", value=str(humans), inline=True)
        embed.add_field(name="💡 Online", value=str(online), inline=True)
        embed.add_field(name="💬 Text kanály", value=str(text_channels), inline=True)
        embed.add_field(name="🔊 Voice kanály", value=str(voice_channels), inline=True)
        embed.add_field(name="🏷️ Role", value=str(roles), inline=True)

        footer_text = (
            f"Report generován automaticky • Pokryto: {start_prev.strftime('%d.%m.%Y')} — "
            f"{end_prev.strftime('%d.%m.%Y')} • Vygenerováno: {generated_str} (Europe/Prague)"
        )
        embed.set_footer(text=footer_text)

        channel = target_channel or (guild.get_channel(self.report_channel_id) if self.report_channel_id else None)
        if channel:
            await channel.send(embed=embed)
        if ctx:
            await ctx.send("✅ Report byl odeslán!")

        return embed  # umožní použít v /report preview

    # ====== PŮVODNÍ PREFIX PŘÍKAZ (ZACHOVÁN) ======
    @commands.command(name='report', help='Okamžitě odešle serverový report')
    async def report_command(self, ctx: commands.Context):
        if ctx.guild and ctx.guild.id == self.guild_id:
            await self.send_report(ctx)
        else:
            await ctx.send("🔒 Tento příkaz nelze použít mimo hlavní server.")

    # ====== NOVÉ: SLASH /report ======
    report_group = app_commands.Group(name="report", description="Serverové měsíční reporty")

    @report_group.command(name="run", description="Odešle report do určeného kanálu (výchozí konfigurovaný).")
    @app_commands.describe(
        year="Rok (např. 2025). Když prázdné, použije se předchozí měsíc.",
        month="Měsíc 1–12. Když prázdné, použije se předchozí měsíc.",
        channel="Cílový kanál (volitelné; jinak REPORT_CHANNEL_ID/CONSOLE_CHANNEL_ID).",
        hide="Odpověď jen pro tebe (ephemeral potvrzení)."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_run(
        self,
        itx: Interaction,
        year: int | None = None,
        month: app_commands.Range[int, 1, 12] | None = None,
        channel: discord.TextChannel | None = None,
        hide: bool = True
    ):
        await itx.response.defer(ephemeral=hide)
        if not itx.guild or itx.guild.id != self.guild_id:
            return await itx.followup.send("🔒 Tento příkaz lze použít jen na hlavním serveru.", ephemeral=True)

        embed = await self.send_report(
            ctx=None,
            year=year,
            month=month,
            target_channel=channel
        )
        if embed is None:
            return await itx.followup.send("❌ Nepodařilo se vygenerovat report.", ephemeral=True)
        await itx.followup.send("✅ Report odeslán.", ephemeral=hide)

    @report_group.command(name="preview", description="Zobrazí náhled reportu (bez odeslání do kanálu).")
    @app_commands.describe(
        year="Rok (např. 2025).",
        month="Měsíc 1–12.",
        hide="Ephemeral náhled (doporučeno)."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_preview(
        self,
        itx: Interaction,
        year: int | None = None,
        month: app_commands.Range[int, 1, 12] | None = None,
        hide: bool = True
    ):
        await itx.response.defer(ephemeral=hide)
        if not itx.guild or itx.guild.id != self.guild_id:
            return await itx.followup.send("🔒 Tento příkaz lze použít jen na hlavním serveru.", ephemeral=True)

        embed = await self.send_report(ctx=None, year=year, month=month, target_channel=None)
        if embed is None:
            return await itx.followup.send("❌ Náhled se nepodařilo vytvořit.", ephemeral=True)

        # poslat jen náhled volajícímu
        await itx.followup.send(embed=embed, ephemeral=hide)

    @report_group.command(name="reload", description="Znovu načte uložená data (member_counts, active_users).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_reload(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        self.load_member_data()
        self.load_active_data()
        await itx.followup.send("🔄 Data znovu načtena.", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerReport(bot))
