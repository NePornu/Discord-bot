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
import random
import string
import asyncio
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Dict, List, Iterable

# --- Globals & Configs ---
try:
    from config import GUILD_ID, MOD_CHANNEL_ID, WELCOME_CHANNEL_ID, BOT_PREFIX
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
except ImportError:
    logging.warning("⚠️ Config import failed, using defaults.")
    GUILD_ID = None
    MOD_CHANNEL_ID = None
    WELCOME_CHANNEL_ID = None
    VERIFICATION_CODE = "123456"
    VERIFIED_ROLE_ID = None
    BOT_PREFIX = "!"

SETTINGS_FILE = "data/verification_settings.json"
STATE_FILE = "data/verification_state.json"
DEFAULT_SETTINGS_DATA = {
    "bypass_password_hash": None,
    "max_attempts": 5,
    "attempt_timeout": 300,        # 5 minut po X pokusech
    "verification_timeout": 86400, # 24 hodin na dokončení
    "min_account_age_days": 7,
    "log_failed_attempts": True,
    "require_avatar": False,
}

# --- Helpers ---
def chunked(seq: Iterable, n: int) -> Iterable[list]:
    """Helper pro safe batching"""
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

def generate_otp(length=6) -> str:
    """Generuje náhodný alfanumerický kód (velká písmena + čísla)"""
    chars = string.ascii_uppercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode('utf-8')).hexdigest()

def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash: return False
    return hmac.compare_digest(hash_password(password), password_hash)

# --- Views ---
class WarnUserModal(discord.ui.Modal, title="⚠️ Upozornit uživatele"):
    def __init__(self, user: discord.User, parent_view):
        super().__init__()
        self.user = user
        self.parent_view = parent_view
        self.reason = discord.ui.TextInput(
            label="Důvod upozornění", 
            placeholder="Např. Nevhodný avatar / Změň si nick...", 
            style=discord.TextStyle.paragraph,
            max_length=500
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            msg = (
                f"⚠️ **Upozornění od moderátora**\n\n"
                f"Zdravím, moderátoři si všimli problému, který je potřeba vyřešit před dokončením ověření:\n\n"
                f"> {self.reason.value}\n\n"
                f"Prosím o nápravu. Pokud potřebuješ pomoc, kontaktuj nás."
            )
            await self.user.send(msg)
            await interaction.followup.send(f"✅ Upozornění odesláno uživateli {self.user.name}.")
            
            # Log do mod kanálu - aktualizace statusu?
            # Zatím jen log
            logging.info(f"MOD WARN for {self.user.id}: {self.reason.value}")
        except Exception as e:
            await interaction.followup.send(f"❌ Nepodařilo se poslat DM: {e}")

class VerificationModView(discord.ui.View):
    def __init__(self, bot: commands.Bot, member_id: int):
        super().__init__(timeout=None)
        self.bot = bot
        self.member_id = member_id

    async def get_member(self, guild: discord.Guild) -> Optional[discord.Member]:
        return guild.get_member(self.member_id)

    @discord.ui.button(label="Schválit (Bypass)", style=discord.ButtonStyle.success, emoji="✅", custom_id="verif_approve")
    async def btn_approve(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        member = await self.get_member(interaction.guild)
        if not member:
            return await interaction.followup.send("❌ Uživatel už není na serveru.", ephemeral=True)
        
        role = interaction.guild.get_role(VERIFIED_ROLE_ID)
        if not role:
            return await interaction.followup.send("❌ Role VERIFIED nenalezena.", ephemeral=True)
        
        try:
            await member.remove_roles(role, reason=f"Manual approve by {interaction.user}")
            await interaction.followup.send(f"✅ **{member.display_name}** byl manuálně schválen moderátorem {interaction.user.mention}.")
            # DM user
            try:
                await member.send("✅ Tvé ověření bylo schváleno moderátorem! Vítej.")
            except: pass
            
            # Disable buttons
            self.stop()
            for child in self.children:
                child.disabled = True
            await interaction.message.edit(view=self)
            
            # Clean state
            cog = self.bot.get_cog("VerificationCog")
            if cog:
                cog.cleanup_state(self.member_id)
                
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba: {e}", ephemeral=True)

    @discord.ui.button(label="Upozornit", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="verif_warn")
    async def btn_warn(self, interaction: Interaction, button: discord.ui.Button):
        member = await self.get_member(interaction.guild)
        if not member:
            return await interaction.response.send_message("❌ Uživatel už není na serveru.", ephemeral=True)
        await interaction.response.send_modal(WarnUserModal(member, self))

    @discord.ui.button(label="Vyhodit (Kick)", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="verif_kick")
    async def btn_kick(self, interaction: Interaction, button: discord.ui.Button):
        member = await self.get_member(interaction.guild)
        if not member:
            return await interaction.response.send_message("❌ Uživatel už není na serveru.", ephemeral=True)
            
        # Confirmation? Direct kick for now.
        if not interaction.user.guild_permissions.kick_members:
             return await interaction.response.send_message("❌ Nemáš právo vyhazovat.", ephemeral=True)

        await interaction.response.defer()
        try:
            await member.kick(reason=f"Verification Kick by {interaction.user}")
            await interaction.followup.send(f"🚪 **{member.display_name}** byl vyhozen.")
            self.stop()
            for child in self.children: child.disabled = True
            await interaction.message.edit(view=self)
            
            cog = self.bot.get_cog("VerificationCog")
            if cog: cog.cleanup_state(self.member_id)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba při kicku: {e}", ephemeral=True)


# --- Main Cog ---
class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.settings = DEFAULT_SETTINGS_DATA.copy()
        self.state: Dict[str, dict] = {} # str(user_id) -> {otp, attempts, timestamp}
        self.mod_messages: Dict[int, int] = {} # user_id -> message_id (in mod channel)
        
        # Load
        if not os.path.exists("data"): os.makedirs("data")
        self.load_settings()
        self.bot.loop.create_task(self.load_state())

    # --- Persistence ---
    def load_settings(self):
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    self.settings.update(json.load(f))
            except Exception as e:
                logging.error(f"Settings load error: {e}")

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=4)
        except Exception as e:
            logging.error(f"Settings save error: {e}")

    async def load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                text = await self.bot.loop.run_in_executor(None, lambda: open(STATE_FILE, 'r').read())
                self.state = json.loads(text)
                logging.info(f"Loaded verification state for {len(self.state)} users.")
            except Exception as e:
                logging.error(f"State load error: {e}")

    async def save_state(self):
        try:
            await self.bot.loop.run_in_executor(None, lambda: open(STATE_FILE, 'w').write(json.dumps(self.state)))
        except Exception as e:
            logging.error(f"State save error: {e}")

    def cleanup_state(self, user_id: int):
        sid = str(user_id)
        if sid in self.state:
            del self.state[sid]
            self.bot.loop.create_task(self.save_state())
        
        # Remove from mod_messages tracking logic (optional clean up)
        if user_id in self.mod_messages:
            del self.mod_messages[user_id]

    def get_user_state(self, user_id: int) -> dict:
        sid = str(user_id)
        if sid not in self.state:
            # Create new session
            self.state[sid] = {
                "otp": generate_otp(),
                "attempts": 0,
                "created_at": datetime.now().timestamp(),
                "locked_until": 0
            }
            self.bot.loop.create_task(self.save_state())
        return self.state[sid]

    def update_user_state(self, user_id: int, **kwargs):
        sid = str(user_id)
        if sid in self.state:
            self.state[sid].update(kwargs)
            self.bot.loop.create_task(self.save_state())

    # --- Logic ---
    async def check_security(self, member: discord.Member) -> tuple[bool, str]:
        issues = []
        age_days = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        if age_days < self.settings["min_account_age_days"]:
            issues.append(f"• Účet je příliš nový ({age_days} dní). Min: {self.settings['min_account_age_days']}")
        if self.settings["require_avatar"] and not member.avatar:
            issues.append("• Chybí profilový obrázek.")
        
        return (len(issues) == 0), "\n".join(issues)

    async def send_verification_dm(self, member: discord.Member, otp: str):
        msg = (
            f"**🔒 Ověření účtu**\n\n"
            f"Ahoj **{member.name}**! Vítej na serveru.\n"
            f"Pro dokončení ověření prosím pošli sem do chatu tento kód:\n\n"
            f"> **`{otp}`**\n\n"
            f"*(Máš na to 24 hodin. Pokud kód nefunguje, můžeš použít příkaz `/reverify resend` na serveru)*"
        )
        await member.send(msg)

    # --- Events ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        
        # 1. Add Role
        role = member.guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try:
                await member.add_roles(role)
            except discord.Forbidden:
                logging.error(f"Missing permissions to add role {role.name}")

        # 2. State & OTP
        st = self.get_user_state(member.id)
        otp = st["otp"]
        
        # 3. Security Check
        sec_ok, sec_reason = await self.check_security(member)
        
        # 4. Mod Log with GUI
        mod_ch = member.guild.get_channel(MOD_CHANNEL_ID)
        if mod_ch:
            status_icon = "🟢" if sec_ok else "🟠"
            desc = (
                f"**Nový uživatel:** {member.mention} (`{member.id}`)\n"
                f"**Účet založen:** <t:{int(member.created_at.timestamp())}:R>\n"
                f"**Status:** {status_icon} {'OK' if sec_ok else 'Podezřelý'}\n"
            )
            if not sec_ok:
                desc += f"\n⚠ **Nálezy:**\n{sec_reason}"
            
            # View
            view = VerificationModView(self.bot, member.id)
            try:
                m = await mod_ch.send(desc, view=view)
                self.mod_messages[member.id] = m.id
            except: pass

        # 5. DM
        try:
            await self.send_verification_dm(member, otp)
        except discord.Forbidden:
            if mod_ch: await mod_ch.send(f"❌ Nepodařilo se poslat DM uživateli {member.mention} (Blocked DMs).")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        # Alert mods if pending user leaves
        if str(member.id) in self.state:
            # It was a pending verification
            if member.id in self.mod_messages:
                # Find log message
                mod_ch = member.guild.get_channel(MOD_CHANNEL_ID)
                if mod_ch:
                    try:
                        msg_id = self.mod_messages[member.id]
                        msg = await mod_ch.fetch_message(msg_id)
                        await msg.reply(f"❌ **{member.display_name}** opustil server během verifikace.")
                        # Disable view on original
                        await msg.edit(view=None)
                    except: pass
            
            # Clean
            self.cleanup_state(member.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild: return
        
        # Check if user is in pending state
        sid = str(message.author.id)
        if sid not in self.state: return
        
        st = self.state[sid]
        
        # Check lock
        if st["locked_until"] > datetime.now().timestamp():
            wait = int(st["locked_until"] - datetime.now().timestamp())
            await message.channel.send(f"⏳ Jsi dočasně zablokován pro příliš mnoho pokusů. Zkus to za {wait} sekund.")
            return

        user_input = message.content.strip()
        
        # Check logic
        success = False
        master_used = False
        
        # 1. Dynamic OTP
        if user_input == st["otp"]:
            success = True
        
        # 2. Master Code (fallback)
        elif VERIFICATION_CODE and user_input.upper() == VERIFICATION_CODE.upper():
            success = True
            master_used = True
            
        # 3. Admin Bypass
        elif self.settings["bypass_password_hash"] and verify_password(user_input, self.settings["bypass_password_hash"]):
            success = True
            master_used = True

        if success:
            # Find guild
            guild = self.bot.get_guild(GUILD_ID)
            if not guild: return # Should not happen
            member = guild.get_member(message.author.id)
            if not member:
                await message.channel.send("❌ Nejsi na serveru.")
                return 

            role = guild.get_role(VERIFIED_ROLE_ID)
            if role:
                try:
                    await member.remove_roles(role, reason="Verification Success")
                    await message.channel.send(f"✅ **Ověřeno!** Vítej na serveru, {member.display_name}.")
                    
                    # Log success
                    mod_ch = guild.get_channel(MOD_CHANNEL_ID)
                    if mod_ch and member.id in self.mod_messages:
                        try:
                            m = await mod_ch.fetch_message(self.mod_messages[member.id])
                            embed_flag = " (Master Pass)" if master_used else ""
                            await m.reply(f"✅ **{member.display_name}** úspěšně zadal kód{embed_flag}.")
                            await m.edit(view=None)
                        except: pass
                    
                    # Cleanup
                    self.cleanup_state(member.id)
                    
                except Exception as e:
                    await message.channel.send("❌ Chyba při odebírání role. Kontaktuj admina.")
                    logging.error(f"Remove role fail: {e}")
            else:
                await message.channel.send("❌ Chyba konfigurace role.")

        else:
            # Fail
            attempts = st["attempts"] + 1
            self.update_user_state(message.author.id, attempts=attempts)
            
            if attempts >= self.settings["max_attempts"]:
                 lock_time = datetime.now().timestamp() + self.settings["attempt_timeout"]
                 self.update_user_state(message.author.id, locked_until=lock_time, attempts=0)
                 await message.channel.send(f"⛔ **Špatný kód.** Příliš mnoho pokusů. Počkej {self.settings['attempt_timeout']} sekund.")
            else:
                 left = self.settings["max_attempts"] - attempts
                 await message.channel.send(f"❌ **Špatný kód.** Zkus to znovu. Zbývá pokusů: {left}")

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
         # Welcome msg when verified role removed
         if VERIFIED_ROLE_ID:
            has_before = any(r.id == VERIFIED_ROLE_ID for r in before.roles)
            has_after = any(r.id == VERIFIED_ROLE_ID for r in after.roles)
            
            if has_before and not has_after:
                # Verified!
                # Send welcome to welcome channel
                if WELCOME_CHANNEL_ID:
                    ch = after.guild.get_channel(WELCOME_CHANNEL_ID)
                    if ch:
                        await ch.send(f"👋 **Vítej {after.mention}!** Jsme rádi že jsi tady.")

    # --- Slash Commands: Verify ---
    verify_group = app_commands.Group(name="verify", description="Příkazy pro ověření")

    @verify_group.command(name="ping", description="Pošle ti testovací DM s OTP.")
    async def verify_ping(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        # Generate dummy OTP
        otp = generate_otp()
        try:
             await self.send_verification_dm(itx.user, otp)
             await itx.followup.send("✅ Testovací DM odesláno.")
        except:
             await itx.followup.send("❌ Nelze poslat DM.")

    @verify_group.command(name="status", description="Stav verifikace uživatele.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_status(self, itx: Interaction, member: discord.Member):
        st = self.state.get(str(member.id))
        if not st:
            await itx.response.send_message("❌ Tento uživatel nemá aktivní verifikační relaci.", ephemeral=True)
        else:
            wait = max(0, int(st.get("locked_until", 0) - datetime.now().timestamp()))
            msg = (
                f"📊 **Stav verifikace: {member.display_name}**\n"
                f"OTP: `{st.get('otp')}`\n"
                f"Pokusy: {st.get('attempts')}/{self.settings['max_attempts']}\n"
            )
            if wait > 0: msg += f"🔒 Zamčeno na: {wait}s\n"
            await itx.response.send_message(msg, ephemeral=True)

    @verify_group.command(name="manual", description="Manuálně spustit ověření pro uživatele (DM).")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def verify_manual(self, itx: Interaction, member: discord.Member):
        await itx.response.defer(ephemeral=True)
        st = self.get_user_state(member.id)
        try:
            await self.send_verification_dm(member, st["otp"])
            await itx.followup.send(f"✅ DM odesláno uživateli {member.display_name}.")
        except Exception as e:
            await itx.followup.send(f"❌ Chyba: {e}")

    # --- Slash Commands: Reverification (Unified) ---
    reverify = app_commands.Group(name="reverify", description="Hromadná re-verifikace")

    @reverify.command(name="status", description="Zobrazí kolik lidí má ověřovací roli.")
    @app_commands.checks.has_permissions(administrator=True)
    async def rev_status(self, itx: Interaction):
        role = itx.guild.get_role(VERIFIED_ROLE_ID)
        if not role: return await itx.response.send_message("❌ Role nenalezena.", ephemeral=True)
        count = len(role.members)
        await itx.response.send_message(f"ℹ️ Rolí {role.mention} disponuje **{count}** členů.", ephemeral=True)

    @reverify.command(name="run", description="Spustí hromadné rozeslání kódů.")
    @app_commands.describe(delay="Prodleva v sekundách (default 0.5)")
    @app_commands.checks.has_permissions(administrator=True)
    async def rev_run(self, itx: Interaction, delay: float = 0.5, dry_run: bool = False):
        await itx.response.defer(ephemeral=True)
        role = itx.guild.get_role(VERIFIED_ROLE_ID)
        if not role: return await itx.followup.send("❌ Role nenalezena.", ephemeral=True)
        
        targets = [m for m in role.members if not m.bot]
        if not targets: return await itx.followup.send("⚠️ Nikdo nemá tuto roli.", ephemeral=True)

        await itx.followup.send(f"🚀 Spouštím hromadnou akci pro {len(targets)} uživatelů. DryRun: {dry_run}")
        
        sent = 0
        fail = 0
        
        for member in targets:
            # Generate OTP via logic
            st = self.get_user_state(member.id) # creates if needed
            otp = st["otp"]
            
            if not dry_run:
                try:
                    await self.send_verification_dm(member, otp)
                    sent += 1
                except:
                    fail += 1
                await asyncio.sleep(delay)
            else:
                sent += 1
        
        mode = "TEST (DryRun)" if dry_run else "Ostrý režim"
        await itx.followup.send(f"✅ Dokončeno ({mode}).\nOdesláno: {sent}\nSelhalo: {fail}", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
