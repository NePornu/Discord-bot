import discord
from discord.ext import commands
from typing import List, Optional

TITLE = "📘 Přehled příkazů a modulů"
FOOTER = "Metricord Bot – Help System"


PAGE_DATA = [
    {
        "name": "⚙️ Core (bot.py)",
        "desc": (
            "• Start logů do `CONSOLE_CHANNEL_ID` (chunkuje dlouhé zprávy)\n"
            "• Načítá všechny cogy z `commands/`\n"
            "• Globální check podle `COMMANDS_CONFIG` (`enabled` / `admin_only`)\n"
        ),
    },
    {
        "name": "🪵 Logování (commands/log.py)",
        "desc": (
            "**Slash group:** `/log`\n"
            "• `/log status` – stav, metriky, detaily\n"
            "• `/log toggle <typ|all> <true/false>` – granularita (messages/members/channels/roles/voice/...)\n"
            "• `/log ignore <channel|user> <id> <add|remove>` – ignorování\n"
            "• `/log stats` – statistiky cogu\n"
            "• `/log test` – zkušební embed do obou log kanálů\n"
            "**Loguje:** členy (join/leave/update, role, timeout, pending…), profily (glob.)\n"
            "kanály (create/update/delete/overwrites), vlákna, role, emoji/stickers,\n"
            "invites, webhooks, integrace, stage, scheduled events, reactions,\n"
            "moderaci a vybrané audit log akce, (volitelně) presence změny\n"
            "**Perzistence:** `data/log_config.json` (nastavení), `data/member_cache.json` (cache)\n"
        ),
    },
    {
        "name": "📊 Reporty (commands/report.py)",
        "desc": (
            "• Auto 1. den v měsíci → report za předchozí měsíc do `REPORT_CHANNEL_ID`\n"
            "• Manuálně: `*report` (na `GUILD_ID`)\n"
            "**Data:** `data/member_counts.json` (joins/leaves), `data/active_users.json` (denní set aktivních)\n"
            "**Metriky:** Noví, Odchody, Celkem, DAU, MAU, DAU/MAU%, Boti/Lidé, Online, počty kanálů/rolí\n"
        ),
    },
    {
        "name": "🧮 Analytika HLL (activity_hll_optimized.py)",
        "desc": (
            "• `*dau [days_ago=0]` – DAU pro den\n"
            "• `*wau` – 7d rolling\n"
            "• `*mau [window_days=30]` – N-denní rolling (N ≤ retention)\n"
            "• `*anloghere` – nastav kanál pro heartbeat log\n"
            "• `*topusers [N]`, `*topchannels [N]` – dnešní heavy-hitters (Space-Saving, RAM only)\n"
            "**Konfigurace (`CONFIG`):** `REDIS_URL`, retenční dny, cooldowny, `TOP_K`, atd.\n"
        ),
    },
    {
        "name": "📢 Hromadné DM (commands/notify.py)",
        "desc": (
            "• `*notify \"zpráva\" [@role|role_id|ALL] [--skip @uživatel @role 123...]` *(admin)*\n"
            "• Posílá DM opatrně (≈90±30 s mezi uživateli, concurrency=1, retry)\n"
            "• Výsledky (CSV) jako příloha do `CONSOLE_CHANNEL_ID`\n"
            "• `DRY_RUN = True` → jen simulace\n"
        ),
    },
    {
        "name": "✅ Verifikace (commands/verification.py)",
        "desc": (
            "• Při joinu: přidá ověřovací roli, pošle DM s kódem, čeká na odpověď\n"
            "• Moderátor potvrdí tlačítkem v `MOD_CHANNEL_ID`\n"
            "• Po ověření: DM „Vítej“ + uvítací zpráva do `WELCOME_CHANNEL_ID`\n"
        ),
    },
    {
        "name": "🧹 Purge (commands/purge.py)",
        "desc": (
            "• `*purge <množství 1–100> [@uživatel] [slovo]` *(manage_messages)*\n"
            "• Najde přesně N odpovídajících zpráv (prochází až ~1000), hromadně smaže\n"
        ),
    },
    {
        "name": "📶 Status (commands/status.py)",
        "desc": (
            "• `*status [kód|stav] [služba] (podrobnosti)` *(manage_messages)*\n"
            "• Kódy 1..11 mapují na stavy (online/údržba/výpadek/…)\n"
            "• Mazání příkazové zprávy, cooldown, hezký barevný embed\n"
        ),
    },
    {
        "name": "🏁 Emoji Challenge (commands/emojirole.py)",
        "desc": (
            "**Slash (/challenge):** `setup role:@Role channel_name:<#kanál> emojis:\"🍁 :strongdoge: 🔥\"`, "
            "`show`, `settings`, `messages add|list|clear`, `clear`\n"
            "**Prefix (*challenge):** `setup/show/messages add|list|clear/clear`\n"
            "**Chování:** při úspěšné kombinaci → ✅ reakce, přidá roli, odpoví náhodnou zprávou (30 přednastavených)\n"
            "**Formát emoji:** Unicode (🍁 🔥 💪), custom `:strongdoge:` nebo `<:strongdoge:123...>`, kombinované `🍁 :strongdoge: 🔥`\n"
            "**Nastavení:** `require_all`, `react_ok`, `reply_on_success`\n"
            "**Data:** `data/challenge_config.json`\n"
        ),
    },
    {
        "name": "🔥 Výzvy (commands/vyzva.py)",
        "desc": (
            "• `*vyhodnotit_vyzvu [#kanál|-] [vypis=true/false] [filtr|photo|-] "
            "[mode=days/fotosum/weekly] [interval] [počet role] [počet role] ...` *(admin)*\n"
            "• Režimy: `days` (počet dní s aktivitou), `fotosum` (počet příspěvků s fotkou), "
            "`weekly` (po sobě jdoucí X-denní intervaly s aktivitou)\n"
            "• Může přidělovat role po dosažení prahů\n"
        ),
    },
]


class HelpPaginator(discord.ui.View):
    def __init__(self, author: discord.abc.User, pages: List[discord.Embed], start_index: int = 0, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.author = author
        self.pages = pages
        self.index = max(0, min(start_index, len(pages) - 1))
        self.message: Optional[discord.Message] = None

        options = [
            discord.SelectOption(label=self._clean_label(embed.title), value=str(i))
            for i, embed in enumerate(self.pages)
        ]
        self.select_menu.options = options  

        self._refresh_button_states()

    def _clean_label(self, s: Optional[str]) -> str:
        return (s or "Untitled")[:100]

    async def _update(self, interaction: discord.Interaction):
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("Tohle ovládání patří tomu, kdo otevřel nápovědu.", ephemeral=True)
        self._refresh_button_states()
        await interaction.response.edit_message(embed=self.pages[self.index], view=self)

    def _refresh_button_states(self):
        self.prev_button.disabled = (self.index <= 0)  
        self.next_button.disabled = (self.index >= len(self.pages) - 1)  

    @discord.ui.button(label="◀ Prev", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):  
        self.index = max(0, self.index - 1)
        await self._update(interaction)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):  
        self.index = min(len(self.pages) - 1, self.index + 1)
        await self._update(interaction)

    @discord.ui.button(label="✖ Close", style=discord.ButtonStyle.danger)
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):  
        if interaction.user.id != self.author.id:
            return await interaction.response.send_message("Zavřít může jen autor nápovědy.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(view=self)
        self.stop()

    @discord.ui.select(placeholder="Přejít na modul…")
    async def select_menu(self, interaction: discord.Interaction, select: discord.ui.Select):  
        try:
            target = int(select.values[0])
        except Exception:
            target = 0
        self.index = max(0, min(target, len(self.pages) - 1))
        await self._update(interaction)

    async def on_timeout(self):
        if self.message:
            for child in self.children:
                child.disabled = True
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class HelpCustom(commands.Cog):
    """Zobrazí stránkovaný přehled modulů a příkazů."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def build_pages(self) -> List[discord.Embed]:
        pages: List[discord.Embed] = []
        total = len(PAGE_DATA)
        for i, page in enumerate(PAGE_DATA, start=1):
            embed = discord.Embed(
                title=page["name"],
                description=page["desc"],
                color=discord.Color.blurple()
            )
            embed.set_author(name=TITLE)
            embed.set_footer(text=f"{FOOTER} • {i}/{total}")
            if self.bot.user and self.bot.user.display_avatar:
                embed.set_thumbnail(url=self.bot.user.display_avatar.url)
            pages.append(embed)
        return pages

    @commands.hybrid_command(name="help", description="Zobrazí stránkovaný přehled příkazů a chování modulů")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def help_command(self, ctx: commands.Context, modul: Optional[str] = None):
        """
        /help [modul]  |  *help [modul]
        - modul: substring názvu stránky (case-insensitive), otevře daný modul.
        """
        pages = self.build_pages()

        index = 0
        if modul:
            m = modul.lower().strip()
            for i, e in enumerate(pages):
                if m in (e.title or "").lower():
                    index = i
                    break

        view = HelpPaginator(author=ctx.author, pages=pages, start_index=index, timeout=180.0)

        if isinstance(ctx.interaction, discord.Interaction):
            await ctx.interaction.response.send_message(embed=pages[index], view=view, ephemeral=True)
            view.message = await ctx.interaction.original_response()
        else:
            msg = await ctx.send(embed=pages[index], view=view)
            view.message = msg

async def setup(bot: commands.Bot):
    
    if "help" in bot.all_commands:
        bot.remove_command("help")
    await bot.add_cog(HelpCustom(bot))

