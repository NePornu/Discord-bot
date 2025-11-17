# -*- coding: utf-8 -*-
from __future__ import annotations

import logging
import discord
from discord.ext import commands
from discord import app_commands, Interaction
import json
import os
import hashlib
import hmac
from datetime import datetime, timedelta
from collections import defaultdict
import asyncio

try:
    from config import GUILD_ID, MOD_CHANNEL_ID, WELCOME_CHANNEL_ID
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
except ImportError as e:
    logging.error(f"Chyba při načítání configů: {e}")
    raise

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Soubor pro uložení nastavení
SETTINGS_FILE = "verification_settings.json"

# Výchozí nastavení
DEFAULT_SETTINGS = {
    "bypass_password_hash": None,
    "max_attempts": 5,
    "attempt_timeout": 300,
    "verification_timeout": 600,
    "min_account_age_days": 7,
    "log_failed_attempts": True,
    "require_avatar": False,
}


def load_settings():
    """Načte nastavení ze souboru."""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                loaded = json.load(f)
                settings = DEFAULT_SETTINGS.copy()
                settings.update(loaded)
                return settings
        except Exception as e:
            logging.error(f"Chyba při načítání nastavení: {e}")
    return DEFAULT_SETTINGS.copy()


def save_settings(settings):
    """Uloží nastavení do souboru."""
    try:
        with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
        return True
    except Exception as e:
        logging.error(f"Chyba při ukládání nastavení: {e}")
        return False


def hash_password(password: str) -> str:
    """Vytvoří SHA-256 hash hesla."""
    return hashlib.sha256(password.encode('utf-8')).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    """Bezpečně porovná heslo s hashem."""
    return hmac.compare_digest(hash_password(password), password_hash)


class RemoveRoleView(discord.ui.View):
    """View s tlačítkem pro odebrání ověřovací role."""
    def __init__(self, target_user_id: int):
        super().__init__(timeout=None)
        self.target_user_id = target_user_id

    @discord.ui.button(label="Odebrat ověřovací roli", style=discord.ButtonStyle.green)
    async def remove_verification_role(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.user.guild_permissions.manage_roles:
            await interaction.response.send_message("Nemáš oprávnění odebírat roli.", ephemeral=True)
            return

        guild = interaction.guild
        role = guild.get_role(VERIFIED_ROLE_ID)
        member = guild.get_member(self.target_user_id)

        if not member or not role:
            await interaction.response.send_message("Nenašel jsem člena nebo roli.", ephemeral=True)
            return

        try:
            await member.remove_roles(role, reason=f"Verification approved by {interaction.user}")
            
            await interaction.response.edit_message(
                content=f"**Uživatel ověřen!**\n{member.mention} byl úspěšně ověřen moderátorem {interaction.user.mention}",
                view=None
            )
            
            logging.info(f"Uživatel {member} (ID: {member.id}) byl ověřen moderátorem {interaction.user} (ID: {interaction.user.id})")
        except Exception as e:
            await interaction.response.send_message(f"Nepodařilo se odebrat roli: {e}", ephemeral=True)
            logging.error(f"Chyba při odebrání role: {e}")


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = load_settings()
        self.verification_attempts = defaultdict(lambda: {"count": 0, "first_attempt": None, "locked_until": None})
        self.suspicious_activity = defaultdict(list)

    def is_rate_limited(self, user_id: int) -> tuple[bool, int]:
        """Kontroluje, zda je uživatel rate-limited."""
        attempts = self.verification_attempts[user_id]
        
        if attempts["locked_until"]:
            if datetime.now() < attempts["locked_until"]:
                remaining = int((attempts["locked_until"] - datetime.now()).total_seconds())
                return True, remaining
            else:
                attempts["count"] = 0
                attempts["first_attempt"] = None
                attempts["locked_until"] = None
        
        return False, 0

    def record_attempt(self, user_id: int, success: bool = False):
        """Zaznamenává pokus o ověření."""
        attempts = self.verification_attempts[user_id]
        
        if success:
            attempts["count"] = 0
            attempts["first_attempt"] = None
            attempts["locked_until"] = None
        else:
            if attempts["count"] == 0:
                attempts["first_attempt"] = datetime.now()
            
            attempts["count"] += 1
            
            if attempts["count"] >= self.settings["max_attempts"]:
                attempts["locked_until"] = datetime.now() + timedelta(seconds=self.settings["attempt_timeout"])
                logging.warning(f"Uživatel {user_id} překročil limit pokusů ({attempts['count']}), zamčeno na {self.settings['attempt_timeout']} sekund")
                
                self.suspicious_activity[user_id].append({
                    "timestamp": datetime.now(),
                    "type": "rate_limit_exceeded",
                    "attempts": attempts["count"]
                })

    async def check_user_security(self, member: discord.Member) -> tuple[bool, str]:
        """Kontroluje bezpečnostní kritéria pro nového uživatele."""
        issues = []
        
        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        if account_age < self.settings["min_account_age_days"]:
            issues.append(f"⚠️ Účet mladší než {self.settings['min_account_age_days']} dní (stáří: {account_age} dní)")
        
        if self.settings["require_avatar"] and member.avatar is None:
            issues.append("⚠️ Chybí profilový obrázek")
        
        if member.discriminator == "0" and not member.display_name:
            issues.append("⚠️ Výchozí uživatelské jméno")
        
        if issues:
            return False, "\n".join(issues)
        return True, ""

    verify_group = app_commands.Group(name="verify", description="Ověřování členů (DM kód, role, status)")

    @verify_group.command(name="send", description="Pošle uživateli DM s ověřovacím kódem.")
    @app_commands.describe(member="Uživatel, kterému poslat DM s kódem", hide="Ephemeral potvrzení v kanále")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_send(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        try:
            message = (
                f"**Ověření účtu**\n\n"
                f"Ahoj {member.mention}! Abychom věděli, že nejsi robot, pošli mi do této konverzace náš tajný kód:\n\n"
                f"**{VERIFICATION_CODE}**\n\n"
                f"Jakmile ho zadáš správně, moderátoři tě ověří a zpřístupní se ti server!"
            )
            await member.send(message)
            await itx.followup.send(f"📨 DM s kódem odesláno uživateli {member.mention}.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Nelze poslat DM: {e}", ephemeral=True)

    @verify_group.command(name="resend", description="Znovu pošle ověřovací DM vybranému uživateli.")
    @app_commands.describe(member="Uživatel pro opětovné odeslání", hide="Ephemeral potvrzení")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_resend(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await self.verify_send.callback(self, itx, member=member, hide=hide)

    @verify_group.command(name="approve", description="Odebere ověřovací roli uživateli (rychlá moderace).")
    @app_commands.describe(member="Uživatel k ověření (odebrání role)", hide="Ephemeral potvrzení")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def verify_approve(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        role = member.guild.get_role(VERIFIED_ROLE_ID) if member.guild else None
        if not role:
            return await itx.followup.send("❌ Ověřovací roli nelze najít.", ephemeral=True)
        if role not in member.roles:
            return await itx.followup.send("ℹ️ Tento uživatel ověřovací roli nemá.", ephemeral=True)
        try:
            await member.remove_roles(role, reason=f"Manual verification by {itx.user}")
            await itx.followup.send(f"✅ Odebírám ověřovací roli uživateli {member.mention}.", ephemeral=hide)
            logging.info(f"Manual verification: {member} (ID: {member.id}) by {itx.user}")
        except Exception as e:
            await itx.followup.send(f"❌ Chyba při odebírání role: {e}", ephemeral=True)

    @verify_group.command(name="status", description="Zobrazí, zda má člen ověřovací roli.")
    @app_commands.describe(member="Uživatel ke kontrole", hide="Ephemeral odpověď")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_status(self, itx: Interaction, member: discord.Member, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        role = member.guild.get_role(VERIFIED_ROLE_ID) if member.guild else None
        if not role:
            return await itx.followup.send("❌ Ověřovací role nebyla nalezena.", ephemeral=True)
        has_role = role in member.roles
        
        account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        security_check, issues = await self.check_user_security(member)
        
        status_msg = f"🔎 {member.mention} **{'má' if has_role else 'nemá'}** ověřovací roli ({role.mention}).\n"
        status_msg += f"📅 Stáří účtu: {account_age} dní\n"
        if not security_check:
            status_msg += f"\n{issues}"
        
        await itx.followup.send(status_msg, ephemeral=hide)

    @verify_group.command(name="ping", description="Pošle zkušební ověřovací DM tobě.")
    @app_commands.describe(hide="Ephemeral potvrzení v kanále")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_ping(self, itx: Interaction, hide: bool = True):
        await itx.response.defer(ephemeral=hide)
        try:
            message = (
                f"**Ověření účtu (TEST)**\n\n"
                f"Ahoj {itx.user.mention}! Abychom věděli, že nejsi robot, pošli mi do této konverzace náš tajný kód:\n\n"
                f"**{VERIFICATION_CODE}**\n\n"
                f"Jakmile ho zadáš správně, moderátoři tě ověří a zpřístupní se ti server!"
            )
            await itx.user.send(message)
            await itx.followup.send("📨 Zkušební DM odesláno.", ephemeral=hide)
        except Exception as e:
            await itx.followup.send(f"❌ Nelze poslat testovací DM: {e}", ephemeral=True)

    @verify_group.command(name="suspicious", description="Zobrazí seznam podezřelé aktivity.")
    @app_commands.checks.has_permissions(administrator=True)
    async def verify_suspicious(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        
        if not self.suspicious_activity:
            return await itx.followup.send("✅ Žádná podezřelá aktivita.", ephemeral=True)
        
        msg = "🚨 **Podezřelá aktivita:**\n\n"
        for user_id, activities in list(self.suspicious_activity.items())[-10:]:
            user = self.bot.get_user(user_id)
            username = user.name if user else f"ID: {user_id}"
            msg += f"**{username}**\n"
            for activity in activities[-3:]:
                msg += f"  • {activity['type']} - {activity['timestamp'].strftime('%H:%M:%S')}\n"
            msg += "\n"
        
        await itx.followup.send(msg, ephemeral=True)

    settings_group = app_commands.Group(name="verifysettings", description="Nastavení ověřovacího systému")

    @settings_group.command(name="setpassword", description="Nastaví bypass heslo pro okamžité ověření.")
    @app_commands.describe(password="Heslo (nebo 'none' pro vypnutí)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_password(self, itx: Interaction, password: str):
        await itx.response.defer(ephemeral=True)
        if password.lower() == "none":
            self.settings["bypass_password_hash"] = None
            await itx.followup.send("✅ Bypass heslo bylo vypnuto.", ephemeral=True)
        else:
            if len(password) < 8:
                return await itx.followup.send("❌ Heslo musí mít alespoň 8 znaků!", ephemeral=True)
            
            self.settings["bypass_password_hash"] = hash_password(password)
            await itx.followup.send(
                f"✅ Bypass heslo bylo bezpečně uloženo (SHA-256 hash).\n"
                f"⚠️ Toto heslo je tajné a nebude zobrazeno uživatelům!\n"
                f"💡 Původní heslo: `{password}` (zapiš si ho, hash nelze dekódovat)",
                ephemeral=True
            )
        save_settings(self.settings)

    @settings_group.command(name="setmaxattempts", description="Nastaví max. počet pokusů před zamčením.")
    @app_commands.describe(attempts="Počet pokusů (doporučeno 3-5)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_max_attempts(self, itx: Interaction, attempts: int):
        await itx.response.defer(ephemeral=True)
        if attempts < 1 or attempts > 10:
            return await itx.followup.send("❌ Počet pokusů musí být mezi 1-10.", ephemeral=True)
        
        self.settings["max_attempts"] = attempts
        save_settings(self.settings)
        await itx.followup.send(f"✅ Max. počet pokusů nastaven na: {attempts}", ephemeral=True)

    @settings_group.command(name="setaccountage", description="Nastaví minimální stáří účtu v dnech.")
    @app_commands.describe(days="Počet dní (0 = vypnuto, doporučeno 7-30)")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_account_age(self, itx: Interaction, days: int):
        await itx.response.defer(ephemeral=True)
        if days < 0 or days > 365:
            return await itx.followup.send("❌ Počet dní musí být mezi 0-365.", ephemeral=True)
        
        self.settings["min_account_age_days"] = days
        save_settings(self.settings)
        await itx.followup.send(f"✅ Min. stáří účtu nastaveno na: {days} dní", ephemeral=True)

    @settings_group.command(name="requireavatar", description="Vyžadovat profilový obrázek (anti-bot).")
    @app_commands.describe(required="True = vyžadovat avatar")
    @app_commands.checks.has_permissions(administrator=True)
    async def require_avatar(self, itx: Interaction, required: bool):
        await itx.response.defer(ephemeral=True)
        self.settings["require_avatar"] = required
        save_settings(self.settings)
        status = "zapnuto" if required else "vypnuto"
        await itx.followup.send(f"✅ Vyžadování avataru: {status}", ephemeral=True)

    @settings_group.command(name="view", description="Zobrazí aktuální nastavení.")
    @app_commands.checks.has_permissions(administrator=True)
    async def view_settings(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        password_status = "✅ Nastaveno (hash)" if self.settings.get("bypass_password_hash") else "❌ Vypnuto"
        
        message = (
            f"**🔧 Aktuální bezpečnostní nastavení:**\n\n"
            f"**Bypass heslo:** {password_status}\n"
            f"**Max. pokusů:** {self.settings['max_attempts']}\n"
            f"**Timeout po selhání:** {self.settings['attempt_timeout']}s\n"
            f"**Timeout ověření:** {self.settings['verification_timeout']}s\n"
            f"**Min. stáří účtu:** {self.settings['min_account_age_days']} dní\n"
            f"**Vyžadovat avatar:** {'✅ Ano' if self.settings['require_avatar'] else '❌ Ne'}\n"
            f"**Logování pokusů:** {'✅ Ano' if self.settings['log_failed_attempts'] else '❌ Ne'}"
        )
        await itx.followup.send(message, ephemeral=True)

    @settings_group.command(name="reset", description="Resetuje nastavení na výchozí hodnoty.")
    @app_commands.checks.has_permissions(administrator=True)
    async def reset_settings(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        self.settings = DEFAULT_SETTINGS.copy()
        save_settings(self.settings)
        await itx.followup.send("✅ Nastavení bylo resetováno na výchozí hodnoty.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Přidání dočasné ověřovací role, DM s kódem a případně info do mod kanálu."""
        guild = self.bot.get_guild(GUILD_ID)
        if not guild or member.guild.id != GUILD_ID:
            logging.error(f"Nepodařilo se najít guildu s ID {GUILD_ID}.")
            return

        security_ok, security_issues = await self.check_user_security(member)
        
        role = guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
                logging.debug(f"Role {VERIFIED_ROLE_ID} byla přidána uživateli {member}.")
            except Exception as e:
                logging.warning(f"Chyba při přidávání role: {e}")

        mod_channel = guild.get_channel(MOD_CHANNEL_ID)
        if mod_channel:
            created_at_relative = discord.utils.format_dt(member.created_at, style='R')
            created_at_full = discord.utils.format_dt(member.created_at, style='F')
            account_age = (datetime.now(member.created_at.tzinfo) - member.created_at).days
            
            avatar_url = member.display_avatar.url if member.avatar else "Avatar není dostupné"
            
            bio = "Bio není dostupné"
            try:
                user_profile = await member.fetch()
                if hasattr(user_profile, 'bio') and user_profile.bio:
                    bio = user_profile.bio
            except:
                pass
            
            new_member_msg = (
                f"**Nový uživatel se připojil na server!**\n\n"
                f"**Uživatel:** {member.mention} ({member.name})\n"
                f"**ID:** {member.id}\n"
                f"**Účet vytvořen:** {created_at_relative} • {created_at_full} (před {account_age} dny)\n"
                f"**Avatar:** {avatar_url}\n"
                f"**Bio:** {bio}\n\n"
                f"Automaticky mu byla přidělena ověřovací role."
            )
            
            if not security_ok:
                new_member_msg += f"\n\n⚠️ **Bezpečnostní varování:**\n{security_issues}"
            
            await mod_channel.send(new_member_msg)

        if not security_ok:
            self.suspicious_activity[member.id].append({
                "timestamp": datetime.now(),
                "type": "security_check_failed",
                "issues": security_issues
            })

        try:
            message = (
                f"**Ověření účtu**\n\n"
                f"Ahoj {member.mention}! Abychom věděli, že nejsi robot, pošli mi do této konverzace náš tajný kód:\n\n"
                f"**{VERIFICATION_CODE}**\n\n"
                f"Jakmile ho zadáš správně, moderátoři tě ověří a zpřístupní se ti server!"
            )
            await member.send(message)
        except Exception as e:
            logging.warning(f"Nelze poslat DM uživateli {member}: {e}")
            return

        def check(msg: discord.Message):
            return msg.author == member and isinstance(msg.channel, discord.DMChannel)

        start_time = datetime.now()
        
        while True:
            try:
                elapsed = (datetime.now() - start_time).total_seconds()
                remaining_timeout = self.settings["verification_timeout"] - elapsed
                
                if remaining_timeout <= 0:
                    await member.send("⏱️ Čas na ověření vypršel. Kontaktuj prosím moderátory.")
                    logging.warning(f"Verification timeout pro {member}")
                    break
                
                response = await self.bot.wait_for("message", check=check, timeout=min(remaining_timeout, 60))
                user_input = response.content.strip()
                
                is_limited, wait_time = self.is_rate_limited(member.id)
                if is_limited:
                    await member.send(f"🛑 Příliš mnoho pokusů! Zkus to znovu za {wait_time} sekund.")
                    continue
                
                if self.settings.get("bypass_password_hash") and verify_password(user_input, self.settings["bypass_password_hash"]):
                    try:
                        await member.remove_roles(role, reason="Bypass password used")
                        self.record_attempt(member.id, success=True)
                        
                        await member.send("**Skvělé!**\n\nZadal jsi správný kód! Byl jsi okamžitě ověřen. Nyní máš přístup ke všem kanálům. Těšíme se na tvou účast v komunitě!")
                        
                        logging.info(f"Uživatel {member} použil bypass heslo a byl okamžitě ověřen.")
                        break
                    except Exception as e:
                        logging.error(f"Chyba při odebrání role pro {member}: {e}")
                        break
                
                elif user_input.upper() == VERIFICATION_CODE.upper():
                    self.record_attempt(member.id, success=True)
                    
                    if mod_channel:
                        view = RemoveRoleView(member.id)
                        await mod_channel.send(
                            f"✅ {member.mention} zadal správný ověřovací kód!",
                            view=view
                        )

                    await member.send("**Skvělé!**\n\nZadal jsi správný kód! Počkej prosím, než tě moderátoři ověří. Dostaneš zprávu, jakmile budeš moci používat server.")
                    break
                else:
                    self.record_attempt(member.id, success=False)
                    attempts_left = self.settings["max_attempts"] - self.verification_attempts[member.id]["count"]
                    
                    if self.settings["log_failed_attempts"]:
                        logging.warning(f"Neúspěšný pokus o ověření: {member} (ID: {member.id}), zbývá pokusů: {attempts_left}")
                    
                    await member.send(f"❌ **Špatný kód!**\n\nZkus to prosím znovu. Zbývá pokusů: {attempts_left}")
            except asyncio.TimeoutError:
                if (datetime.now() - start_time).total_seconds() >= self.settings["verification_timeout"]:
                    await member.send("⏱️ Čas na ověření vypršel. Kontaktuj prosím moderátory.")
                    logging.warning(f"Verification timeout pro {member}")
                    break
            except Exception as e:
                logging.error(f"Chyba při zpracování kódu od uživatele {member}: {e}")
                break

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        """Jakmile dojde k odebrání ověřovací role, je uživatel oficiálně ověřen."""
        before_roles = {r.id for r in before.roles}
        after_roles = {r.id for r in after.roles}

        if VERIFIED_ROLE_ID in before_roles and VERIFIED_ROLE_ID not in after_roles:
            try:
                await after.send("**Vítej na serveru!**\n\nTvůj účet byl úspěšně ověřen! Nyní máš přístup ke všem kanálům. Těšíme se na tvou účast v komunitě!")
            except Exception as e:
                logging.warning(f"Nelze poslat DM o ověření uživateli {after}: {e}")

            guild = after.guild
            welcome_channel = guild.get_channel(WELCOME_CHANNEL_ID)
            if welcome_channel:
                await welcome_channel.send(
                    f"Nový člen se k nám připojil! Všichni přivítejme {after.mention}! "
                    f"Nezapomeň se podívat do ⁠📗pravidla a ⁠ℹ️úvod Můžeš se představit v ⁠👋představ-se"
                )

            logging.info(f"Uživatel {after} byl ověřen odebráním role.")


async def setup(bot: commands.Bot):
    """Načtení cogu (pro discord.py 2.x)."""
    await bot.add_cog(VerificationCog(bot))
