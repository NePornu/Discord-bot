import discord
from discord.ext import commands
from discord import app_commands
import aiosqlite
import aiohttp
import os
import asyncio
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

# =====================================================================
#   CONFIG & CONSTANTS
# =====================================================================
DB_DIR = "data"
DB_FILE = "calendar.db"
DB_PATH = os.path.join(DB_DIR, DB_FILE)
TZ = ZoneInfo("Europe/Prague")

# =====================================================================
#   HELPERS
# =====================================================================
def parse_date(value: str) -> date:
    v = value.strip()
    if "." in v:
        return datetime.strptime(v, "%d.%m.%Y").date()
    return datetime.strptime(v, "%Y-%m-%d").date()

async def fetch_image(url: str) -> bytes:
    if not url: return None
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as r:
                if r.status == 200:
                    return await r.read()
    except:
        return None
    return None

def create_progress_bar(count: int, max_count: int, length: int = 10) -> str:
    if max_count == 0: return "░" * length
    filled = int((count / max_count) * length)
    return "█" * filled + "░" * (length - filled)

# =====================================================================
#   DATABASE LAYER
# =====================================================================
class CalendarDB:
    @staticmethod
    async def init():
        if not os.path.exists(DB_DIR):
            os.makedirs(DB_DIR)
            
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("""
            CREATE TABLE IF NOT EXISTS calendars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER,
                channel_id INTEGER,
                name TEXT,
                start_date TEXT,
                num_days INTEGER,
                test_mode INTEGER DEFAULT 0
            )""")
            await db.execute("""
            CREATE TABLE IF NOT EXISTS days (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                calendar_id INTEGER,
                day INTEGER,
                title TEXT,
                emoji TEXT,
                btn_label TEXT,
                btn_emoji TEXT,
                reward_text TEXT,
                reward_link TEXT,
                reward_image TEXT,
                reward_role TEXT,
                UNIQUE(calendar_id, day)
            )""")
            await db.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                calendar_id INTEGER,
                day INTEGER,
                user TEXT,
                UNIQUE(calendar_id, day, user)
            )""")
            await db.commit()

    @staticmethod
    async def create_calendar(channel_id: int, name: str, start_date: str, num_days: int) -> int:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute("""
                INSERT INTO calendars (message_id, channel_id, name, start_date, num_days)
                VALUES (0, ?, ?, ?, ?)
            """, (channel_id, name, start_date, num_days))
            cid = cursor.lastrowid
            
            for i in range(1, num_days + 1):
                await db.execute("""
                    INSERT INTO days (calendar_id, day, title, emoji, btn_label, btn_emoji)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (cid, i, f"Den {i}", "🎁", f"Den {i}", "🎄"))
            await db.commit()
            return cid

    @staticmethod
    async def update_message_id(cid: int, mid: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE calendars SET message_id=? WHERE id=?", (mid, cid))
            await db.commit()

    @staticmethod
    async def update_day(cid: int, day: int, data: dict):
        fields = [f"{k}=?" for k in data.keys()]
        values = list(data.values()) + [cid, day]
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(f"UPDATE days SET {', '.join(fields)} WHERE calendar_id=? AND day=?", tuple(values))
            await db.commit()

    @staticmethod
    async def get_calendar(cid: int):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM calendars WHERE id=?", (cid,)) as cursor:
                return await cursor.fetchone()

    @staticmethod
    async def get_day(cid: int, day: int):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM days WHERE calendar_id=? AND day=?", (cid, day)) as cursor:
                return await cursor.fetchone()

    @staticmethod
    async def list_days(cid: int):
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT day, btn_label, btn_emoji FROM days WHERE calendar_id=? ORDER BY day", (cid,)) as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def save_claim(cid: int, day: int, user_id: str):
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute("INSERT INTO claims (calendar_id, day, user) VALUES (?, ?, ?)", (cid, day, user_id))
                await db.commit()
                return True
            except aiosqlite.IntegrityError:
                return False

    @staticmethod
    async def is_claimed(cid: int, day: int, user_id: str) -> bool:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT 1 FROM claims WHERE calendar_id=? AND day=? AND user=?", (cid, day, user_id)) as cursor:
                return await cursor.fetchone() is not None

    @staticmethod
    async def get_active_calendars():
        async with aiosqlite.connect(DB_PATH) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM calendars ORDER BY id DESC") as cursor:
                return await cursor.fetchall()

    @staticmethod
    async def delete_calendar(cid: int):
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM days WHERE calendar_id=?", (cid,))
            await db.execute("DELETE FROM claims WHERE calendar_id=?", (cid,))
            await db.execute("DELETE FROM calendars WHERE id=?", (cid,))
            await db.commit()

    @staticmethod
    async def get_stats(cid: int):
        async with aiosqlite.connect(DB_PATH) as db:
            # Total unique users
            cursor = await db.execute("SELECT COUNT(DISTINCT user) FROM claims WHERE calendar_id=?", (cid,))
            res = await cursor.fetchone()
            total_users = res[0] if res else 0
            
            # Claims per day
            cursor = await db.execute("SELECT day, COUNT(*) FROM claims WHERE calendar_id=? GROUP BY day ORDER BY day", (cid,))
            days_stats = await cursor.fetchall() # list of (day, count)
            
            return total_users, days_stats

# =====================================================================
#   PUBLIC VIEW (Co vidí uživatelé)
# =====================================================================
class PublicDayButton(discord.ui.Button):
    def __init__(self, cid: int, day: int, label: str, emoji: str):
        if not emoji or emoji == "None" or emoji == "": emoji = None
        super().__init__(style=discord.ButtonStyle.secondary, label=label, emoji=emoji, custom_id=f"pub_cal:{cid}:{day}")
        self.cid = cid
        self.day = day

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = interaction.user
        
        cal = await CalendarDB.get_calendar(self.cid)
        if not cal: return await interaction.followup.send("❌ Kalendář již neexistuje.", ephemeral=True)
            
        day_data = await CalendarDB.get_day(self.cid, self.day)
        if not day_data: return await interaction.followup.send("❌ Data dne nenalezena.", ephemeral=True)

        try:
            start_date = datetime.strptime(cal['start_date'], "%Y-%m-%d").date()
        except:
            start_date = datetime.strptime(cal['start_date'], "%d.%m.%Y").date()
            
        target_day = start_date + timedelta(days=self.day - 1)
        now = datetime.now(TZ).date()

        if not cal['test_mode'] and now < target_day:
            diff = (target_day - now).days
            return await interaction.followup.send(f"⏳ Otevření je možné až **{target_day.strftime('%d.%m.%Y')}** (za {diff} dní).", ephemeral=True)

        if await CalendarDB.is_claimed(self.cid, self.day, str(user.id)):
            return await interaction.followup.send("❌ Toto okénko jsi už otevřel/a!", ephemeral=True)

        if await CalendarDB.save_claim(self.cid, self.day, str(user.id)):
            content = f"🎄 **Den {self.day}: {day_data['title']}**\n\n"
            if day_data['reward_text']: content += f"{day_data['reward_text']}\n"
            if day_data['reward_link']: content += f"🔗 {day_data['reward_link']}\n"
            
            if day_data['reward_role']:
                try:
                    role = interaction.guild.get_role(int(day_data['reward_role']))
                    if role:
                        await user.add_roles(role)
                        content += f"\n✅ Získal jsi roli **{role.name}**"
                except:
                    content += "\n⚠ Nepodařilo se přidat roli."

            try:
                img_data = await fetch_image(day_data['reward_image'])
                file = discord.File(fp=img_data, filename="reward.png") if img_data else None
                await user.send(content, file=file)
                await interaction.followup.send("🎁 Odměna odeslána do DM!", ephemeral=True)
            except:
                await interaction.followup.send(f"⚠ Máš zablokované DM. Tady je odměna:\n\n{content}", ephemeral=True)

class PublicCalendarView(discord.ui.View):
    def __init__(self, cid: int, days_list: list):
        super().__init__(timeout=None)
        for row in days_list:
            self.add_item(PublicDayButton(cid, row['day'], row['btn_label'], row['btn_emoji']))

# =====================================================================
#   ADMIN MODALS (Formuláře)
# =====================================================================
class EditContentModal(discord.ui.Modal):
    def __init__(self, parent_view, cid, day, data):
        super().__init__(title=f"Obsah Dne {day}")
        self.parent_view = parent_view
        self.cid = cid
        self.day = day
        self.t = discord.ui.TextInput(label="Nadpis v DM", default=data['title'], max_length=100)
        self.rt = discord.ui.TextInput(label="Text odměny", default=data['reward_text'] or "", style=discord.TextStyle.paragraph, required=False)
        self.rl = discord.ui.TextInput(label="Odkaz (URL)", default=data['reward_link'] or "", required=False)
        self.rr = discord.ui.TextInput(label="ID Role (nepovinné)", default=data['reward_role'] or "", required=False)
        self.add_item(self.t)
        self.add_item(self.rt)
        self.add_item(self.rl)
        self.add_item(self.rr)

    async def on_submit(self, interaction: discord.Interaction):
        # DŮLEŽITÉ: Defer hned na začátku, aby nedošlo k chybě
        await interaction.response.defer() 
        await CalendarDB.update_day(self.cid, self.day, {
            "title": self.t.value, "reward_text": self.rt.value,
            "reward_link": self.rl.value, "reward_role": self.rr.value
        })
        await self.parent_view.refresh_dashboard(interaction)

class EditButtonModal(discord.ui.Modal):
    def __init__(self, parent_view, cid, day, data):
        super().__init__(title=f"Vzhled Dne {day}")
        self.parent_view = parent_view
        self.cid = cid
        self.day = day
        self.bl = discord.ui.TextInput(label="Nápis na tlačítku", default=data['btn_label'], max_length=50)
        self.be = discord.ui.TextInput(label="Emoji", default=data['btn_emoji'] or "", required=False)
        self.add_item(self.bl)
        self.add_item(self.be)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await CalendarDB.update_day(self.cid, self.day, {"btn_label": self.bl.value, "btn_emoji": self.be.value})
        await self.parent_view.refresh_dashboard(interaction)

class EditImageModal(discord.ui.Modal):
    def __init__(self, parent_view, cid, day, data):
        super().__init__(title=f"Obrázek Dne {day}")
        self.parent_view = parent_view
        self.cid = cid
        self.day = day
        self.ri = discord.ui.TextInput(label="URL Obrázku", default=data['reward_image'] or "", required=False)
        self.add_item(self.ri)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await CalendarDB.update_day(self.cid, self.day, {"reward_image": self.ri.value})
        await self.parent_view.refresh_dashboard(interaction)

class NewCalendarModal(discord.ui.Modal, title="Nový Kalendář"):
    name = discord.ui.TextInput(label="Název", placeholder="Vánoce 2025")
    start = discord.ui.TextInput(label="Start (DD.MM.YYYY)", placeholder="01.12.2025")
    days = discord.ui.TextInput(label="Počet dní", default="24")

    async def on_submit(self, interaction: discord.Interaction):
        try:
            date_obj = parse_date(self.start.value)
            num = int(self.days.value)
        except:
            return await interaction.response.send_message("❌ Chybný formát data nebo čísla.", ephemeral=True)

        await interaction.response.defer(ephemeral=True)
        cid = await CalendarDB.create_calendar(interaction.channel_id, self.name.value, date_obj.strftime("%Y-%m-%d"), num)
        days = await CalendarDB.list_days(cid)
        view = PublicCalendarView(cid, days)
        embed = discord.Embed(title=f"🗓 {self.name.value}", description=f"Start: **{date_obj.strftime('%d.%m.%Y')}**", color=discord.Color.gold())
        
        msg = await interaction.channel.send(embed=embed, view=view)
        await CalendarDB.update_message_id(cid, msg.id)
        await interaction.followup.send(f"✅ Vytvořeno (ID: {cid}). Spusť `/calendar_admin` pro úpravy.")

# =====================================================================
#   DELETE CONFIRMATION
# =====================================================================
class DeleteConfirmView(discord.ui.View):
    def __init__(self, cid, cal_name, bot):
        super().__init__(timeout=60)
        self.cid = cid
        self.cal_name = cal_name
        self.bot = bot

    @discord.ui.button(label="POTVRDIT SMAZÁNÍ", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        # 1. Get calendar info to find message
        cal = await CalendarDB.get_calendar(self.cid)
        
        # 2. Delete from DB
        await CalendarDB.delete_calendar(self.cid)
        
        # 3. Try to delete message
        if cal:
            channel = self.bot.get_channel(cal['channel_id'])
            if channel:
                try:
                    msg = await channel.fetch_message(cal['message_id'])
                    await msg.delete()
                except:
                    pass

        embed = discord.Embed(title="✅ Smazáno", description=f"Kalendář **{self.cal_name}** byl nenávratně smazán.", color=discord.Color.red())
        await interaction.edit_original_response(embed=embed, view=None)

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Operace zrušena.", ephemeral=True)
        await interaction.message.delete()

# =====================================================================
#   ADMIN DASHBOARD (OPRAVENÁ LOGIKA)
# =====================================================================
class AdminDashboardView(discord.ui.View):
    def __init__(self, bot):
        super().__init__(timeout=None) # Timeout None = panel nezmizí tak rychle
        self.bot = bot
        self.selected_cid = None
        self.selected_day = None
        self.cal_data = None
        self.showing_stats = False

    # --- ROW 0: Calendar Select ---
    @discord.ui.select(placeholder="1. Vyber kalendář...", min_values=1, max_values=1, row=0)
    async def select_calendar(self, interaction: discord.Interaction, select: discord.ui.Select):
        # Okamžitá reakce pro uživatele
        await interaction.response.defer()
        
        try:
            val = int(select.values[0])
            self.selected_cid = val
            self.cal_data = await CalendarDB.get_calendar(self.selected_cid)
            
            # Reset vnořených stavů
            self.selected_day = None 
            self.showing_stats = False
            
            await self.update_view(interaction)
        except Exception as e:
            await interaction.followup.send(f"Chyba při výběru kalendáře: {e}", ephemeral=True)

    # --- ROW 2: Buttons ---
    @discord.ui.button(label="Obsah", emoji="📝", style=discord.ButtonStyle.primary, row=2, disabled=True)
    async def btn_edit_content(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await CalendarDB.get_day(self.selected_cid, self.selected_day)
        await interaction.response.send_modal(EditContentModal(self, self.selected_cid, self.selected_day, data))

    @discord.ui.button(label="Tlačítko", emoji="🎨", style=discord.ButtonStyle.secondary, row=2, disabled=True)
    async def btn_edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await CalendarDB.get_day(self.selected_cid, self.selected_day)
        await interaction.response.send_modal(EditButtonModal(self, self.selected_cid, self.selected_day, data))
        
    @discord.ui.button(label="Obrázek", emoji="🖼", style=discord.ButtonStyle.secondary, row=2, disabled=True)
    async def btn_edit_image(self, interaction: discord.Interaction, button: discord.ui.Button):
        data = await CalendarDB.get_day(self.selected_cid, self.selected_day)
        await interaction.response.send_modal(EditImageModal(self, self.selected_cid, self.selected_day, data))

    # --- ROW 3: Actions ---
    @discord.ui.button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.success, row=3, disabled=True)
    async def btn_refresh_public(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        channel = self.bot.get_channel(self.cal_data['channel_id'])
        if channel:
            try:
                msg = await channel.fetch_message(self.cal_data['message_id'])
                days = await CalendarDB.list_days(self.selected_cid)
                embed = discord.Embed(title=f"🗓 {self.cal_data['name']}", description=f"Start: **{parse_date(self.cal_data['start_date']).strftime('%d.%m.%Y')}**", color=discord.Color.gold())
                await msg.edit(embed=embed, view=PublicCalendarView(self.selected_cid, days))
                await interaction.followup.send("✅ Veřejná zpráva aktualizována.", ephemeral=True)
            except:
                await interaction.followup.send("❌ Zpráva nenalezena.", ephemeral=True)

    @discord.ui.button(label="Statistiky", emoji="📊", style=discord.ButtonStyle.secondary, row=3, disabled=True)
    async def btn_stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        self.showing_stats = not self.showing_stats # Toggle
        await self.update_view(interaction)

    @discord.ui.button(label="Smazat", emoji="🗑", style=discord.ButtonStyle.danger, row=3, disabled=True)
    async def btn_delete(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚠ POZOR", 
            description=f"Opravdu chceš smazat kalendář **{self.cal_data['name']}**?\nTato akce je nevratná a smaže všechna data i veřejnou zprávu.",
            color=discord.Color.red()
        )
        await interaction.response.send_message(embed=embed, view=DeleteConfirmView(self.selected_cid, self.cal_data['name'], self.bot), ephemeral=True)

    # --- Metody pro update UI ---
    async def refresh_dashboard(self, interaction: discord.Interaction):
        # Tato metoda je volána z Modalu, který už udělal defer/response
        # Proto používáme edit_original_response
        await self.update_view(interaction, use_followup=True)

    async def update_view(self, interaction: discord.Interaction, use_followup=False):
        # 1. Nastavit stavy tlačítek
        for child in self.children:
            if isinstance(child, discord.ui.Button):
                if child.emoji.name in ["📝", "🎨", "🖼"]:
                    child.disabled = self.selected_day is None
                else:
                    child.disabled = self.selected_cid is None

        # 2. Vyčistit starý Select pro dny
        # OPRAVA: self.children je read-only. Musíme použít remove_item.
        items_to_remove = [c for c in self.children if isinstance(c, discord.ui.Select) and c.row == 1]
        for item in items_to_remove:
            self.remove_item(item)
        
        # 3. Přidat Select pro dny, pokud je vybrán kalendář
        if self.selected_cid:
            num_days = self.cal_data['num_days']
            options = []
            # Omezení na 25 dní kvůli limitu Discordu
            limit = min(num_days + 1, 26)
            for i in range(1, limit):
                is_sel = (i == self.selected_day)
                options.append(discord.SelectOption(label=f"Den {i}", value=str(i), default=is_sel))
            
            # Vytvoření dynamického selectu
            day_select = discord.ui.Select(placeholder="2. Vyber den...", options=options, min_values=1, max_values=1, row=1)
            
            # Callback pro výběr dne
            async def day_callback(inter: discord.Interaction):
                await inter.response.defer()
                self.selected_day = int(day_select.values[0])
                self.showing_stats = False
                await self.update_view(inter)
            
            day_select.callback = day_callback
            self.add_item(day_select)

        # 4. Sestavit Embed
        embed = discord.Embed(title="⚙ Správa Kalendáře", color=discord.Color.from_rgb(47, 49, 54))
        
        if not self.selected_cid:
            embed.description = "⬅ Začni výběrem kalendáře v menu nahoře."
        
        elif self.showing_stats:
            users, day_stats = await CalendarDB.get_stats(self.selected_cid)
            embed.title = f"📊 Statistiky: {self.cal_data['name']}"
            embed.color = discord.Color.blue()
            embed.add_field(name="Unikátní uživatelé", value=f"**{users}**", inline=False)
            
            stats_text = ""
            max_val = max((c for d, c in day_stats), default=0)
            
            for d, c in day_stats:
                bar = create_progress_bar(c, max_val, 12)
                stats_text += f"`{d:02d}` {bar} **{c}**\n"
            
            embed.add_field(name="Otevření po dnech", value=stats_text or "Zatím žádná data.", inline=False)

        elif self.selected_day:
            day_data = await CalendarDB.get_day(self.selected_cid, self.selected_day)
            embed.title = f"Editace: {self.cal_data['name']} / Den {self.selected_day}"
            embed.color = discord.Color.green()
            
            c_info = f"**Nadpis:** {day_data['title']}\n"
            c_info += f"**Text:** {day_data['reward_text'][:40] + '...' if day_data['reward_text'] else '❌'}\n"
            c_info += f"**Link:** {'✅' if day_data['reward_link'] else '❌'}\n"
            c_info += f"**Role:** `{day_data['reward_role']}`" if day_data['reward_role'] else "**Role:** ❌"
            embed.add_field(name="📝 Obsah", value=c_info, inline=True)
            
            v_info = f"**Label:** {day_data['btn_label']}\n"
            v_info += f"**Emoji:** {day_data['btn_emoji'] or '❌'}\n"
            v_info += f"**Obrázek:** {'✅' if day_data['reward_image'] else '❌'}"
            embed.add_field(name="🎨 Vzhled", value=v_info, inline=True)
            
        else:
            embed.description = f"**Vybrán:** {self.cal_data['name']} (ID: {self.cal_data['id']})\n\n👇 Vyber den pro úpravu obsahu.\n📊 Klikni na Statistiky pro přehled."

        # 5. Odeslání změn
        if use_followup:
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.edit_original_response(embed=embed, view=self)

# =====================================================================
#   MAIN COG
# =====================================================================
class AdventCalendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.loop.create_task(self.restore_views())

    async def restore_views(self):
        await self.bot.wait_until_ready()
        calendars = await CalendarDB.get_active_calendars()
        for cal in calendars:
            try:
                days = await CalendarDB.list_days(cal['id'])
                view = PublicCalendarView(cal['id'], days)
                self.bot.add_view(view, message_id=cal['message_id'])
            except: pass

    @app_commands.command(name="calendar_create", description="Vytvořit nový adventní kalendář")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_create(self, interaction: discord.Interaction):
        await interaction.response.send_modal(NewCalendarModal())

    @app_commands.command(name="calendar_admin", description="Otevřít správu kalendářů")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_admin(self, interaction: discord.Interaction):
        calendars = await CalendarDB.get_active_calendars()
        if not calendars:
            return await interaction.response.send_message("❌ Žádné kalendáře. Vytvoř první pomocí `/calendar_create`.", ephemeral=True)

        view = AdminDashboardView(self.bot)
        # Naplnění prvního selectu
        select = view.children[0]
        select.options = [discord.SelectOption(label=f"{c['name']} (ID:{c['id']})", value=str(c['id'])) for c in calendars[:25]]
        
        embed = discord.Embed(title="⚙ Calendar Admin", description="Načítám...", color=discord.Color.dark_grey())
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

async def setup(bot):
    await CalendarDB.init()
    await bot.add_cog(AdventCalendar(bot))