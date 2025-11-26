import discord
import os
import json
from discord import app_commands
from discord.ext import commands, tasks
from discord.ui import View, Button, Modal, TextInput, Select
from datetime import datetime
from typing import Optional, Dict
import asyncio

# ============================================================
#   ULTIMATE UNIVERSAL CALENDAR COG – MULTI-EVENT ENGINE
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
    #   JSON + FILESYSTEM HELPERS
    # ============================================================
    def load_events(self) -> Dict:
        """Načte všechny eventy ze složky ./calendar/"""
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
            print(f"⚠️ Error loading {path}: {e}")
        return default

    def _save_json(self, path: str, data):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"⚠️ Error saving {path}: {e}")

    # ============================================================
    #   EVENT GENERATOR
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

        # config file
        config = {
            "event_name": name,
            "month": month,
            "total_days": days,
            "broadcast_hour": hour,
            "broadcast_minute": minute,
            "broadcast_channel_id": channel_id,
            "created_at": datetime.now().isoformat(),
            "active": True
        }
        self._save_json(f"{folder}/config.json", config)

        # content file
        content = {}
        for d in range(1, days + 1):
            content[str(d)] = {
                "title": f"{prefix} {d}",
                "text": "Zatím prázdné. Použij admin panel pro úpravu.",
                "image": "",
                "roles": [],
                "emoji": "🎁"
            }
        self._save_json(f"{folder}/content.json", content)

        # progress file
        self._save_json(f"{folder}/progress.json", {})

        # stats file
        self._save_json(f"{folder}/stats.json", {
            "total_opens": 0,
            "unique_users": 0,
            "daily_opens": {}
        })

        return config

    # ============================================================
    #   LOAD EVENT INTO MEMORY
    # ============================================================
    def load_event(self, event_id: str):
        folder = f"{CALENDAR_ROOT}/{event_id}"

        self.event_id = event_id
        self.event_folder = folder

        self.config = self._load_json(f"{folder}/config.json", {})
        self.content = self._load_json(f"{folder}/content.json", {})
        self.progress = self._load_json(f"{folder}/progress.json", {})
        self.stats = self._load_json(
            f"{folder}/stats.json",
            {"total_opens": 0, "unique_users": 0, "daily_opens": {}}
        )

    def save_all(self):
        folder = self.event_folder
        self._save_json(f"{folder}/config.json", self.config)
        self._save_json(f"{folder}/content.json", self.content)
        self._save_json(f"{folder}/progress.json", self.progress)
        self._save_json(f"{folder}/stats.json", self.stats)
    # ============================================================
    #   SLASH COMMANDS
    # ============================================================

    @app_commands.command(name="calendar_new", description="Vytvořit nový kalendář")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_new(self, interaction: discord.Interaction):
        await interaction.response.send_modal(CalendarNewModal(self))

    @app_commands.command(name="calendar_list", description="Zobrazit všechny kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_list(self, interaction: discord.Interaction):
        if not self.events:
            return await interaction.response.send_message(
                "📭 Žádné kalendáře nenalezeny.",
                ephemeral=True
            )

        embed = discord.Embed(
            title="📅 Seznam všech kalendářů",
            color=discord.Color.blue()
        )

        for event_id, cfg in self.events.items():
            status = "🟢 Aktivní" if cfg.get("active", True) else "🔴 Vypnutý"
            embed.add_field(
                name=f"{cfg['event_name']} (`{event_id}`)",
                value=(
                    f"{status}\n"
                    f"Dní: **{cfg['total_days']}**\n"
                    f"Broadcast: **{cfg['broadcast_hour']}:{cfg['broadcast_minute']:02d}**"
                ),
                inline=False
            )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="calendar_start", description="Zobrazí kalendář uživateli")
    @app_commands.describe(
        event_id="ID kalendáře",
        mode="live = podle reálného data, test = zobraz všechny dny"
    )
    async def calendar_start(self, interaction: discord.Interaction, event_id: str, mode: str):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Tento event neexistuje.", ephemeral=True)

        self.load_event(event_id)

        # Validace režimu
        mode = mode.lower()
        if mode not in ("live", "test"):
            return await interaction.response.send_message(
                "❌ Režim musí být `live` nebo `test`.",
                ephemeral=True
            )

        now = datetime.now()
        total = self.config["total_days"]

        # Určení viditelných dnů
        if mode == "live":
            if self.config["month"] is not None and self.config["month"] != now.month:
                return await interaction.response.send_message(
                    f"❌ Tento kalendář je aktivní v měsíci **{self.config['month']}**, "
                    f"teď je **{now.month}**.",
                    ephemeral=True
                )
            max_day = min(now.day, total)
        else:
            max_day = total

        uid = str(interaction.user.id)
        opened = self.progress.get(uid, [])

        embed = discord.Embed(
            title=f"📅 {self.config['event_name']}",
            description=(
                f"Režim: **{mode.upper()}**\n"
                f"Dostupné dny: **{max_day}/{total}**\n"
                f"Tvůj progres: **{len(opened)}/{max_day}**"
            ),
            color=discord.Color.gold()
        )

        view = CalendarGridView(self, interaction.user, max_day, admin=False)
        await interaction.response.send_message(embed=embed, view=view)

    @app_commands.command(name="calendar_admin", description="Admin panel kalendáře")
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_admin(self, interaction: discord.Interaction, event_id: str):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        self.load_event(event_id)

        embed = discord.Embed(
            title=f"🛠️ Admin panel – {self.config['event_name']}",
            description=(
                f"ID: `{event_id}`\n"
                f"Dní: **{self.config['total_days']}**\n"
                f"Broadcast: **{self.config['broadcast_hour']}:{self.config['broadcast_minute']:02d}**"
            ),
            color=discord.Color.red()
        )

        view = AdminControlView(self, event_id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="calendar_stats", description="Statistiky kalendáře")
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_stats(self, interaction: discord.Interaction, event_id: str):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        self.load_event(event_id)

        embed = discord.Embed(
            title=f"📊 Statistiky – {self.config['event_name']}",
            color=discord.Color.blue()
        )

        unique_users = len(self.progress)
        total_opens = sum(len(v) for v in self.progress.values())

        embed.add_field(
            name="Celkové statistiky",
            value=(
                f"👥 Unikátní uživatelé: **{unique_users}**\n"
                f"📬 Celkem otevření: **{total_opens}**"
            ),
            inline=False
        )

        # TOP 5 uživatelů
        if self.progress:
            sorted_users = sorted(self.progress.items(), key=lambda x: len(x[1]), reverse=True)
            top = "\n".join(
                f"{i+1}. <@{uid}> – **{len(days)}** dní"
                for i, (uid, days) in enumerate(sorted_users[:5])
            )
            embed.add_field(name="🏆 Top 5 nejaktivnějších", value=top, inline=False)

        # TOP dny
        day_counter = {}
        for days in self.progress.values():
            for d in days:
                day_counter[d] = day_counter.get(d, 0) + 1

        if day_counter:
            sorted_days = sorted(day_counter.items(), key=lambda x: x[1], reverse=True)
            top_days = "\n".join(
                f"Den {d}: **{c}×** otevřen"
                for d, c in sorted_days[:5]
            )
            embed.add_field(name="📅 Nejoblíbenější dny", value=top_days, inline=False)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="calendar_delete", description="Smazat kalendář")
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_delete(self, interaction: discord.Interaction, event_id: str):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        view = ConfirmDeleteView(self, event_id)
        await interaction.response.send_message(
            f"⚠️ Opravdu chceš **smazat** kalendář `{event_id}`?\nTato akce je nevratná.",
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="calendar_toggle", description="Zapnout/vypnout kalendář (broadcast)")
    @app_commands.describe(event_id="ID kalendáře")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_toggle(self, interaction: discord.Interaction, event_id: str):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        self.load_event(event_id)

        self.config["active"] = not self.config.get("active", True)
        status = "🟢 Aktivní" if self.config["active"] else "🔴 Vypnutý"

        self.save_all()
        self.events[event_id] = self.config

        await interaction.response.send_message(
            f"Kalendář `{event_id}` je nyní **{status}**.",
            ephemeral=True
        )

    @app_commands.command(name="calendar_reset_user", description="Resetuje progres uživatele")
    @app_commands.describe(event_id="ID kalendáře", user="Uživatel k resetu")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_reset_user(self, interaction: discord.Interaction,
                                  event_id: str, user: discord.User):
        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        self.load_event(event_id)
        uid = str(user.id)

        if uid in self.progress:
            del self.progress[uid]
            self.save_all()
            await interaction.response.send_message(
                f"✔ Progres uživatele {user.mention} resetován.",
                ephemeral=True
            )
        else:
            await interaction.response.send_message(
                f"❌ Uživatel {user.mention} nemá žádný progres.",
                ephemeral=True
            )

    @app_commands.command(name="calendar_broadcast_test", description="Odeslat testovací broadcast (jen tobě)")
    @app_commands.describe(event_id="ID kalendáře", day="Testovací den (volitelné)")
    @app_commands.checks.has_permissions(administrator=True)
    async def calendar_broadcast_test(self, interaction: discord.Interaction,
                                      event_id: str, day: Optional[int] = None):

        if event_id not in self.events:
            return await interaction.response.send_message("❌ Event neexistuje.", ephemeral=True)

        self.load_event(event_id)

        if day is None:
            day = min(datetime.now().day, self.config["total_days"])

        if not (1 <= day <= self.config["total_days"]):
            return await interaction.response.send_message(
                f"❌ Den musí být mezi 1 a {self.config['total_days']}.",
                ephemeral=True
            )

        data = self.content.get(str(day), {})

        embed = discord.Embed(
            title=f"📩 Test broadcast – den {day}",
            description=f"**{data.get('title', f'Den {day}')}**\n\nKlikni pro otevření.",
            color=discord.Color.green()
        )

        try:
            await interaction.user.send(
                embed=embed,
                view=BroadcastOpenView(day)
            )
            await interaction.response.send_message("✔ Test broadcast odeslán do DM.", ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Nemůžu ti poslat DM. Zkontroluj soukromí.",
                ephemeral=True
            )
    # ============================================================
    #   CORE FUNCTIONALITY – OTEVŘENÍ DNE
    # ============================================================
    async def open_day(self, interaction: discord.Interaction, user: discord.User, day: int):
        """Otevře konkrétní den pro uživatele a odešle DM s odměnou."""

        uid = str(user.id)

        # Vytvořit záznam uživatele
        if uid not in self.progress:
            self.progress[uid] = []

        # Už otevřeno?
        if day in self.progress[uid]:
            return await interaction.response.send_message(
                "🔁 Tento den už máš otevřený.",
                ephemeral=True
            )

        # Obsah neexistuje?
        if str(day) not in self.content:
            return await interaction.response.send_message(
                "❌ Tento den neobsahuje žádná data.",
                ephemeral=True
            )

        data = self.content[str(day)]

        # ZAPSAT PROGRES
        self.progress[uid].append(day)

        self.stats["total_opens"] = self.stats.get("total_opens", 0) + 1
        self.stats["unique_users"] = len(self.progress)

        # Denní statistika
        self.stats["daily_opens"][str(day)] = self.stats["daily_opens"].get(str(day), 0) + 1

        # Uložit změny
        self.save_all()

        # EMBED
        embed = discord.Embed(
            title=f"{data.get('emoji', '🎁')} {data['title']}",
            description=data["text"],
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )

        if data["image"]:
            embed.set_image(url=data["image"])

        embed.set_footer(text=f"Den {day}/{self.config['total_days']}")

        # ROLE REWARDS
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

        # DM ODESLÁNÍ
        try:
            await user.send(embed=embed)

            response = "📬 Odměna poslána do DM!"
            if roles_added:
                response += f"\n🎭 Přiřazené role: {', '.join(roles_added)}"

            await interaction.response.send_message(response, ephemeral=True)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Nemůžu ti poslat DM. Zapni soukromé zprávy.",
                ephemeral=True
            )
        except Exception as e:
            await interaction.response.send_message(
                f"❌ Nepodařilo se odeslat DM: {e}",
                ephemeral=True
            )

    # ============================================================
    #   BROADCAST ENGINE
    # ============================================================
    @tasks.loop(minutes=1)
    async def broadcast_loop(self):
        """Každou minutu zkontroluje všechny eventy a pošle broadcast."""
        now = datetime.now()
        cache_key = f"{now.year}-{now.month}-{now.day}-{now.hour}-{now.minute}"

        # Zabraňuje dvojímu spuštění ve stejné minutě
        if cache_key in self.broadcast_cache:
            return

        self.broadcast_cache[cache_key] = True

        # Udržovat cache čistý (max 60 položek)
        if len(self.broadcast_cache) > 60:
            old = list(self.broadcast_cache.keys())[:-60]
            for key in old:
                del self.broadcast_cache[key]

        # Projít všechny eventy
        for event_id in list(self.events.keys()):
            try:
                await self._process_event_broadcast(event_id, now)
            except Exception as e:
                print(f"⚠️ Chyba při broadcastu eventu {event_id}: {e}")

    async def _process_event_broadcast(self, event_id: str, now: datetime):
        """Zpracuje broadcast pro jeden event."""
        folder = f"{CALENDAR_ROOT}/{event_id}"

        config = self._load_json(f"{folder}/config.json", {})
        if not config:
            return

        # Event vypnutý
        if not config.get("active", True):
            return

        content = self._load_json(f"{folder}/content.json", {})
        progress = self._load_json(f"{folder}/progress.json", {})

        # Pokud je definovaný měsíc → zkontrolovat
        month = config.get("month")
        if month is not None and month != now.month:
            return

        # Broadcast se odešle pouze v konkrétní minutu
        H = config.get("broadcast_hour")
        M = config.get("broadcast_minute")

        if now.hour != H or now.minute != M:
            return

        day = now.day
        if day > config["total_days"]:
            return  # Neexistuje den → ignorovat

        if str(day) not in content:
            return

        data = content[str(day)]

        # Poslat broadcast do kanálu (pokud je)
        channel_id = config.get("broadcast_channel_id")
        if channel_id:
            channel = self.bot.get_channel(int(channel_id))
            if channel:
                embed = discord.Embed(
                    title=f"{data.get('emoji', '🎁')} {config['event_name']} – Den {day}",
                    description="Použij `/calendar_start` pro otevření dne.",
                    color=discord.Color.green()
                )
                try:
                    await channel.send(embed=embed)
                except:
                    pass

        # DM všem uživatelům, co mají progres, ale neotevřeli tento den
        sent = 0
        for uid, opened in progress.items():
            if day in opened:
                continue

            user = self.bot.get_user(int(uid))
            if not user:
                continue

            embed = discord.Embed(
                title=f"{data.get('emoji', '🎁')} {config['event_name']} – Den {day}",
                description="Klikni níže, pokud chceš odměnu!",
                color=discord.Color.green()
            )

            try:
                await user.send(embed=embed, view=BroadcastOpenView(day))
                sent += 1
                await asyncio.sleep(0.5)  # Rate-limit protection
            except:
                pass

        print(f"📨 Broadcast eventu {event_id}: den {day} → {sent} uživatelům")

    @broadcast_loop.before_loop
    async def before_broadcast(self):
        """Počká na ready bot instance před startem loopu."""
        await self.bot.wait_until_ready()
# ============================================================
#   UI COMPONENTS – GRID / ADMIN / BROADCAST
# ============================================================

class CalendarGridView(View):
    """Mřížka tlačítek pro dny, dynamická podle počtu dní."""
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

                style = discord.ButtonStyle.gray if day in opened else discord.ButtonStyle.green
                emoji = "✅" if day in opened else "🎁"

                self.add_item(DayButton(day, style, emoji))
                day += 1

        # Admin button (only visible in admin views)
        if admin:
            self.add_item(OpenAdminPanelButton())


class DayButton(Button):
    """Tlačítko pro otevření určitého dne."""
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
        await cog.open_day(interaction, interaction.user, self.day)


class OpenAdminPanelButton(Button):
    """Admin tlačítko – otevře výběr dne k úpravě."""
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


class AdminControlView(View):
    """Hlavní admin menu pro event – úpravy, statistiky, nastavení."""
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
        # Zavoláme přímo stats command
        stats_cmd = interaction.client.get_cog("UniversalCalendar").calendar_stats
        await stats_cmd.callback(
            interaction.client.get_cog("UniversalCalendar"),
            interaction,
            self.event_id
        )

    @discord.ui.button(label="⚙️ Nastavení", style=discord.ButtonStyle.gray)
    async def settings(self, interaction: discord.Interaction, button: Button):
        await interaction.response.send_modal(EditConfigModal(self.cog))


class AdminDaySelectView(View):
    """Select menu – výběr dne k úpravě."""
    def __init__(self, cog):
        super().__init__(timeout=300)
        self.cog = cog

        options = [
            discord.SelectOption(
                label=f"Den {d}",
                value=str(d)
            )
            for d in range(1, cog.config["total_days"] + 1)
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


class BroadcastOpenView(View):
    """View pro broadcast DM zprávy – zobrazí tlačítko pro otevření."""
    def __init__(self, day):
        super().__init__(timeout=None)
        self.add_item(BroadcastOpenButton(day))


class BroadcastOpenButton(Button):
    """Tlačítko v broadcast DM – otevře den v příslušném aktivním eventu."""
    def __init__(self, day):
        super().__init__(
            label=f"🎁 Otevřít den {day}",
            style=discord.ButtonStyle.green,
            custom_id=f"broadcast_open_{day}"
        )
        self.day = day

    async def callback(self, interaction: discord.Interaction):
        cog = interaction.client.get_cog("UniversalCalendar")

        # Najdeme aktivní event
        for event_id in cog.events:
            cog.load_event(event_id)
            if cog.config.get("active", True):
                await cog.open_day(interaction, interaction.user, self.day)
                break


class ConfirmDeleteView(View):
    """Potvrzení smazání kalendáře."""
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
                content=f"🗑️ Kalendář `{self.event_id}` byl smazán.",
                view=None
            )
        except Exception as e:
            await interaction.response.edit_message(
                content=f"❌ Chyba při mazání: {e}",
                view=None
            )

    @discord.ui.button(label="❌ Zrušit", style=discord.ButtonStyle.gray)
    async def cancel(self, interaction: discord.Interaction, button: Button):
        await interaction.response.edit_message(
            content="❎ Operace zrušena.",
            view=None
        )
# ============================================================
#   MODALS – GUI FORMULÁŘE PRO SPRÁVU KALENDÁŘE
# ============================================================

class CalendarNewModal(Modal, title="Vytvořit nový kalendář"):
    """Modal pro vytvoření nového multi-event kalendáře."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

        self.days = TextInput(
            label="Počet dní:",
            placeholder="Např. 24 nebo 30",
            default="24"
        )
        self.name = TextInput(
            label="Název kalendáře:",
            placeholder="Např. Advent 2025",
            default="Nový kalendář"
        )
        self.month = TextInput(
            label="Měsíc (1–12 nebo prázdné):",
            placeholder="12 = prosinec, prázdné = celoroční",
            required=False
        )
        self.prefix = TextInput(
            label="Prefix názvů (Den, Box, Gift…):",
            default="Den",
            required=True
        )
        self.broadcast_time = TextInput(
            label="Broadcast čas (HH:MM):",
            default="08:00",
            required=True
        )

        # MAX 5 položek!
        self.add_item(self.days)
        self.add_item(self.name)
        self.add_item(self.month)
        self.add_item(self.prefix)
        self.add_item(self.broadcast_time)

    async def on_submit(self, interaction: discord.Interaction):

        # základní věci
        days = int(self.days.value)
        name = self.name.value.strip()
        prefix = self.prefix.value.strip() or "Den"

        # měsíc
        month_str = self.month.value.strip()
        if month_str:
            month = int(month_str)
        else:
            month = None

        # čas broadcastu
        time_str = self.broadcast_time.value.strip()
        hour, minute = 8, 0
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                hour = int(parts[0])
                minute = int(parts[1])
        except ValueError:
            # necháme 8:00 jako fallback
            pass

        # kanál při vytvoření nedáváme, necháme None
        channel_id = None

        event_id = self.cog.generate_event_id()
        config = self.cog.generate_event_files(
            event_id,
            name,
            month,
            days,
            prefix,
            hour,
            minute,
            channel_id=channel_id
        )

        self.cog.events[event_id] = config

        await interaction.response.send_message(
            f"🎉 Kalendář **{name}** byl vytvořen!\n"
            f"ID: `{event_id}`\n"
            f"Dní: **{days}**\n"
            f"Broadcast: **{hour:02d}:{minute:02d}**",
            ephemeral=True
        )


# ============================================================
#   EDIT DAY MODAL – ÚPRAVA KONKRÉTNÍHO DNE
# ============================================================

class EditDayModal(Modal, title="Upravit den"):
    """Umožňuje adminovi editovat obsah konkrétního dne."""
    def __init__(self, day, cog):
        super().__init__(timeout=None)
        self.day = day
        self.cog = cog

        data = cog.content.get(str(day), {
            "title": f"Den {day}",
            "text": "",
            "image": "",
            "roles": [],
            "emoji": "🎁"
        })

        self.title_field = TextInput(
            label="Titulek:",
            default=data["title"]
        )
        self.text_field = TextInput(
            label="Text:",
            default=data["text"],
            style=discord.TextStyle.paragraph,
            max_length=1900
        )
        self.image_field = TextInput(
            label="Obrázek URL:",
            default=data["image"],
            required=False
        )
        self.roles_field = TextInput(
            label="Role ID (oddělit čárkami):",
            default=",".join(str(x) for x in data["roles"]),
            required=False
        )
        self.emoji_field = TextInput(
            label="Emoji:",
            default=data.get("emoji", "🎁"),
            required=False
        )

        self.add_item(self.title_field)
        self.add_item(self.text_field)
        self.add_item(self.image_field)
        self.add_item(self.roles_field)
        self.add_item(self.emoji_field)

    async def on_submit(self, interaction: discord.Interaction):

        # Zpracovat role
        roles = []
        if self.roles_field.value.strip():
            for r in self.roles_field.value.split(","):
                r = r.strip()
                if r.isdigit():
                    roles.append(int(r))

        # Uložit změny
        self.cog.content[str(self.day)] = {
            "title": self.title_field.value,
            "text": self.text_field.value,
            "image": self.image_field.value,
            "roles": roles,
            "emoji": self.emoji_field.value or "🎁"
        }

        self.cog.save_all()

        await interaction.response.send_message(
            f"✔ Den **{self.day}** byl aktualizován.",
            ephemeral=True
        )


# ============================================================
#   CONFIG EDIT MODAL – ÚPRAVA KONFIGURACE KALENDÁŘE
# ============================================================

class EditConfigModal(Modal, title="Upravit nastavení kalendáře"):
    """Umožňuje adminovi změnit základní config kalendáře."""
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog
        cfg = cog.config

        # složíme broadcast do jednoho pole HH:MM
        default_time = f"{cfg.get('broadcast_hour', 8):02d}:{cfg.get('broadcast_minute', 0):02d}"

        self.name_field = TextInput(
            label="Název:",
            default=cfg.get("event_name", ""),
            required=True
        )
        self.month_field = TextInput(
            label="Měsíc (1–12 nebo prázdné):",
            default=str(cfg.get("month") or ""),
            required=False
        )
        self.days_field = TextInput(
            label="Počet dní:",
            default=str(cfg.get("total_days", 24)),
            required=True
        )
        self.time_field = TextInput(
            label="Broadcast čas (HH:MM):",
            default=default_time,
            required=True
        )
        self.channel_field = TextInput(
            label="ID kanálu pro broadcast:",
            default=str(cfg.get("broadcast_channel_id") or ""),
            required=False
        )

        # MAX 5 položek!
        self.add_item(self.name_field)
        self.add_item(self.month_field)
        self.add_item(self.days_field)
        self.add_item(self.time_field)
        self.add_item(self.channel_field)

    async def on_submit(self, interaction: discord.Interaction):
        cfg = self.cog.config

        cfg["event_name"] = self.name_field.value.strip()

        # měsíc
        month_str = self.month_field.value.strip()
        if month_str:
            cfg["month"] = int(month_str)
        else:
            cfg["month"] = None

        # počet dní
        cfg["total_days"] = int(self.days_field.value)

        # čas HH:MM
        time_str = self.time_field.value.strip()
        hour, minute = cfg.get("broadcast_hour", 8), cfg.get("broadcast_minute", 0)
        try:
            parts = time_str.split(":")
            if len(parts) == 2:
                hour = int(parts[0])
                minute = int(parts[1])
        except ValueError:
            pass

        cfg["broadcast_hour"] = hour
        cfg["broadcast_minute"] = minute

        # kanál
        ch_str = self.channel_field.value.strip()
        if ch_str.isdigit():
            cfg["broadcast_channel_id"] = int(ch_str)
        else:
            cfg["broadcast_channel_id"] = None

        # uložit
        self.cog.save_all()

        await interaction.response.send_message(
            f"✔ Nastavení kalendáře aktualizováno.\n"
            f"Broadcast: **{hour:02d}:{minute:02d}**"
            + (f"\nKanál: `<#{cfg['broadcast_channel_id']}>`" if cfg.get("broadcast_channel_id") else "\nKanál: žádný"),
            ephemeral=True
        )

# ============================================================
#   DOPLŇKOVÉ UI A FINÁLNÍ REGISTRACE COGU
# ============================================================

# (Většina UI komponent byla už ve ČÁSTI 4, takže zde zbývá jen završení)

# Nic dalšího už není potřeba — ConfirmDeleteView, AdminControlView,
# AdminDaySelectView, BroadcastOpenView a další už byly kompletní.


# ============================================================
#   BOT SETUP — TOTO JE NUTNÉ NA KONCI SOUBORU
# ============================================================

async def setup(bot: commands.Bot):
    """Registrace Cogu do bota jako extension."""
    await bot.add_cog(UniversalCalendar(bot))
