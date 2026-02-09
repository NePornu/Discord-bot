from discord.ext import commands
import discord
import asyncio
import csv
import io
import logging
import random
from datetime import datetime
from typing import Optional, Iterable, Tuple, Set

logger = logging.getLogger("notify_cog")

class NotifyCog(commands.Cog):
    """
    Hromadné DM oznámení s maximální ochranou proti banu:
      - extrémně konzervativní rozestupy (3-5 minut mezi zprávami),
      - live zpětná vazba o postupu,
      - CSV report jako příloha,
      - cílení na ALL nebo konkrétní roli,
      - volitelný --skip (uživatelé/role).

    Použití:
      !notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role ...]

    Příklady:
      !notify "Server byl uzavřen Discordem. Nové místo: https://discord.gg/XXXX" ALL
      !notify "Info jen pro ověřené" @Ověřený --skip @Admin 123456789012345678
    """

    # EXTRÉMNĚ KONZERVATIVNÍ nastavení pro ochranu proti banu
    DRY_RUN             = False      # False = skutečné odesílání
    BASE_DELAY_SECONDS  = 180        # 3 minuty základní delay
    JITTER_SECONDS      = 120        # ±2 minuty náhody = celkem 1-5 minut mezi zprávami
    MAX_CONCURRENCY     = 1          # pouze 1 DM najednou
    MAX_RETRIES         = 2          # méně retry
    TIMEOUT_PER_DM      = 30         # delší timeout
    
    # Ochranné limity
    MAX_DMS_PER_HOUR    = 15         # maximálně 15 DM za hodinu
    PAUSE_AFTER_BATCH   = 10         # po 10 zprávách pauza
    BATCH_PAUSE_MINUTES = 15         # 15 minut pauza po každých 10 zprávách
    
    LOG_FILENAME        = "dm_status_report.csv"

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sem = asyncio.Semaphore(self.MAX_CONCURRENCY)
        self._results = []
        self._status_message = None  # pro live update
        self._sent_count = 0
        self._dm_timestamps = []  # sledování rate limitu

    async def _console_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Získá log kanál podle config.CONSOLE_CHANNEL_ID."""
        try:
            from config import config
            return guild.get_channel(getattr(config, "CONSOLE_CHANNEL_ID", 0))
        except Exception:
            return None

    async def _log(self, guild: discord.Guild, msg: str):
        """Pošle log do log kanálu + do loggeru."""
        ch = await self._console_channel(guild)
        full = f"{datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')} {msg}"
        if ch:
            try:
                for i in range(0, len(full), 1900):
                    await ch.send(f"```{full[i:i+1900]}```")
            except Exception as e:
                logger.warning(f"Log do kanálu selhal: {e}")
        logger.info(full)

    async def _update_status(self, ctx: commands.Context, sent: int, total: int, skipped: int, failed: int, eta_minutes: int = 0):
        """Aktualizuje živou zpětnou vazbu o postupu."""
        status_text = (
            f"📨 **Průběh rozesílání DM**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Odesláno: **{sent}** / {total}\n"
            f"⏭️ Přeskočeno: **{skipped}**\n"
            f"❌ Selhalo: **{failed}**\n"
            f"⏱️ Odhadovaný čas: **~{eta_minutes} minut**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"_Průměrný interval: 3-5 minut mezi zprávami_"
        )
        
        try:
            if self._status_message is None:
                self._status_message = await ctx.send(status_text)
            else:
                await self._status_message.edit(content=status_text)
        except Exception as e:
            logger.warning(f"Nepodařilo se aktualizovat status: {e}")

    async def _delete_message(self, msg: discord.Message):
        try:
            await msg.delete()
        except (discord.NotFound, discord.Forbidden):
            pass

    def _append_status(self, member: discord.abc.User, state: str, error: str = ""):
        uname = (
            f"{member.name}#{getattr(member, 'discriminator', '0')}"
            if getattr(member, 'discriminator', '0') != "0" else member.name
        )
        self._results.append({
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "member_id": str(member.id),
            "username": uname,
            "state": state,
            "error": error
        })

    async def _flush_report(self, guild: discord.Guild):
        """Po dokončení pošle CSV report jako přílohu."""
        if not self._results:
            return
        csv_buffer = io.StringIO()
        writer = csv.DictWriter(csv_buffer, fieldnames=["ts", "member_id", "username", "state", "error"])
        writer.writeheader()
        writer.writerows(self._results)
        csv_buffer.seek(0)

        ch = await self._console_channel(guild)
        if not ch:
            return

        file = discord.File(
            fp=io.BytesIO(csv_buffer.getvalue().encode("utf-8")),
            filename=self.LOG_FILENAME
        )
        await ch.send(
            content=f"📊 Výsledky hromadného DM rozeslání ({len(self._results)} záznamů)",
            file=file
        )

    def _resolve_role(self, ctx: commands.Context, role_or_all: Optional[str]) -> Optional[discord.Role]:
        """Vrátí cíl: None = ALL, jinak konkrétní role."""
        if not role_or_all or role_or_all.upper() == "ALL":
            return None
        if ctx.message.role_mentions:
            return ctx.message.role_mentions[0]
        try:
            rid = int(role_or_all)
            return ctx.guild.get_role(rid)
        except:
            return discord.utils.get(ctx.guild.roles, name=role_or_all)

    def _parse_skip(self, ctx: commands.Context, tail: str) -> Tuple[Set[int], Set[int]]:
        """Vrátí (skip_users, skip_roles)."""
        skip_users: Set[int] = set()
        skip_roles: Set[int] = set()
        if not tail or "--skip" not in tail:
            return skip_users, skip_roles

        tail = tail.split("--skip", 1)[1].strip()
        tokens = tail.split()

        # Zpracuj zmínky
        for user in ctx.message.mentions:
            skip_users.add(user.id)
        for role in ctx.message.role_mentions:
            skip_roles.add(role.id)

        # Zpracuj tokeny
        for tok in tokens:
            if tok.startswith("<@") or tok.startswith("<@&"):
                continue
            if tok.isdigit():
                rid = int(tok)
                if ctx.guild.get_member(rid):
                    skip_users.add(rid)
                else:
                    found_role = ctx.guild.get_role(rid)
                    if found_role:
                        skip_roles.add(found_role.id)
                continue
            found_role = discord.utils.get(ctx.guild.roles, name=tok)
            if found_role:
                skip_roles.add(found_role.id)

        return skip_users, skip_roles

    async def _iter_targets(
        self,
        guild: discord.Guild,
        role: Optional[discord.Role],
        skip_users: Set[int],
        skip_roles: Set[int]
    ) -> Iterable[discord.Member]:
        """Iterátor přes cílové členy."""
        members = []
        try:
            async for m in guild.fetch_members(limit=None):
                members.append(m)
        except Exception:
            members = list(guild.members)

        for m in members:
            if m.bot or m.id in skip_users:
                continue
            if any(r.id in skip_roles for r in m.roles):
                continue
            if role is None or role in m.roles:
                yield m

    async def _check_rate_limit(self):
        """Zkontroluje, zda nepřekračujeme hodinový limit."""
        now = datetime.now()
        # Odstraň záznamy starší než hodinu
        self._dm_timestamps = [ts for ts in self._dm_timestamps if (now - ts).total_seconds() < 3600]
        
        if len(self._dm_timestamps) >= self.MAX_DMS_PER_HOUR:
            # Počkej, až nejstarší záznam bude starší než hodina
            oldest = min(self._dm_timestamps)
            wait_seconds = 3600 - (now - oldest).total_seconds()
            if wait_seconds > 0:
                logger.warning(f"Rate limit dosažen, čekám {wait_seconds:.0f} sekund")
                await asyncio.sleep(wait_seconds + 5)  # +5s buffer

    async def _sleep_safe_delay(self):
        """Extrémně dlouhá pauza mezi uživateli (3-5 minut)."""
        base = max(1.0, float(self.BASE_DELAY_SECONDS))
        jitter = float(self.JITTER_SECONDS)
        delta = random.uniform(-jitter, jitter) if jitter > 0 else 0.0
        total_delay = max(60.0, base + delta)  # minimálně 1 minuta
        await asyncio.sleep(total_delay)

    async def _batch_pause(self):
        """Dlouhá pauza po každých N zprávách."""
        pause_seconds = self.BATCH_PAUSE_MINUTES * 60
        logger.info(f"Batch pauza: {self.BATCH_PAUSE_MINUTES} minut")
        await asyncio.sleep(pause_seconds)

    async def _safe_send_dm(self, member: discord.Member, text: str) -> str:
        """Bezpečné odeslání DM s ochranou proti banu."""
        if self.DRY_RUN:
            self._append_status(member, "DRY_RUN")
            await self._sleep_safe_delay()
            return "DRY_RUN"

        # Kontrola rate limitu
        await self._check_rate_limit()

        wait = 3.0
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with self._sem:
                    dm = await member.create_dm()
                    await asyncio.wait_for(dm.send(text), timeout=self.TIMEOUT_PER_DM)
                    self._append_status(member, "SENT")
                    self._dm_timestamps.append(datetime.now())
                    self._sent_count += 1
                    
                    # Batch pauza každých N zpráv
                    if self._sent_count % self.PAUSE_AFTER_BATCH == 0:
                        await self._batch_pause()
                    else:
                        await self._sleep_safe_delay()
                    
                    return "SENT"
            except discord.Forbidden:
                self._append_status(member, "FORBIDDEN", "DMs disabled/privacy")
                await asyncio.sleep(5)  # krátká pauza i při chybě
                return "FORBIDDEN"
            except (discord.HTTPException, asyncio.TimeoutError) as e:
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, 30)
                else:
                    self._append_status(member, "FAILED", f"{type(e).__name__}: {e}")
                    await asyncio.sleep(10)  # pauza i při selhání
                    return "FAILED"
            except Exception as e:
                self._append_status(member, "FAILED", f"Unexpected: {e}")
                await asyncio.sleep(10)
                return "FAILED"

    @commands.command(name="notify")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 30, commands.BucketType.guild)
    async def notify(
        self,
        ctx: commands.Context,
        message: str,
        role_or_all: Optional[str] = None,
        *,
        rest: str = ""
    ):
        """
        Pošle DM všem nebo roli s maximální ochranou proti banu.
        !notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role ...]
        """
        await self._delete_message(ctx.message)

        if not ctx.guild:
            return await ctx.send("❌ Musíš to spustit na serveru.")

        role = self._resolve_role(ctx, role_or_all)
        skip_users, skip_roles = self._parse_skip(ctx, rest)

        self._results.clear()
        self._status_message = None
        self._sent_count = 0

        # Spočítej celkový počet cílů
        target_list = []
        async for member in self._iter_targets(ctx.guild, role, skip_users, skip_roles):
            target_list.append(member)
        
        total = len(target_list)
        
        if total == 0:
            return await ctx.send("❌ Žádní uživatelé k odeslání.")

        # Upozornění na čas
        avg_delay_minutes = (self.BASE_DELAY_SECONDS / 60)
        estimated_minutes = int(total * avg_delay_minutes)
        estimated_hours = estimated_minutes / 60
        
        confirm_msg = await ctx.send(
            f"⚠️ **Potvrzení hromadného rozesílání**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 Cílových uživatelů: **{total}**\n"
            f"🎯 Cíl: **{'ALL' if role is None else role.name}**\n"
            f"⏱️ Odhadovaný čas: **~{estimated_hours:.1f} hodin** ({estimated_minutes} minut)\n"
            f"⚡ Interval: **3-5 minut** mezi zprávami\n"
            f"🛡️ Ochrana: **Maximální** (rate limit + batch pauzy)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"Reaguj ✅ pro pokračování (60s timeout)"
        )
        
        await confirm_msg.add_reaction("✅")
        
        def check(reaction, user):
            return (user == ctx.author and 
                   str(reaction.emoji) == "✅" and 
                   reaction.message.id == confirm_msg.id)
        
        try:
            await self.bot.wait_for('reaction_add', timeout=60.0, check=check)
        except asyncio.TimeoutError:
            await confirm_msg.edit(content="❌ Timeout - rozesílání zrušeno.")
            return
        
        await confirm_msg.delete()

        await self._log(
            ctx.guild,
            f"📣 {ctx.author.display_name} spustil notify | cíl: {'ALL' if role is None else role.name} | "
            f"total={total} | skip_users={len(skip_users)}, skip_roles={len(skip_roles)} | "
            f"DRY_RUN={self.DRY_RUN} | delay={self.BASE_DELAY_SECONDS}±{self.JITTER_SECONDS}s"
        )

        sent = skipped = failed = 0
        
        for idx, member in enumerate(target_list, 1):
            state = await self._safe_send_dm(member, message)
            
            if state == "SENT":
                sent += 1
            elif state in ("DRY_RUN", "FORBIDDEN"):
                skipped += 1
            elif state == "FAILED":
                failed += 1
            else:
                skipped += 1
            
            # Live update každých 5 zpráv nebo na konci
            if idx % 5 == 0 or idx == total:
                remaining = total - idx
                eta = int(remaining * avg_delay_minutes)
                await self._update_status(ctx, sent, total, skipped, failed, eta)

        # Finální zpráva
        final_text = (
            f"✅ **Rozesílání dokončeno!**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"✅ Úspěšně odesláno: **{sent}** / {total}\n"
            f"⏭️ Přeskočeno: **{skipped}**\n"
            f"❌ Selhalo: **{failed}**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
        if self._status_message:
            await self._status_message.edit(content=final_text)
        else:
            await ctx.send(final_text)

        await self._log(
            ctx.guild,
            f"✅ Notify hotovo. SENT={sent}, SKIPPED={skipped}, FAILED={failed}"
        )
        await self._flush_report(ctx.guild)

    @notify.error
    async def _notify_error(self, ctx: commands.Context, error):
        try:
            await self._delete_message(ctx.message)
        except:
            pass
        guild = ctx.guild if ctx and ctx.guild else None
        if guild:
            await self._log(guild, f"❌ Notify error: {error}")
        else:
            logger.error(f"Notify error (mimo guild): {error}")

async def setup(bot: commands.Bot):
    await bot.add_cog(NotifyCog(bot))