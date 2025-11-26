import discord
import os
import json
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import asyncio

# ============================================================
#   UNIVERSAL MULTI-CALENDAR COG — ADVANCED VERSION
#   Supports:
#   - multi-calendar
#   - monthly activation
#   - nth-day / weekly / daily broadcast
#   - full GUI configuration
# ============================================================

CALENDAR_ROOT = "calendar"


class UniversalCalendar(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.events = self.load_events()
        self.broadcast_cache = {}
        self.broadcast_loop.start()

    def cog_unload(self):
        self.broadcast_loop.cancel()

    # ============================================================
    #   FILESYSTEM HELPERS
    # ============================================================

    def load_events(self) -> Dict:
        """Loads all calendar configs."""
        if not os.path.exists(CALENDAR_ROOT):
            os.makedirs(CALENDAR_ROOT)

        events = {}
        for folder in os.listdir(CALENDAR_ROOT):
            full = f"{CALENDAR_ROOT}/{folder}"
            if not os.path.isdir(full):
                continue

            config = self._load_json(f"{full}/config.json", None)
            if config:
                events[folder] = config
        return events

    def _load_json(self, path: str, default):
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ Error loading JSON {path}: {e}")
        return default

    def _save_json(self, path: str, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving JSON {path}: {e}")

    # ============================================================
    #   EVENT GENERATION
    # ============================================================

    def generate_event_id(self) -> str:
        now = datetime.now()
        return f"event_{now.year}{now.month:02d}{now.day:02d}_{now.hour:02d}{now.minute:02d}{now.second:02d}"

    def generate_event_files(
        self,
        event_id: str,
        name: str,
        month: Optional[int],
        days: int,
        prefix: str,
        hour: int,
        minute: int,
        channel_id: Optional[int] = None
    ) -> Dict:

        folder = f"{CALENDAR_ROOT}/{event_id}"
        os.makedirs(folder, exist_ok=True)

        # ======================================================
        #   NEW CONFIG — full broadcast control
        # ======================================================
        config = {
            "event_name": name,
            "month": month,                       # aktivace otevření
            "total_days": days,

            "start_day": 1,                       # od kdy lze otevírat

            # ===============================
            # BROADCAST CONFIG
            # ===============================
            "broadcast_mode": "daily",            # daily | weekly | nth_day | off
            "broadcast_n": 1,                     # pro nth_day
            "broadcast_start_day": 1,
            "broadcast_end_day": None,

            "broadcast_hour": hour,
            "broadcast_minute": minute,
            "broadcast_channel_id": channel_id,

            "created_at": datetime.now().isoformat(),
            "active": True
        }

        self._save_json(f"{folder}/config.json", config)

        # ===============================
        # CONTENT
        # ===============================
        content = {}
        for d in range(1, days + 1):
            content[str(d)] = {
                "title": f"{prefix} {d}",
                "text": "Zatím prázdné. Úpravte v admin panelu.",
                "image": "",
                "roles": [],
                "emoji": "🎁"
            }
        self._save_json(f"{folder}/content.json", content)

        # Empty progress
        self._save_json(f"{folder}/progress.json", {})

        # Stats
        self._save_json(f"{folder}/stats.json", {
            "total_opens": 0,
            "unique_users": 0,
            "daily_opens": {}
        })

        return config

    # ============================================================
    #   EVENT LOADING / SAVING
    # ============================================================

    def load_event(self, event_id: str):
        folder = f"{CALENDAR_ROOT}/{event_id}"

        self.event_id = event_id
        self.event_folder = folder

        self.config = self._load_json(f"{folder}/config.json", {})
        self.content = self._load_json(f"{folder}/content.json", {})
        self.progress = self._load_json(f"{folder}/progress.json", {})
        self.stats = self._load_json(f"{folder}/stats.json", {
            "total_opens": 0,
            "unique_users": 0,
            "daily_opens": {}
        })

    def save_all(self):
        folder = self.event_folder
        self._save_json(f"{folder}/config.json", self.config)
        self._save_json(f"{folder}/content.json", self.content)
        self._save_json(f"{folder}/progress.json", self.progress)
        self._save_json(f"{folder}/stats.json", self.stats)
    # ============================================================
    #   SLASH COMMANDS
    # ============================================================

    @app_commands.command(
        name="calendar_new",
        description="Vytvoří nový univerzální kalendář."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_new(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CalendarNewModal(self))


    @app_commands.command(
        name="calendar_list",
        description="Zobrazí seznam všech kalendářů."
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_list(self, interaction: discord.Interaction):

        if not self.events:
            return await interaction.response.send_message(
                "📭 Žádné kalendáře nebyly vytvořeny.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📅 Všechny kalendáře",
            color=discord.Color.blurple()
        )

        for event_id, config in self.events.items():
            status = "🟢 Aktivní" if config.get("active", True) else "🔴 Vypnutý"

            embed.add_field(
                name=f"{config['event_name']} (`{event_id}`)",
                value=(
                    f"Status: {status}\n"
                    f"Dny: {config['total_days']}\n"
                    f"Aktivní měsíc: {config['month']}\n"
                    f"Broadcast: {config['broadcast_mode']} "
                    f"({config['broadcast_hour']:02d}:{config['broadcast_minute']:02d})"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(
        name="calendar_announce",
        description="Propaguje kalendář do kanálu (kdykoliv v roce)."
    )
    @app_commands.describe(event_id="ID kalendáře", channel="Kanál pro oznámení")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_announce(self, interaction: discord.Interaction,
                                event_id: str, channel: discord.TextChannel):
        if event_id not in self.events:
            return await interaction.response.send_message(
                "❌ Kalendář neexistuje.", ephemeral=True
            )

        config = self.events[event_id]

        await channel.send(
            f"📣 **{config['event_name']}**\n"
            f"Kalendář bude **aktivní v měsíci {config['month']}**.\n"
            f"Použij `/calendar_start {event_id}` až to začne!"
        )

        await interaction.response.send_message(
            "✔ Oznámení bylo odesláno.",
            ephemeral=True
        )


    @app_commands.command(
        name="calendar_start",
        description="Spustí kalendář pro uživatele."
    )
    @app_commands.describe(event_id="ID kalendáře", mode="live/test")
    async def calendar_start(self, interaction: discord.Interaction,
                             event_id: str, mode: str):

        if event_id not in self.events:
            return await interaction.response.send_message(
                "❌ Tento kalendář neexistuje.",
                ephemeral=True
            )

        self.load_event(event_id)
        uid = str(interaction.user.id)

        now = datetime.now()
        total = self.config["total_days"]

        mode = mode.lower()
        if mode not in ("live", "test"):
            return await interaction.response.send_message(
                "❌ Režim musí být `live` nebo `test`.",
                ephemeral=True
            )

        # ============ OMEZENÍ NA MĚSÍC ===============
        if mode == "live":
            if self.config["month"] is not None and self.config["month"] != now.month:
                return await interaction.response.send_message(
                    f"❌ Tento kalendář lze otevírat jen v měsíci **{self.config['month']}**.",
                    ephemeral=True
                )

            # ============ START DAY ⁠–⁠ NE DŘÍVE =============
            unlock_day = max(now.day, self.config.get("start_day", 1))
            max_day = min(unlock_day, total)

        else:
            max_day = total  # test mód vždy odemyká vše

        opened = self.progress.get(uid, [])

        embed = discord.Embed(
            title=f"📅 {self.config['event_name']}",
            description=(
                f"Režim: **{mode.upper()}**\n"
                f"Dostupné dny: **{max_day}/{total}**\n"
                f"Tvůj progres: **{len(opened)}** dnů"
            ),
            color=discord.Color.gold()
        )

        view = CalendarGridView(self, interaction.user, max_day, admin=False)

        await interaction.response.send_message(
            embed=embed,
            view=view
        )


    @app_commands.command(
        name="calendar_admin",
        description="Admin panel kalendáře."
    )
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_admin(self, interaction: discord.Interaction,
                             event_id: str):

        if event_id not in self.events:
            return await interaction.response.send_message(
                "❌ Kalendář nenalezen.",
                ephemeral=True
            )

        self.load_event(event_id)

        embed = discord.Embed(
            title=f"🛠️ Admin panel — {self.config['event_name']}",
            description=(
                f"ID: `{event_id}`\n"
                f"Dny: {self.config['total_days']}\n"
                f"Aktivní měsíc: {self.config['month']}\n"
                f"Broadcast: {self.config['broadcast_mode']} "
                f"({self.config['broadcast_hour']:02d}:{self.config['broadcast_minute']:02d})"
            ),
            color=discord.Color.red()
        )

        view = AdminControlView(self, event_id)

        await interaction.response.send_message(
            embed=embed,
            view=view,
            ephemeral=True
        )


    @app_commands.command(
        name="calendar_stats",
        description="Statistiky kalendáře."
    )
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_stats(self, interaction: discord.Interaction, event_id: str):

        if event_id not in self.events:
            return await interaction.response.send_message(
                "❌ Kalendář neexistuje.",
                ephemeral=True
            )

        self.load_event(event_id)
        progress = self.progress

        embed = discord.Embed(
            title=f"📊 Statistiky — {self.config['event_name']}",
            color=discord.Color.blue()
        )

        unique_users = len(progress)
        total_opens = sum(len(v) for v in progress.values())

        embed.add_field(
            name="Souhrn",
            value=(
                f"👥 Unikátních uživatelů: **{unique_users}**\n"
                f"📬 Celkem otevření: **{total_opens}**"
            ),
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(
        name="calendar_toggle",
        description="Zapne/vypne kalendář."
    )
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_toggle(self, interaction: discord.Interaction,
                              event_id: str):

        if event_id not in self.events:
            return await interaction.response.send_message("❌ Kalendář nenalezen.", ephemeral=True)

        self.load_event(event_id)

        self.config["active"] = not self.config.get("active", True)
        self.save_all()

        status = "🟢 Aktivní" if self.config["active"] else "🔴 Vypnutý"

        await interaction.response.send_message(
            f"Kalendář **{self.config['event_name']}** je nyní: **{status}**",
            ephemeral=True
        )
    # ============================================================
    #   CORE FUNCTIONALITY — OPENING DAYS
    # ============================================================

    async def open_day(self, interaction: discord.Interaction, user: discord.User, day: int):
        """Otevírá konkrétní den kalendáře pro uživatele."""

        uid = str(user.id)

        # Už otevřeno?
        if uid in self.progress and day in self.progress[uid]:
            return await interaction.response.send_message(
                "🔁 Tento den už máš otevřený.",
                ephemeral=True
            )

        # Den neexistuje?
        if str(day) not in self.content:
            return await interaction.response.send_message(
                "❌ Tento den nemá žádný obsah.",
                ephemeral=True
            )

        data = self.content[str(day)]

        # Zapis progres
        if uid not in self.progress:
            self.progress[uid] = []

        self.progress[uid].append(day)

        # Statistiky
        self.stats["total_opens"] = self.stats.get("total_opens", 0) + 1
        self.stats["unique_users"] = len(self.progress)
        self.stats["daily_opens"][str(day)] = (
            self.stats["daily_opens"].get(str(day), 0) + 1
        )

        self.save_all()

        # Embed pro DM (uživatel dostane odměnu tam)
        embed = discord.Embed(
            title=f"{data.get('emoji', '🎁')} {data['title']}",
            description=data['text'],
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )
        if data["image"]:
            embed.set_image(url=data["image"])

        embed.set_footer(text=f"Den {day}/{self.config['total_days']}")

        # Role
        roles_added = []
        if interaction.guild:
            member = interaction.guild.get_member(user.id)
            if member and data["roles"]:
                for rid in data["roles"]:
                    role = interaction.guild.get_role(int(rid))
                    if role and role not in member.roles:
                        try:
                            await member.add_roles(role)
                            roles_added.append(role.name)
                        except discord.Forbidden:
                            pass

        # Pošli odměnu do DM
        try:
            await user.send(embed=embed)

            message = "📬 Odměna byla poslána do tvých DM!"
            if roles_added:
                message += "\n🎭 Přidané role: " + ", ".join(roles_added)

            await interaction.response.send_message(message, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Nemůžu ti poslat DM – zkontroluj nastavení soukromí.",
                ephemeral=True
            )


    # ============================================================
    #   BROADCAST SYSTEM — DAILY / WEEKLY / NTH DAY
    # ============================================================

    @tasks.loop(minutes=1)
    async def broadcast_loop(self):
        """Každou minutu kontroluje, zda se má poslat broadcast."""
        now = datetime.now()
        cache_key = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}"

        # Zabraň opakovanému běhu
        if cache_key in self.broadcast_cache:
            return
        self.broadcast_cache[cache_key] = True

        # čistíme starý cache
        if len(self.broadcast_cache) > 200:
            self.broadcast_cache = {}

        # zpracuj každý event
        for event_id in list(self.events.keys()):
            try:
                await self._process_event_broadcast(event_id, now)
            except Exception as e:
                print(f"⚠️ Broadcast error ({event_id}): {e}")


    async def _process_event_broadcast(self, event_id: str, now: datetime):
        """Vyhodnocení broadcastu pro konkrétní kalendář."""

        folder = f"{CALENDAR_ROOT}/{event_id}"
        config = self._load_json(f"{folder}/config.json", {})
        content = self._load_json(f"{folder}/content.json", {})
        progress = self._load_json(f"{folder}/progress.json", {})

        # ===============================
        # Pokud je vypnutý → ignoruj
        # ===============================
        if not config.get("active", True):
            return

        # ===============================
        # Broadcast spouštíme jen v určený měsíc !!!
        # Mimo měsíc se ale může propagovat ručně.
        # ===============================
        month = config.get("month")
        if month is not None and month != now.month:
            return

        # ===============================
        # Správný čas H:M
        # ===============================
        if now.hour != config.get("broadcast_hour") or now.minute != config.get("broadcast_minute"):
            return

        # ===============================
        # Výpočet dne + rozsahy
        # ===============================
        day = now.day
        total_days = config.get("total_days", 24)

        if day > total_days:
            return

        # Omezující dny
        start_b = config.get("broadcast_start_day", 1)
        end_b = config.get("broadcast_end_day", None)

        if day < start_b:
            return
        if end_b is not None and day > end_b:
            return

        # ===============================
        # Broadcast opakování
        # ===============================
        mode = config.get("broadcast_mode", "daily")
        n_val = config.get("broadcast_n", 1)

        should_send = False

        if mode == "daily":
            should_send = True

        elif mode == "weekly":
            # pondělí = 0
            should_send = now.weekday() == 0

        elif mode == "nth_day":
            if n_val <= 0:
                n_val = 1
            should_send = (day % n_val == 0)

        elif mode == "off":
            return

        else:
            return  # unknown mode

        if not should_send:
            return

        # ===============================
        # Broadcast → nejprve kanál
        # ===============================
        channel_id = config.get("broadcast_channel_id")
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                try:
                    await channel.send(
                        f"🎁 **{config['event_name']} – den {day}** právě začal!\n"
                        f"Otevři ho pomocí příkazu: `/calendar_start {event_id}`"
                    )
                except:
                    pass

        # ===============================
        # Broadcast → DM uživatelům
        # (kteří daný den ještě neotevřeli)
        # ===============================
        sent = 0

        for uid, opened_days in progress.items():
            if day in opened_days:
                continue

            user = self.bot.get_user(int(uid))
            if not user:
                continue

            try:
                await user.send(
                    f"🎁 Nový den kalendáře **{config['event_name']}**!\n"
                    f"Otevři ho na serveru pomocí `/calendar_start {event_id}`."
                )
                sent += 1
                await asyncio.sleep(0.3)  # rate limit
            except:
                pass

        print(f"📨 Broadcast {event_id} — Den {day}: Odesláno {sent} DM")
    # ============================================================
    #   UI COMPONENTS — CALENDAR GRID
    # ============================================================

class CalendarGridView(View):
    """Zobrazuje mřížku tlačítek pro otevření dnů kalendáře."""
    def __init__(self, cog, user, max_day, admin=False):
        super().__init__(timeout=300)
        self.cog = cog
        self.user = user
        self.admin = admin

        uid = str(user.id)
        opened = cog.progress.get(uid, [])

        cols = 5
        rows = (max_day + cols - 1) // cols

        day = 1
        for r in range(rows):
            for c in range(cols):
                if day > max_day:
                    break

                is_opened = day in opened
                style = discord.ButtonStyle.gray if is_opened else discord.ButtonStyle.green
                emoji = "✅" if is_opened else "🎁"

                self.add_item(DayButton(day, style, emoji))
                day += 1

        if admin:
            self.add_item(OpenAdminPanelButton())


class DayButton(Button):
    """Tlačítko pro otevření konkrétního dne (na serveru)."""
    def __init__(self, day, style, emoji):
        super().__init__(
            label=str(day),
            style=style,
            emoji=emoji,
            custom_id=f"day_{day}"
        )
        self.day = day

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("UniversalCalendar")

        # DM otevření je zakázané
        if interaction.guild is None:
            return await interaction.response.send_message(
                "❌ Okénka lze otevírat pouze na serveru.",
                ephemeral=True
            )

        await cog.open_day(interaction, interaction.user, self.day)


class OpenAdminPanelButton(Button):
    """Tlačítko pro otevření admin panelu."""
    def __init__(self):
        super().__init__(
            label="🛠️ Admin Panel",
            style=discord.ButtonStyle.red,
            row=4
        )

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("UniversalCalendar")
        view = AdminDaySelectView(cog)
        await interaction.response.send_message(
            "Vyber den k úpravě:",
            view=view,
            ephemeral=True
        )


# ============================================================
#   ADMIN PANEL
# ============================================================

class AdminControlView(View):
    """Panel s tlačítky: Úprava dnů, Statistiky, Nastavení."""
    def __init__(self, cog, event_id):
        super().__init__(timeout=300)
        self.cog = cog
        self.event_id = event_id

    @discord.ui.button(label="📝 Upravit dny", style=discord.ButtonStyle.primary)
    async def edit_days(self, interaction: discord.Interaction, button: Button):
        view = AdminDaySelectView(self.cog)
        await interaction.response.send_message(
            "Vyber den k úpravě:",
            view=view,
            ephemeral=True
        )

    @discord.ui.button(label="📊 Statistiky", style=discord.ButtonStyle.green)
    async def show_stats(self, interaction: discord.Interaction, button: Button):
        await interaction.client.get_cog("UniversalCalendar").calendar_stats.callback(
            interaction.client.get_cog("UniversalCalendar"),
            interaction,
            self.event_id
        )

    @discord.ui.button(label="⚙️ Nastavení", style=discord.ButtonStyle.gray)
    async def settings(self, interaction: discord.Interaction, button: Button):
        # 🟣 NOVÉ MENU S DVĚMA MOŽNOSTMI
        await interaction.response.send_message(
            "Vyber část konfigurace:",
            view=ConfigSelectView(self.cog),
            ephemeral=True
        )


# ============================================================
#   CONFIG MENU → BASIC / BROADCAST
# ============================================================

class ConfigSelectView(View):
    """Menu se dvěma tlačítky: Basic settings / Broadcast settings."""
    def __init__(self, cog):
        super().__init__(timeout=200)
        self.cog = cog

    @discord.ui.button(label="⚙️ Základní nastavení", style=discord.ButtonStyle.blurple)
    async def basic(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditConfigModalBasic(self.cog))

    @discord.ui.button(label="📣 Broadcast nastavení", style=discord.ButtonStyle.green)
    async def broadcast(self, interaction: discord.Interaction, button: Button):
      await interaction.response.send_message(
        "Vyber režim broadcastu:",
        view=BroadcastModeSelectView(self.cog),
        ephemeral=True
    )



# ============================================================
#   ADMIN DAY SELECT (dropdown)
# ============================================================

class AdminDaySelectView(View):
    def __init__(self, cog):
        super().__init__(timeout=200)
        self.cog = cog

        options = [
            discord.SelectOption(label=f"Den {d}", value=str(d))
            for d in range(1, min(cog.config["total_days"] + 1, 100))
        ]

        select = Select(
            placeholder="Vyber den k úpravě...",
            options=options
        )
        select.callback = self.select_callback
        self.add_item(select)

    async def select_callback(self, interaction: discord.Interaction):
        day = int(interaction.data["values"][0])
        await interaction.response.send_modal(EditDayModal(day, self.cog))


# ============================================================
#   CONFIRM DELETE
# ============================================================

class ConfirmDeleteView(View):
    def __init__(self, cog, event_id):
        super().__init__(timeout=60)
        self.cog = cog
        self.event_id = event_id

    @discord.ui.button(label="🗑️ Ano, smazat", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: Button):
        import shutil

        folder = f"{CALENDAR_ROOT}/{self.event_id}"
        try:
            shutil.rmtree(folder)
            del self.cog.events[self.event_id]
            await interaction.response.edit_message(
                content=f"✔ Kalendář `{self.event_id}` byl odstraněn.",
                view=None
            )
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Chyba při mazání: {e}",
                view=None
            )

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="❎ Zrušeno.",
            view=None
        )
# ============================================================
#   MODAL: CREATE NEW CALENDAR
# ============================================================

class CalendarNewModal(Modal, title="Vytvořit nový kalendář"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

        self.days = TextInput(
            label="Počet dní",
            placeholder="Např. 24",
            default="24"
        )
        self.name = TextInput(
            label="Název kalendáře",
            placeholder="Např. Advent 2026",
            default="Nový kalendář"
        )
        self.month = TextInput(
            label="Měsíc (1–12)",
            placeholder="Např. 12",
            default="12"
        )
        self.prefix = TextInput(
            label="Prefix okének",
            placeholder="Den / Box / Day",
            default="Den"
        )
        self.broadcast_time = TextInput(
            label="Broadcast čas (HH:MM)",
            placeholder="08:00",
            default="08:00"
        )

        # max 5 fields
        self.add_item(self.days)
        self.add_item(self.name)
        self.add_item(self.month)
        self.add_item(self.prefix)
        self.add_item(self.broadcast_time)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            days = int(self.days.value)
            if days < 1 or days > 1000:
                raise ValueError

        except ValueError:
            return await interaction.response.send_message(
                "❌ Počet dní musí být celé číslo.",
                ephemeral=True
            )

        name = self.name.value.strip()
        if not name:
            return await interaction.response.send_message(
                "❌ Název nesmí být prázdný.",
                ephemeral=True
            )

        try:
            month = int(self.month.value)
            if month < 1 or month > 12:
                raise ValueError
        except:
            return await interaction.response.send_message(
                "❌ Měsíc musí být číslo 1–12.",
                ephemeral=True
            )

        prefix = self.prefix.value.strip() or "Den"

        # čas
        try:
            hh, mm = self.broadcast_time.value.split(":")
            hour = int(hh)
            minute = int(mm)
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
        except:
            return await interaction.response.send_message(
                "❌ Formát času musí být HH:MM.",
                ephemeral=True
            )

        # vytvořit event
        event_id = self.cog.generate_event_id()
        self.cog.generate_event_files(
            event_id,
            name,
            month,
            days,
            prefix,
            hour,
            minute,
            channel_id=None
        )
        self.cog.events[event_id] = self.cog._load_json(
            f"{CALENDAR_ROOT}/{event_id}/config.json", {}
        )

        await interaction.response.send_message(
            f"🎉 Kalendář **{name}** byl vytvořen!\n"
            f"ID: `{event_id}`\n"
            f"Dní: **{days}**\n"
            f"Aktivní měsíc: **{month}**\n"
            f"Broadcast: **{hour:02d}:{minute:02d}**",
            ephemeral=True
        )


# ============================================================
#   MODAL: EDIT DAY CONTENT
# ============================================================

class EditDayModal(Modal, title="Úprava dne"):
    def __init__(self, day: int, cog):
        super().__init__(timeout=None)
        self.day = day
        self.cog = cog

        data = cog.content.get(str(day), {})

        self.title_field = TextInput(
            label="Titulek",
            default=data.get("title", ""),
            required=False
        )
        self.text_field = TextInput(
            label="Text odměny",
            default=data.get("text", ""),
            style=discord.TextStyle.long,
            required=False
        )
        self.image_field = TextInput(
            label="Obrázek URL (volitelné)",
            default=data.get("image", ""),
            required=False
        )
        self.roles_field = TextInput(
            label="Role ID oddělené čárkou",
            default=",".join([str(r) for r in data.get("roles", [])]),
            required=False
        )
        self.emoji_field = TextInput(
            label="Emoji (např. 🎁)",
            default=data.get("emoji", "🎁"),
            required=False
        )

        self.add_item(self.title_field)
        self.add_item(self.text_field)
        self.add_item(self.image_field)
        self.add_item(self.roles_field)
        self.add_item(self.emoji_field)

    async def on_submit(self, interaction: discord.Interaction):

        data = self.cog.content[str(self.day)]
        data["title"] = self.title_field.value.strip()
        data["text"] = self.text_field.value.strip()
        data["image"] = self.image_field.value.strip()
        data["emoji"] = self.emoji_field.value.strip()

        roles_raw = self.roles_field.value.strip()
        if roles_raw:
            ids = [x.strip() for x in roles_raw.split(",") if x.strip().isdigit()]
            data["roles"] = [int(x) for x in ids]
        else:
            data["roles"] = []

        self.cog.save_all()

        await interaction.response.send_message(
            f"✔ Den {self.day} byl aktualizován.",
            ephemeral=True
        )


# ============================================================
#   MODAL: BASIC CONFIG SETTINGS
# ============================================================

class EditConfigModalBasic(Modal, title="Základní nastavení kalendáře"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        cfg = cog.config

        self.name_field = TextInput(
            label="Název",
            default=cfg.get("event_name", ""),
            required=True
        )
        self.month_field = TextInput(
            label="Měsíc (1–12)",
            default=str(cfg.get("month") or ""),
            required=True
        )
        self.days_field = TextInput(
            label="Počet dní",
            default=str(cfg.get("total_days", 24)),
            required=True
        )
        self.time_field = TextInput(
            label="Broadcast čas (HH:MM)",
            default=f"{cfg.get('broadcast_hour', 8):02d}:{cfg.get('broadcast_minute', 0):02d}",
            required=True
        )
        self.channel_field = TextInput(
            label="ID kanálu pro broadcast",
            default=str(cfg.get("broadcast_channel_id") or ""),
            required=False
        )

        self.add_item(self.name_field)
        self.add_item(self.month_field)
        self.add_item(self.days_field)
        self.add_item(self.time_field)
        self.add_item(self.channel_field)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.cog.config

        cfg["event_name"] = self.name_field.value.strip()

        try:
            month = int(self.month_field.value)
            if not (1 <= month <= 12):
                raise ValueError
            cfg["month"] = month
        except:
            return await interaction.response.send_message(
                "❌ Měsíc musí být v rozsahu 1–12.",
                ephemeral=True
            )

        try:
            dn = int(self.days_field.value)
            if dn < 1:
                raise ValueError
            cfg["total_days"] = dn
        except:
            return await interaction.response.send_message(
                "❌ Počet dní musí být celé číslo.",
                ephemeral=True
            )

        # čas
        try:
            hh, mm = self.time_field.value.split(":")
            cfg["broadcast_hour"] = int(hh)
            cfg["broadcast_minute"] = int(mm)
        except:
            return await interaction.response.send_message(
                "❌ Špatný formát času.",
                ephemeral=True
            )

        ch = self.channel_field.value.strip()
        cfg["broadcast_channel_id"] = int(ch) if ch.isdigit() else None

        self.cog.save_all()

        await interaction.response.send_message(
            "✔ Základní nastavení aktualizováno.",
            ephemeral=True
        )


# ============================================================
#   MODAL: BROADCAST CONFIG SETTINGS
# ============================================================

class EditConfigModalBroadcast(Modal, title="Broadcast nastavení"):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        cfg = cog.config

        # Tady už není žádný Select. Hodnota režimu (mode)
        # přichází z BroadcastModeSelectView a je uložená
        # do cog._pending_broadcast_mode

        self.n_field = TextInput(
            label="N hodnota (nth_day režim)",
            default=str(cfg.get("broadcast_n", 1)),
            required=False
        )
        self.start_field = TextInput(
            label="Broadcast start day",
            default=str(cfg.get("broadcast_start_day", 1)),
            required=False
        )
        self.end_field = TextInput(
            label="Broadcast end day (prázdné = žádný limit)",
            default=str(cfg.get("broadcast_end_day") or ""),
            required=False
        )

        self.add_item(self.n_field)
        self.add_item(self.start_field)
        self.add_item(self.end_field)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.cog.config

        # správné převzetí broadcast mode:
        mode = getattr(self.cog, "_pending_broadcast_mode", None)
        if mode is None:
            mode = cfg.get("broadcast_mode", "daily")

        cfg["broadcast_mode"] = mode

        # nth-day
        try:
            cfg["broadcast_n"] = max(1, int(self.n_field.value))
        except:
            cfg["broadcast_n"] = 1

        # start day
        try:
            cfg["broadcast_start_day"] = max(1, int(self.start_field.value))
        except:
            cfg["broadcast_start_day"] = 1

        # end day
        end_raw = self.end_field.value.strip()
        cfg["broadcast_end_day"] = int(end_raw) if end_raw.isdigit() else None

        self.cog.save_all()

        # smazání temp hodnoty
        if hasattr(self.cog, "_pending_broadcast_mode"):
            delattr(self.cog, "_pending_broadcast_mode")

        await interaction.response.send_message(
            f"✔ Broadcast byl nastaven.\nRežim: **{mode}**",
            ephemeral=True
        )

# ============================================================
#   BROADCAST MODE SELECT VIEW (kvůli omezení Discordu)
# ============================================================

class BroadcastModeSelectView(View):
    def __init__(self, cog):
        super().__init__(timeout=200)
        self.cog = cog

        self.select = Select(
            placeholder="Vyber režim broadcastu...",
            options=[
                discord.SelectOption(label="Denně", value="daily"),
                discord.SelectOption(label="Týdně", value="weekly"),
                discord.SelectOption(label="Každý N-tý den", value="nth_day"),
                discord.SelectOption(label="Vypnuto", value="off")
            ],
            default=cog.config.get("broadcast_mode", "daily")
        )
        self.select.callback = self.select_callback
        self.add_item(self.select)

    async def select_callback(self, interaction: discord.Interaction):
        # uložíme vybraný mód
        self.cog._pending_broadcast_mode = self.select.values[0]

        # otevřeme modal
        await interaction.response.send_modal(EditConfigModalBroadcast(self.cog))

# ============================================================
#   COG REGISTRATION
# ============================================================

async def setup(bot: commands.Bot):
    await bot.add_cog(UniversalCalendar(bot))
