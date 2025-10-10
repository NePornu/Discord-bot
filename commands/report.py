import discord
from discord.ext import commands, tasks
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

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.guild and message.guild.id == self.guild_id and not message.author.bot:
            # doporučeno používat UTC pro konzistenci, ale zatím zachováno local date
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

    async def send_report(self, ctx: commands.Context = None):
        now = datetime.utcnow().replace(tzinfo=timezone.utc)
        guild = self.bot.get_guild(self.guild_id)
        if not guild:
            return

        current_total = guild.member_count

        last_month_last_day = now.replace(day=1) - timedelta(days=1)
        start_prev = last_month_last_day.replace(day=1).date()
        end_prev = last_month_last_day.date()
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

        this_month_key = now.strftime('%Y-%m')
        self.member_data.setdefault(this_month_key, {'joins': 0, 'leaves': 0})
        self.save_member_data()

        # titulka: český název měsíce za který jsou data (start_prev.month)
        month_idx = start_prev.month - 1
        month_name_cz = CZECH_MONTHS[month_idx].capitalize()
        embed_title = f"Server Report — {month_name_cz} {start_prev.year}"

        # čas vygenerování v Prague tz (fallback když zoneinfo chybí)
        try:
            prague_now = now.astimezone(PRAGUE_TZ)
        except Exception:
            # pokud PRAGUE_TZ je timezone object z fallbacku, použij replace
            prague_now = now.astimezone(PRAGUE_TZ) if hasattr(now, 'astimezone') else now

        generated_str = prague_now.strftime('%d.%m.%Y %H:%M')

        embed = discord.Embed(
            title=embed_title,
            timestamp=now,  # discord timestamp (UTC) — discord zobrazí hezky podle uživatele
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

        # footer: pokryté období + přesný čas vygenerování (Europe/Prague)
        footer_text = f"Report generován automaticky • Pokryto: {start_prev.strftime('%d.%m.%Y')} — {end_prev.strftime('%d.%m.%Y')} • Vygenerováno: {generated_str} (Europe/Prague)"
        embed.set_footer(text=footer_text)

        channel = guild.get_channel(self.report_channel_id)
        if channel:
            await channel.send(embed=embed)
        if ctx:
            await ctx.send("✅ Report byl odeslán!")

    @commands.command(name='report', help='Okamžitě odešle serverový report')
    async def report_command(self, ctx: commands.Context):
        if ctx.guild and ctx.guild.id == self.guild_id:
            await self.send_report(ctx)
        else:
            await ctx.send("🔒 Tento příkaz nelze použít mimo hlavní server.")

async def setup(bot: commands.Bot):
    await bot.add_cog(ServerReport(bot))
