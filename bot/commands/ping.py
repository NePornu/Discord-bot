

from __future__ import annotations

import random
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

QUOTES: list[tuple[str, str]] = [
    ("Pornografie je iluze lásky.", "John Eldredge"),
    ("Sledování porna mění mozek.", "Gary Wilson"),
    ("Dej si pauzu od porna a zjistíš, jak se změní tvůj život.", "Noah Church"),
    ("Skutečná intimita není na obrazovce.", "Matt Fradd"),
    ("Láska znamená dávat sebe, ne brát druhého pro sebe.", "Christopher West"),
    ("Každá touha po pornografii je ve skutečnosti touha po spojení.", "Jason Evert"),
    ("Síla člověka se ukazuje v tom, co dokáže ovládnout.", "Sokrates"),
    ("Závislost je klec, kterou si zpočátku stavíme sami.", "Neznámý autor"),
    ("Nikdo nikdy nelitoval, že přestal s pornem – jen že s tím nezačal dřív.", "Noah Church"),
    ("Když se naučíš být sám se sebou v tichu, už nebudeš potřebovat útěk do obrazovky.", "Gary Wilson"),
    ("Svoboda není dělat cokoliv chci, ale mít sílu dělat to, co je správné.", "Jan Pavel II."),
    ("Pokušení není hřích, ale výzva k růstu.", "Neznámý autor"),
    ("Skutečné spojení začíná tam, kde končí klam obrazovky.", "Matt Fradd"),
    ("Mozek se uzdravuje, když mu dáš čas bez dopaminových bomb.", "Gary Wilson"),
    ("Porno ti dá okamžik útěchy, ale ukradne ti roky důvěry.", "NoFap Community"),
    ("Láska není o dokonalém těle, ale o věrnosti srdce.", "Neznámý autor"),
    ("Nejsi definován svými pády, ale tím, že se zvedáš.", "John Eldredge"),
    ("Zlo se rozpadá, když se na něj podíváš světlem pravdy.", "C. S. Lewis"),
    ("Síla začíná v rozhodnutí – nekliknout.", "Neznámý autor"),
    ("Život mimo pornografii není prázdný, je plný skutečných lidí.", "Metricord"),
]

def format_quote() -> str:
    text, author = random.choice(QUOTES)
    return f'📖 „{text}“ — *{author}*'

class Ping(commands.Cog):
    """Ping/latency utility s náhodným citátem."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.hybrid_command(
        name="ping",
        description="Změří odezvu bota a přidá náhodný motivační citát."
    )
    @app_commands.describe(
        detailed="Zobrazí detailní rozpis latencí (WS, send, edit).",
        hide="U slash příkazu pošle odpověď jako skrytou (ephemeral)."
    )
    async def ping(
        self,
        ctx: commands.Context,
        detailed: Optional[bool] = False,
        hide: Optional[bool] = False
    ):
        """Hybridní ping příkaz (prefix + slash) s citáty."""
        is_slash = ctx.interaction is not None

        
        start_send = time.perf_counter()
        msg = await ctx.send("⏱️ Měřím odezvu…", ephemeral=hide) if is_slash else await ctx.send("⏱️ Měřím odezvu…")
        send_ms = (time.perf_counter() - start_send) * 1000

        start_edit = time.perf_counter()
        await msg.edit(content="⏱️ Dokončuji měření…")
        edit_ms = (time.perf_counter() - start_edit) * 1000

        ws_ms = self.bot.latency * 1000

        quote = format_quote()

        if detailed:
            content = (
                f"🏓 **Pong!**\n"
                f"{quote}\n\n"
                f"### Detaily měření\n"
                f"• WebSocket: **{ws_ms:.2f} ms**\n"
                f"• Odeslání zprávy: **{send_ms:.2f} ms**\n"
                f"• Editace zprávy: **{edit_ms:.2f} ms**"
            )
        else:
            avg = (send_ms + edit_ms) / 2.0
            content = f"🏓 **Pong!** Odezva: ~{avg:.2f} ms (WS {ws_ms:.2f} ms)\n{quote}"

        try:
            await msg.edit(content=content)
        except discord.Forbidden:
            if not is_slash:
                await ctx.send("❌ Nemám oprávnění upravit zprávu.")
        except Exception as e:
            if is_slash:
                await ctx.send(f"❌ Chyba: {e}", ephemeral=True)
            else:
                await ctx.send(f"❌ Chyba: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(Ping(bot))

