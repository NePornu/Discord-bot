# commands/notify.py
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
    Hromadné DM oznámení s:
      - ultra-safe rozestupy (minuty + náhodný jitter),
      - logem do log kanálu (config.CONSOLE_CHANNEL_ID),
      - CSV reportem jako přílohou (nic se neukládá na disk),
      - cílením na ALL nebo konkrétní roli,
      - volitelným --skip (uživatelé/role).

    Použití:
      !notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role ...]

    Příklady:
      !notify "Server byl uzavřen Discordem. Nové místo: https://discord.gg/XXXX" ALL
      !notify "Info jen pro ověřené" @Ověřený --skip @Admin 123456789012345678
    """

    # ==== KONFIGURACE (klidně uprav) ====
    DRY_RUN             = False      # True = neposílat, jen simulovat a logovat
    BASE_DELAY_SECONDS  = 90         # základní pauza mezi DM (např. 90 s)
    JITTER_SECONDS      = 30         # náhodný +/- jitter (např. 30 s)
    MAX_CONCURRENCY     = 1          # nech 1 (bezpečné)
    MAX_RETRIES         = 3          # retry pro jednotlivé DM
    TIMEOUT_PER_DM      = 20         # timeout odeslání DM (s)
    ERROR_TIMEOUT       = 60         # mazání případných chybových echo zpráv (s)

    LOG_FILENAME        = "dm_status_report.csv"  # jen název přílohy (neukládá se na disk)
    # ====================================

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._sem = asyncio.Semaphore(self.MAX_CONCURRENCY)
        self._results = []  # in-memory výsledky pro CSV export (žádný soubor na disku)

    # ========== HELPERY ==========

    async def _console_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        """Získá log kanál podle config.CONSOLE_CHANNEL_ID."""
        try:
            import config
            return guild.get_channel(getattr(config, "CONSOLE_CHANNEL_ID", 0))
        except Exception:
            return None

    async def _log(self, guild: discord.Guild, msg: str):
        """Pošle log do log kanálu + do loggeru (codeblock, chunkování)."""
        ch = await self._console_channel(guild)
        full = f"{datetime.now().strftime('[%Y-%m-%d %H:%M:%S]')} {msg}"
        if ch:
            try:
                for i in range(0, len(full), 1900):
                    await ch.send(f"```{full[i:i+1900]}```")
            except Exception as e:
                logger.warning(f"Log do kanálu selhal: {e}")
        logger.info(full)

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
        """Po dokončení pošle CSV report jako přílohu do log kanálu (neukládá se na disk)."""
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
        """
        Vrátí (skip_users, skip_roles).
        Podporuje @zmínky, ID, názvy rolí. Příklad tailu: '--skip @Uživatel @Role 1234567890'
        """
        skip_users: Set[int] = set()
        skip_roles: Set[int] = set()
        if not tail or "--skip" not in tail:
            return skip_users, skip_roles

        tail = tail.split("--skip", 1)[1].strip()
        tokens = tail.split()

        # mentions
        for user in ctx.message.mentions:
            skip_users.add(user.id)
        for role in ctx.message.role_mentions:
            skip_roles.add(role.id)

        # zbytek tokenů
        for tok in tokens:
            if tok.startswith("<@") or tok.startswith("<@&"):
                continue
            if tok.isdigit():
                rid = int(tok)
                if ctx.guild.get_member(rid):
                    skip_users.add(rid)
                elif (r := ctx.guild.get_role(rid)):
                    skip_roles.add(r.id)
                continue
            r = discord.utils.get(ctx.guild.roles, name=tok)
            if r:
                skip_roles.add(r.id)

        return skip_users, skip_roles

    async def _iter_targets(
        self,
        guild: discord.Guild,
        role: Optional[discord.Role],
        skip_users: Set[int],
        skip_roles: Set[int]
    ) -> Iterable[discord.Member]:
        """Líný iterátor přes cílové členy (ALL/role), s vynecháním skipů a botů."""
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

    async def _sleep_safe_delay(self):
        """Dlouhá, náhodně jitterovaná pauza mezi uživateli (ultra-safe)."""
        base = max(1.0, float(self.BASE_DELAY_SECONDS))
        jitter = float(self.JITTER_SECONDS)
        delta = random.uniform(-jitter, jitter) if jitter > 0 else 0.0
        await asyncio.sleep(max(1.0, base + delta))

    async def _safe_send_dm(self, member: discord.Member, text: str) -> str:
        """Bezpečné odeslání DM s retry, loggingem a oddělovací pauzou."""
        if self.DRY_RUN:
            self._append_status(member, "DRY_RUN")
            await self._sleep_safe_delay()
            return "DRY_RUN"

        wait = 2.0  # krátký backoff pro retry; dlouhý inter-user delay je zvlášť
        for attempt in range(1, self.MAX_RETRIES + 1):
            try:
                async with self._sem:
                    dm = await member.create_dm()
                    await asyncio.wait_for(dm.send(text), timeout=self.TIMEOUT_PER_DM)
                    self._append_status(member, "SENT")
                    await self._sleep_safe_delay()
                    return "SENT"
            except discord.Forbidden:
                self._append_status(member, "FORBIDDEN", "DMs disabled/privacy")
                await self._sleep_safe_delay()
                return "FORBIDDEN"
            except (discord.HTTPException, asyncio.TimeoutError) as e:
                if attempt < self.MAX_RETRIES:
                    await asyncio.sleep(wait)
                    wait = min(wait * 2, 30)
                else:
                    self._append_status(member, "FAILED", f"{type(e).__name__}: {e}")
                    await self._sleep_safe_delay()
                    return "FAILED"
            except Exception as e:
                self._append_status(member, "FAILED", f"Unexpected: {e}")
                await self._sleep_safe_delay()
                return "FAILED"

    # ========== PŘÍKAZ ==========

    @commands.command(name="notify")
    @commands.has_permissions(administrator=True)
    @commands.cooldown(1, 15, commands.BucketType.guild)
    async def notify(
        self,
        ctx: commands.Context,
        message: str,
        role_or_all: Optional[str] = None,
        *,
        rest: str = ""
    ):
        """
        Pošle DM (ALL/role). Volitelně --skip pro vynechání userů/rolí.
        !notify "zpráva" [@role|role_id|ALL] [--skip @uživatel @role ...]
        """
        await self._delete_message(ctx.message)

        if not ctx.guild:
            return await ctx.send("❌ Musíš to spustit na serveru.")

        role = self._resolve_role(ctx, role_or_all)
        skip_users, skip_roles = self._parse_skip(ctx, rest)

        self._results.clear()  # čistý běh

        await self._log(
            ctx.guild,
            f"📣 {ctx.author.display_name} spustil notify | cíl: {'ALL' if role is None else role.name} | "
            f"skip_users={len(skip_users)}, skip_roles={len(skip_roles)} | "
            f"DRY_RUN={self.DRY_RUN} | delay≈{self.BASE_DELAY_SECONDS}±{self.JITTER_SECONDS}s"
        )

        sent = skipped = failed = 0
        async for member in self._iter_targets(ctx.guild, role, skip_users, skip_roles):
            state = await self._safe_send_dm(member, message)
            if state == "SENT":
                sent += 1
            elif state in ("DRY_RUN", "FORBIDDEN"):
                skipped += 1
            elif state == "FAILED":
                failed += 1
            else:
                # SKIP_SENT už nepoužíváme (bez perzistence), ale kdyby se objevil:
                skipped += 1

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

