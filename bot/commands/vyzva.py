import discord
from discord.ext import commands
from collections import defaultdict
import asyncio
from datetime import datetime, timedelta

class VyzvaCog(commands.Cog):
    """
    Cog pro univerzální vyhodnocení aktivity uživatelů v kanále podle různých kritérií.
    Umožňuje:
    - hodnotit podle počtu dní s aktivitou (originální režim)
    - hodnotit podle počtu zpráv s fotkou (fotosum)
    - hodnotit podle týdenní aktivity (weekly) - každých X dní aspoň jedna zpráva
    - automaticky přidělovat role podle dosaženého výsledku
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="vyhodnotit_vyzvu")
    async def vyhodnotit_vyzvu(
        self,
        ctx,
        channel: discord.TextChannel = None,
        vypis: str = "true",
        filtr: str = "",
        mode: str = "days",
        interval: int = 7,
        *odmeny
    ):
        """
        Univerzální vyhodnocení aktivity v kanále s možností odměňování rolí.

        Syntax:
        *vyhodnotit_vyzvu [#kanál] [vypis=true/false] [filtr/slovo/photo] [mode=days/fotosum/weekly] [interval] [počet role] ...

        Parametry:
        ----------
        #kanál (volitelné)    -- Textový kanál pro vyhodnocení. Pokud není zadán, použije aktuální kanál.
        vypis                 -- Zda se má vygenerovat veřejný report. 'true' (výchozí) = ano, 'false' = ne.
        filtr                 -- Slovo pro filtrování zpráv nebo 'photo' pro zprávy s obrázkovou přílohou.
        mode                  -- 'days' (výchozí): počítá dny s aktivitou
                                 'fotosum': počítá celkový počet zpráv s fotkou
                                 'weekly': kontroluje aktivitu každých X dní
        interval              -- Pro mode 'weekly': počet dní pro jeden interval (výchozí: 7).
                                 Pro ostatní módy se ignoruje.
        odmeny                -- Pary hodnot (počet, role), za kolik dní/fotek/intervalů se má udělit role.
                                 Například: 3 Aktivní 7 Superaktivní 10 Fotograf

        Použití:
        --------
        - Podle dnů s aktivitou (výchozí režim):
            *vyhodnotit_vyzvu #kanal true photo days 7 3 Aktivní 7 Superaktivní
            
        - Podle celkového počtu fotek:
            *vyhodnotit_vyzvu #kanal true photo fotosum 7 4 Fotograf
            
        - Podle týdenní aktivity (každých X dní aspoň jedna zpráva):
            *vyhodnotit_vyzvu #kanal true photo weekly 7 3 Aktivní 4 Superaktivní
            *vyhodnotit_vyzvu #kanal true - weekly 5 2 Konzistentní

        Pro mode 'weekly':
        - interval = počet dní pro jeden časový úsek (např. 7 = týden, 5 = pět dní)
        - Vyhodnocuje se, v kolika po sobě jdoucích intervalech měl uživatel aktivitu
        - Například: weekly 7 znamená kontrolu každých 7 dní zpětně

        Každý pár 'číslo role' znamená: pokud uživatel splní podmínku, dostane zadanou roli.

        Omezení a poznámky:
        -------------------
        - Oprávnění: pouze administrátor serveru.
        - Pokud není zadán kanál, použije se aktuální.
        - Pokud je report delší než 2000 znaků, pošle se jako soubor.
        - Pokud je mode 'fotosum', filtr musí být 'photo' (má smysl jen pro fotky).
        - Role musí již existovat na serveru.
        """

        try:
            await ctx.message.delete()

            
            if not ctx.author.guild_permissions.administrator:
                msg = await ctx.send("⛔ Tento příkaz může použít pouze administrátor serveru.")
                await asyncio.sleep(10)
                await msg.delete()
                return

            
            if channel is None or channel == "-":
                channel = ctx.channel
            vypis = vypis.lower() != "false"
            filtr = None if filtr == "-" else filtr
            mode = mode.lower() if mode else "days"
            
            
            if mode != "weekly" and isinstance(interval, str):
                odmeny = (str(interval),) + odmeny
                interval = 7
            
            odmeny = [o for o in odmeny if o != "-"]

            
            now = datetime.now()
            cutoff_date = None
            
            if mode == "weekly":
                max_intervals = 12  
                
                days_needed = (max_intervals + 2) * interval
                cutoff_date = now - timedelta(days=days_needed)
            else:
                
                cutoff_date = now - timedelta(days=365)

            status_message = await ctx.send(
                f"📊 Analyzuji zprávy v {channel.mention} (režim: {self._get_mode_description(mode, interval)}).\n"
                f"🕒 Limit historie: zprávy novější než {cutoff_date.strftime('%d.%m.%Y')}..."
            )

            
            if mode == "days":
                user_dict = defaultdict(set)
            elif mode == "fotosum":
                user_dict = defaultdict(int)
            elif mode == "weekly":
                user_dict = defaultdict(set)  
            else:
                await status_message.edit(content="❌ Neplatný mód! Použijte: days, fotosum nebo weekly")
                return

            
            count_scanned = 0
            async for message in channel.history(limit=None, after=cutoff_date):
                count_scanned += 1
                if message.author.bot:
                    continue
                    
                
                if filtr:
                    if filtr.lower() == "photo":
                        if not message.attachments or not any(
                            att.content_type and att.content_type.startswith("image") for att in message.attachments
                        ):
                            continue
                    elif filtr not in message.content and not any(str(emoji) in message.content for emoji in message.guild.emojis):
                        continue

                if mode == "days":
                    date = message.created_at.date()
                    user_dict[message.author.id].add(date)
                elif mode == "fotosum":
                    user_dict[message.author.id] += 1
                elif mode == "weekly":
                    
                    days_ago = (now - message.created_at).days
                    interval_number = days_ago // interval
                    if interval_number < max_intervals:  
                        user_dict[message.author.id].add(interval_number)

            
            if mode == "fotosum" and filtr != "photo":
                await status_message.edit(content="❌ Pro fotosum musí být filtr photo!")
                return

            results = []
            activity_report = [f"📋 **Aktivita uživatelů** ({self._get_report_header(mode, interval)}) [Scanned: {count_scanned}]:"]

            for user_id, value in user_dict.items():
                if mode == "weekly":
                    
                    score = self._count_consecutive_intervals(value)
                else:
                    score = len(value) if mode == "days" else value
                    
                user = ctx.guild.get_member(user_id)
                if user:
                    activity_report.append(
                        f"👤 {user.display_name} – **{score} {self._get_score_unit(mode, interval)}**"
                    )
                    
                    
                    for i in range(0, len(odmeny), 2):
                        try:
                            threshold = int(odmeny[i])
                            role = discord.utils.get(ctx.guild.roles, name=odmeny[i + 1])
                            if score >= threshold and role and role not in user.roles:
                                await user.add_roles(role)
                                results.append(
                                    f"🏆 {user.mention} získal roli {role.name} ({score} {self._get_score_unit(mode, interval)})"
                                )
                        except (ValueError, IndexError):
                            continue

            
            if vypis:
                activity_report_text = "\n".join(activity_report)
                if len(activity_report_text) > 2000:
                    with open("activity_report.txt", "w", encoding="utf-8") as file:
                        file.write(activity_report_text)
                    await ctx.send(
                        "📄 **Přehled aktivity je moc dlouhý, posílám jako soubor:**",
                        file=discord.File("activity_report.txt"),
                    )
                else:
                    await ctx.send(activity_report_text)

            
            if results:
                await ctx.send("\n".join(results))
            elif odmeny:
                no_reward_msg = await ctx.send("ℹ️ Nikdo nesplnil podmínky pro získání role.")
                await asyncio.sleep(10)
                await no_reward_msg.delete()

            await status_message.delete()

        except Exception as e:
            error_msg = await ctx.send(f"⚠️ Chyba: {e}")
            print(f"❌ Chyba při vyhodnocení výzvy: {e}")
            await asyncio.sleep(10)
            await error_msg.delete()

    def _get_mode_description(self, mode, interval):
        """Vrátí popis módu pro status zprávu"""
        if mode == "days":
            return "podle dnů"
        elif mode == "fotosum":
            return "celkový počet fotek"
        elif mode == "weekly":
            return f"každých {interval} dní"
        return "neznámý"

    def _get_report_header(self, mode, interval):
        """Vrátí hlavičku pro report"""
        if mode == "days":
            return "dny"
        elif mode == "fotosum":
            return "počet fotek"
        elif mode == "weekly":
            return f"po sobě jdoucí {interval}-denní období"
        return "neznámé"

    def _get_score_unit(self, mode, interval):
        """Vrátí jednotku pro skóre"""
        if mode == "days":
            return "dní"
        elif mode == "fotosum":
            return "fotek"
        elif mode == "weekly":
            return f"{interval}-denních období"
        return "bodů"

    def _count_consecutive_intervals(self, intervals):
        """Počítá po sobě jdoucí intervaly od nejnovějšího (0)"""
        if not intervals:
            return 0
        
        sorted_intervals = sorted(intervals)
        consecutive_count = 0
        
        
        for i in range(min(sorted_intervals), max(sorted_intervals) + 1):
            if i in intervals:
                consecutive_count += 1
            else:
                break
                
        return consecutive_count

async def setup(bot):
    """
    Nutné pro načtení cogu v Discord.py 2.x
    """
    await bot.add_cog(VyzvaCog(bot))
