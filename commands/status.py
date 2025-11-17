
from discord.ext import commands
import discord
import asyncio
from typing import Dict, Tuple, Optional, Literal
import logging

# Nastavení loggeru
logger = logging.getLogger('status_cog')

class StatusCog(commands.Cog):
    """Cog pro odesílání aktualizací stavu služby."""
    
    # Typy pro anotace
    StatusType = Literal["online", "údržba", "plánovaná_údržba", "výpadek", 
                         "částečný_výpadek", "snížený_výkon", "nestabilní", 
                         "omezená_funkčnost", "vyšetřujeme", "monitoring", "vyřešeno"]
    
    def __init__(self, bot: commands.Bot):
        """Inicializace StatusCog."""
        self.bot = bot
        
        # Mapa stavů na (emoji, barva embedu)
        self.status_map: Dict[StatusType, Tuple[str, int]] = {
            "online":                ("✅", 0x00FF00),
            "údržba":                ("🛠️", 0xFFA500),
            "plánovaná_údržba":      ("🗓️", 0xFFA500),
            "výpadek":               ("🔴", 0xFF0000),
            "částečný_výpadek":      ("🚧", 0xFF4500),
            "snížený_výkon":         ("🐌", 0xFFD700),
            "nestabilní":            ("⚠️", 0xFFFF00),
            "omezená_funkčnost":     ("⚙️", 0xFFA500),
            "vyšetřujeme":           ("🔎", 0x3498DB),
            "monitoring":            ("📡", 0x1ABC9C),
            "vyřešeno":              ("✔️", 0x00CC00),
        }
        
        # Číselné kódy pro rychlý výběr stavu
        self.code_map: Dict[str, StatusType] = {
            "1": "online",
            "2": "údržba",
            "3": "plánovaná_údržba",
            "4": "výpadek",
            "5": "částečný_výpadek",
            "6": "snížený_výkon",
            "7": "nestabilní",
            "8": "omezená_funkčnost",
            "9": "vyšetřujeme",
            "10": "monitoring",
            "11": "vyřešeno",
        }
        
        # Konstanty pro přehlednost
        self.ERROR_TIMEOUT = 60  # Čas v sekundách před smazáním chybové zprávy

    async def cog_check(self, ctx: commands.Context) -> bool:
        """Lokální kontrola pro příkaz - obchází některé globální kontroly."""
        return True

    async def _delete_message(self, message: discord.Message) -> None:
        """Pomocná metoda pro bezpečné smazání zprávy."""
        try:
            await message.delete()
        except (discord.NotFound, discord.Forbidden, discord.HTTPException) as e:
            logger.debug(f"Nelze smazat zprávu: {e}")

    async def _delayed_delete(self, message: discord.Message, delay: int = 60) -> None:
        """Smaže zprávu po určitém zpoždění."""
        await asyncio.sleep(delay)
        await self._delete_message(message)

    async def _send_error(self, ctx: commands.Context, message: str) -> None:
        """Odešle chybovou zprávu a nastaví její smazání."""
        # Smaže původní příkaz okamžitě
        await self._delete_message(ctx.message)
        
        # Odešle a po čase smaže chybovou zprávu
        error_msg = await ctx.send(message)
        asyncio.create_task(self._delayed_delete(error_msg, self.ERROR_TIMEOUT))

    @commands.command(name="status")
    @commands.has_permissions(manage_messages=True)
    @commands.cooldown(1, 10, commands.BucketType.user)
    @commands.check(lambda ctx: True)  # Bypass pro globální kontrolu
    async def status(self, ctx: commands.Context, code_or_state: Optional[str] = None, 
                     služba: Optional[str] = None, *, podrobnosti: Optional[str] = None) -> None:
        """
        Odešle embed s aktuálním stavem služby.
        
        Použití:
            !status [kód|stav] [název služby] (volitelné: podrobnosti)
        
        Příklady:
            !status 1 Web "Web běží normálně"
            !status online API "Všechny endpointy jsou funkční"
            !status výpadek Database "Databáze není dostupná"
        """
        # Kontrola povinných parametrů
        if code_or_state is None or služba is None:
            return await self._send_error(
                ctx, 
                "❌ Chybí povinné parametry. Použití: `!status [kód|stav] [název služby] (volitelné: podrobnosti)`"
            )

        # Zpracování vstupu
        key = code_or_state.lower()
        
        # Převod číselného kódu na stav
        status = self.code_map.get(key, key)
        
        # Kontrola platnosti stavu
        if status not in self.status_map:
            codes = ", ".join(f"{k}:{v}" for k, v in self.code_map.items())
            states = ", ".join(self.status_map.keys())
            return await self._send_error(
                ctx,
                f"❌ Neplatný vstup. Kódy: {codes} | Stavy: {states}"
            )

        try:
            # Smazání původního příkazu před odesláním odpovědi
            await self._delete_message(ctx.message)
            
            # Sestavení a odeslání embedu
            emoji, color = self.status_map[status]
            embed = self._create_status_embed(ctx, status, služba, podrobnosti, emoji, color)
            await ctx.send(embed=embed)
            
        except Exception as e:
            logger.error(f"Chyba při zpracování příkazu status: {e}", exc_info=True)
            await self._send_error(ctx, f"❌ Došlo k chybě při generování embedu: {str(e)}")

    def _create_status_embed(self, ctx: commands.Context, status: str, služba: str, 
                            podrobnosti: Optional[str], emoji: str, color: int) -> discord.Embed:
        """Vytvoří embed se stavem služby."""
        title = f"Stav služby: {služba}"
        desc = f"{emoji} **{status.replace('_', ' ').capitalize()}**"

        embed = discord.Embed(
            title=title,
            description=desc,
            color=color,
            timestamp=ctx.message.created_at
        )
        
        if podrobnosti:
            embed.add_field(name="Podrobnosti", value=podrobnosti, inline=False)
            
        embed.set_footer(text=f"Odesláno: {ctx.author.display_name}")
        return embed

    @status.error
    async def status_error(self, ctx: commands.Context, error) -> None:
        """Zpracování chyb při použití příkazu status."""
        error_message = self._get_error_message(error)
        
        # Logování chyby
        if not isinstance(error, (commands.MissingPermissions, commands.CommandOnCooldown)):
            logger.error(f"Error in status command: {error}", exc_info=True)
        
        # Smazání původního příkazu okamžitě
        await self._delete_message(ctx.message)
        
        # Odeslání a pozdější smazání chybové zprávy
        error_msg = await ctx.send(error_message)
        asyncio.create_task(self._delayed_delete(error_msg, self.ERROR_TIMEOUT))

    def _get_error_message(self, error) -> str:
        """Vrátí vhodnou chybovou zprávu na základě typu chyby."""
        if hasattr(error, "original") and isinstance(error.original, commands.CheckFailure):
            return "❌ Globální kontrola selhala. Nemáš potřebná oprávnění pro použití tohoto příkazu."
        elif isinstance(error, commands.CheckFailure):
            return "❌ Kontrolní podmínka selhala. Nemáš potřebná oprávnění pro použití tohoto příkazu."
        elif isinstance(error, commands.MissingPermissions):
            return "❌ Nemáš oprávnění tento příkaz použít."
        elif isinstance(error, commands.CommandOnCooldown):
            return f"⏳ Zkus to znovu za {error.retry_after:.1f}s."
        elif isinstance(error, commands.MissingRequiredArgument):
            return f"❌ Chybí povinný argument: {error.param.name}. Použití: `!status [kód|stav] [název služby] (volitelné: podrobnosti)`"
        elif isinstance(error, commands.BadArgument):
            return "❌ Neplatný argument. Použití: `!status [kód|stav] [název služby] (volitelné: podrobnosti)`"
        else:
            return f"❌ Došlo k chybě: {str(error)}"

async def setup(bot: commands.Bot) -> None:
    """Přidá cog do bota."""
    await bot.add_cog(StatusCog(bot))
