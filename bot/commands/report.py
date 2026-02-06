

from __future__ import annotations

import discord
from discord.ext import commands, tasks
from discord import app_commands, Interaction
import json
from config import config
from datetime import datetime, date, timedelta, time, timezone
import os
import calendar
from typing import Optional, Union


try:
    from zoneinfo import ZoneInfo
    PRAGUE_TZ = ZoneInfo("Europe/Prague")
except Exception:
    
    PRAGUE_TZ = timezone(timedelta(hours=1))


CZECH_MONTHS = [
    "leden", "únor", "březen", "duben", "květen", "červen",
    "červenec", "srpen", "září", "říjen", "listopad", "prosinec"
]

class ServerReport(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        
        self.data_folder = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(self.data_folder, exist_ok=True)

        self.member_file = os.path.join(self.data_folder, 'member_counts.json')
        self.active_file = os.path.join(self.data_folder, 'active_users.json')

        self.guild_id = config.GUILD_ID
        self.report_channel_id = getattr(config, "REPORT_CHANNEL_ID", getattr(config, "CONSOLE_CHANNEL_ID", None))

        self.member_data = {}
        self.active_data = {}
        
        
        self._data_dirty = False

        self.load_member_data()
        self.load_active_data()
        
        
        self.daily_report_check.start()
        self.periodic_save.start()

    def cog_unload(self):
        """Při vypnutí/reloadu cogu vynutit uložení."""
        self.daily_report_check.cancel()
        self.periodic_save.cancel()
        self.save_all_data()

    
    def load_member_data(self):
        try:
            with open(self.member_file, 'r', encoding='utf-8') as f:
                self.member_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            self.member_data = {}

    def load_active_data(self):
        try:
            with open(self.active_file, 'r', encoding='utf-8') as f:
                
                data = json.load(f)
                self.active_data = {k: set(v) for k, v in data.items()}
        except (FileNotFoundError, json.JSONDecodeError):
            self.active_data = {}

    def save_member_data(self):
        with open(self.member_file, 'w', encoding='utf-8') as f:
            json.dump(self.member_data, f, ensure_ascii=False, indent=4)

    def save_active_data(self):
        
        serializable = {k: list(v) for k, v in self.active_data.items()}
        with open(self.active_file, 'w', encoding='utf-8') as f:
            json.dump(serializable, f, ensure_ascii=False, indent=4)
            
    def save_all_data(self):
        """Uloží všechna data, pokud jsou změněna."""
        if self._data_dirty:
            print("💾 Ukládám report data...")
            self.save_member_data()
            self.save_active_data()
            self._data_dirty = False

    @tasks.loop(minutes=5)
    async def periodic_save(self):
        """Pravidelné ukládání dat (každých 5 minut), aby se neukládalo při každé zprávě."""
        self.save_all_data()

    
    
    def _get_today_prague_str(self) -> str:
        """Vrátí dnešní datum v ISO formátu (YYYY-MM-DD) podle Europe/Prague."""
        return datetime.now(PRAGUE_TZ).date().isoformat()

    def _get_month_prague_str(self) -> str:
        """Vrátí aktuální měsíc (YYYY-MM) podle Europe/Prague."""
        return datetime.now(PRAGUE_TZ).strftime('%Y-%m')

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.guild.id != self.guild_id or message.author.bot:
            return

        today = self._get_today_prague_str()
        
        
        if today not in self.active_data:
            self.active_data[today] = set()

        if message.author.id not in self.active_data[today]:
            self.active_data[today].add(message.author.id)
            self._data_dirty = True
            

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.guild.id != self.guild_id:
            return
        
        month_key = self._get_month_prague_str()
        self.member_data.setdefault(month_key, {'joins': 0, 'leaves': 0})
        self.member_data[month_key]['joins'] += 1
        self._data_dirty = True

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.guild.id != self.guild_id:
            return

        month_key = self._get_month_prague_str()
        self.member_data.setdefault(month_key, {'joins': 0, 'leaves': 0})
        self.member_data[month_key]['leaves'] += 1
        self._data_dirty = True

    
    
    @tasks.loop(time=time(hour=0, minute=5, tzinfo=timezone.utc)) 
    
    
    
    async def daily_report_check(self):
        
        now_prague = datetime.now(PRAGUE_TZ)
        
        
        
        
        if now_prague.day != 1:
            return
            
        print(f"🕐 Spouštím měsíční report [automaticky]: {now_prague}")
        await self.send_report(send_message=True)

    @daily_report_check.before_loop
    async def before_daily_report(self):
        await self.bot.wait_until_ready()

    

    def _period_from_year_month(self, year: int | None, month: int | None):
        """
        Vrátí rozsah data pro report (start, end) a popisky.
        Vždy pracuje s daty relativně k PRAGUE_TZ pro 'aktuálnost',
        ale vrací date objekty.
        """
        now = datetime.now(PRAGUE_TZ)
        
        if year and month:
            
            start_date = date(year, month, 1)
            
            next_month = start_date.replace(day=28) + timedelta(days=4)
            end_date = next_month - timedelta(days=next_month.day)
        else:
            
            
            first_this_month = now.date().replace(day=1)
            
            end_date = first_this_month - timedelta(days=1)
            
            start_date = end_date.replace(day=1)

        month_idx = start_date.month - 1
        return start_date, end_date, CZECH_MONTHS[month_idx].capitalize(), start_date.year, now

    async def send_report(
        self,
        ctx: commands.Context | None = None,
        *,
        year: int | None = None,
        month: int | None = None,
        target_channel: discord.TextChannel | None = None,
        send_message: bool = True
    ) -> discord.Embed | None:
        """
        Generuje a případně odešle report.
        Arg: send_message=False slouží pro preview (náhled bez odeslání).
        """
        start_prev, end_prev, month_name_cz, title_year, now = self._period_from_year_month(year, month)
        
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            if ctx: await ctx.send("❌ Nelze najít cílový server.")
            return None

        
        month_key = start_prev.strftime('%Y-%m')
        stats = self.member_data.get(month_key, {'joins': 0, 'leaves': 0})
        new_members = stats.get('joins', 0)
        leaves = stats.get('leaves', 0)
        current_total = guild.member_count  

        
        daily_counts = []
        mau_set = set()
        
        
        
        delta = end_prev - start_prev
        days_in_month = delta.days + 1  
        
        for i in range(days_in_month):
            check_date = start_prev + timedelta(days=i)
            day_str = check_date.isoformat()
            
            users_that_day = self.active_data.get(day_str, set())
            count = len(users_that_day)
            
            
            
            daily_counts.append(count)
            mau_set.update(users_that_day)

        
        
        avg_dau = sum(daily_counts) / days_in_month if days_in_month > 0 else 0
        mau = len(mau_set)
        
        ratio = f"{(avg_dau / mau * 100):.2f}%" if mau > 0 else 'N/A'

        
        bots = sum(1 for m in guild.members if m.bot)
        humans = current_total - bots
        online = sum(1 for m in guild.members if m.status != discord.Status.offline)
        text_channels = len(guild.text_channels)
        voice_channels = len(guild.voice_channels)
        roles = len(guild.roles)

        
        embed_title = f"Server Report — {month_name_cz} {title_year}"
        generated_str = now.strftime('%d.%m.%Y %H:%M')

        
        
        embed = discord.Embed(
            title=embed_title,
            timestamp=datetime.now(timezone.utc),
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
            f"Report generate automatically • Period: {start_prev.strftime('%d.%m.%Y')} — "
            f"{end_prev.strftime('%d.%m.%Y')} • Generated: {generated_str} (Europe/Prague)"
        )
        embed.set_footer(text=footer_text)

        
        if send_message:
            channel = target_channel or (guild.get_channel(self.report_channel_id) if self.report_channel_id else None)
            if channel:
                await channel.send(embed=embed)
            elif ctx:
                await ctx.send("⚠ Nebyl nalezen kanál pro odeslání reportu (nastavte REPORT_CHANNEL_ID).", delete_after=10)

        return embed

    
    report_group = app_commands.Group(name="report", description="Serverové měsíční reporty")

    @report_group.command(name="run", description="Odešle report do určeného kanálu (nebo default).")
    @app_commands.describe(
        year="Rok (např. 2025). Default: aktuální rok.",
        month="Měsíc 1–12. Default: minulý měsíc.",
        channel="Cílový kanál . Default: nakonfigurovaný REPORT_CHANNEL_ID.",
        hide="Skrýt odpověď bota (ephemeral)."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_run(
        self,
        itx: Interaction,
        year: Optional[int] = None,
        month: Optional[app_commands.Range[int, 1, 12]] = None,
        channel: Optional[discord.TextChannel] = None,
        hide: bool = True
    ):
        await itx.response.defer(ephemeral=hide)
        if not itx.guild or itx.guild.id != self.guild_id:
            return await itx.followup.send("🔒 Tento příkaz lze použít jen na hlavním serveru.", ephemeral=True)

        embed = await self.send_report(
            ctx=None,
            year=year,
            month=month,
            target_channel=channel,
            send_message=True  
        )
        
        if embed:
            await itx.followup.send("✅ Report byl úspěšně vygenerován a odeslán.", ephemeral=hide)
        else:
            await itx.followup.send("❌ Nepodařilo se vygenerovat report (chyba serveru nebo konfigurace).", ephemeral=True)

    @report_group.command(name="preview", description="Zobrazí pouze náhled reportu (NIC NEODESÍLÁ do kanálů).")
    @app_commands.describe(
        year="Rok (např. 2025).",
        month="Měsíc 1–12.",
        hide="Skrýt náhled jen pro tebe (doporučeno True)."
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_preview(
        self,
        itx: Interaction,
        year: Optional[int] = None,
        month: Optional[app_commands.Range[int, 1, 12]] = None,
        hide: bool = True
    ):
        await itx.response.defer(ephemeral=hide)
        if not itx.guild or itx.guild.id != self.guild_id:
            return await itx.followup.send("🔒 Tento příkaz lze použít jen na hlavním serveru.", ephemeral=True)

        
        embed = await self.send_report(
            ctx=None, 
            year=year, 
            month=month, 
            target_channel=None,
            send_message=False 
        )
        
        if embed:
            await itx.followup.send(content="**NÁHLED REPORTU (nebyl odeslán):**", embed=embed, ephemeral=hide)
        else:
            await itx.followup.send("❌ Chyba při generování náhledu.", ephemeral=True)

    @report_group.command(name="reload", description="Vynutí znovu-načtení dat z disku a uložení cache.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def report_reload(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        self.save_all_data() 
        self.load_member_data() 
        self.load_active_data()
        await itx.followup.send("🔄 Data uložena a znovu načtena z disku.", ephemeral=True)

    @commands.command(name='report')
    async def report_command_prefix(self, ctx: commands.Context):
        """Legacy prefix command"""
        if ctx.guild and ctx.guild.id == self.guild_id:
            await self.send_report(ctx, send_message=True)
        else:
            await ctx.send("🔒 Mimo hlavní server nelze použít.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerReport(bot))
