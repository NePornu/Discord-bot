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
    # Try to import channel IDs for welcome message if they exist in config, else use None/Placeholder
    try:
        from config import RULES_CHANNEL_ID, INFO_CHANNEL_ID, INTRO_CHANNEL_ID
    except ImportError:
        RULES_CHANNEL_ID = None
        INFO_CHANNEL_ID = None
        INTRO_CHANNEL_ID = None
        
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
except ImportError:
    logging.warning("⚠️ Config import failed, using defaults.")
    GUILD_ID = None
    MOD_CHANNEL_ID = None
    WELCOME_CHANNEL_ID = None
    VERIFICATION_CODE = "123456"
    VERIFIED_ROLE_ID = None
    BOT_PREFIX = "!"
    RULES_CHANNEL_ID = None
    INFO_CHANNEL_ID = None
    INTRO_CHANNEL_ID = None

SETTINGS_FILE = "data/verification_settings.json"
STATE_FILE = "data/verification_state.json"
DEFAULT_SETTINGS_DATA = {
    "bypass_password_hash": None, # SHA-256 hash of bypass password
    "max_attempts": 3,
    "attempt_timeout": 300,
    "verification_timeout": 86400,
    "min_account_age_days": 7,
    "log_failed_attempts": True,
    "require_avatar": False,
}

# --- Helpers ---
def chunked(seq: Iterable, n: int) -> Iterable[list]:
    buf = []
    for x in seq:
        buf.append(x)
        if len(buf) >= n:
            yield buf
            buf = []
    if buf:
        yield buf

def generate_otp(length=6) -> str:
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

    @discord.ui.button(label="Schválit (Approve)", style=discord.ButtonStyle.success, emoji="✅", custom_id="verif_approve")
    async def btn_approve(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        cog = self.bot.get_cog("VerificationCog")
        if not cog: return await interaction.followup.send("❌ Cog error.", ephemeral=True)
        
        member = await self.get_member(interaction.guild)
        if not member:
            return await interaction.followup.send("❌ Uživatel už není na serveru.", ephemeral=True)

        st = cog.get_user_state(member.id)
        if st.get("status") != "WAITING_FOR_APPROVAL":
             return await interaction.followup.send("❌ Uživatel zatím nezadal správný kód. (Použij /verify bypass pokud je to nutné)", ephemeral=True)
            
        success = await cog.approve_user(member, approver=interaction.user)
        if success:
            # Message is updated in approve_user
            self.stop()
        else:
            await interaction.followup.send("❌ Chyba při schvalování (Role? Config?).", ephemeral=True)


    @discord.ui.button(label="Upozornit", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="verif_warn")
    async def btn_warn(self, interaction: Interaction, button: discord.ui.Button):
        member = await self.get_member(interaction.guild)
        if not member: return await interaction.response.send_message("❌ Uživatel už není na serveru.", ephemeral=True)
        await interaction.response.send_modal(WarnUserModal(member, self))

    @discord.ui.button(label="Vyhodit (Kick)", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="verif_kick")
    async def btn_kick(self, interaction: Interaction, button: discord.ui.Button):
        member = await self.get_member(interaction.guild)
        if not member: return await interaction.response.send_message("❌ Uživatel už není na serveru.", ephemeral=True)
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
        self.state: Dict[str, dict] = {} 
        self.mod_messages: Dict[int, int] = {}
        
        if not os.path.exists("data"): os.makedirs("data")
        self.load_settings()
        self.bot.loop.create_task(self.load_state())

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

    def get_user_state(self, user_id: int) -> dict:
        sid = str(user_id)
        if sid not in self.state:
            self.state[sid] = {
                "otp": generate_otp(),
                "attempts": 0,
                "created_at": datetime.now().timestamp(),
                "locked_until": 0,
                "status": "PENDING",
                "mod_message_id": None
            }
            self.bot.loop.create_task(self.save_state())
        return self.state[sid]

    def update_user_state(self, user_id: int, **kwargs):
        sid = str(user_id)
        if sid in self.state:
            self.state[sid].update(kwargs)
            self.bot.loop.create_task(self.save_state())

    async def check_security(self, member: discord.Member) -> tuple[bool, str]:
        issues = []
        age_days = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        if age_days < self.settings["min_account_age_days"]:
            issues.append(f"⚠️ Účet mladší než {self.settings['min_account_age_days']} dní (stáří: {age_days} dní)")
        if self.settings["require_avatar"] and not member.avatar:
            issues.append("⚠️ Chybí profilový obrázek.")
        return (len(issues) == 0), "\n".join(issues)

    async def send_verification_dm(self, member: discord.Member, otp: str):
        msg = (
            f"**🔒 Ověření účtu**\n\n"
            f"Ahoj **{member.name}**! Vítej na serveru.\n"
            f"Pro dokončení ověření prosím pošli sem do chatu tento kód:\n\n"
            f"> **`{otp}`**\n\n"
        )
        await member.send(msg)

    async def _update_mod_message(self, guild: discord.Guild, user_id: int, content: str = None, view = None, delete: bool = False):
        """Helper to update the persistent mod message"""
        st = self.state.get(str(user_id))
        if not st or not st.get("mod_message_id"): return

        mod_ch = guild.get_channel(MOD_CHANNEL_ID)
        if not mod_ch: return
        
        try:
            msg = await mod_ch.fetch_message(st["mod_message_id"])
            if delete:
                await msg.delete()
            else:
                await msg.edit(content=content, view=view)
        except discord.NotFound:
            pass # Message already deleted
        except Exception as e:
            logging.error(f"Failed to update mod message: {e}")

    async def approve_user(self, member: discord.Member, approver: Optional[discord.User] = None, bypass_used: bool = False) -> bool:
        guild = member.guild
        role = guild.get_role(VERIFIED_ROLE_ID)
        if not role:
            logging.error(f"Verified role {VERIFIED_ROLE_ID} not found.")
            return False

        try:
            await member.remove_roles(role, reason=f"Verification Approved (Bypass:{bypass_used}, Approver:{approver})")
        except Exception as e:
            logging.error(f"Failed to remove role: {e}")
            return False

        # Custom Welcome Message
        if WELCOME_CHANNEL_ID:
            ch = guild.get_channel(WELCOME_CHANNEL_ID)
            if ch:
                rules_ch = f"<#{RULES_CHANNEL_ID}>" if RULES_CHANNEL_ID else "⁠📗pravidla"
                info_ch = f"<#{INFO_CHANNEL_ID}>" if INFO_CHANNEL_ID else "⁠ℹ️úvod"
                intro_ch = "<#1191296600631431198>"
                
                welcome_msg = (
                    f"Nový člen se k nám připojil! Všichni přivítejme {member.mention}!"
                )
                try: await ch.send(welcome_msg)
                except: pass

        # Notify User
        try:
            await member.send("✅ **Ověření úspěšné!** Byli jste schváleni a máte přístup na server. Vítejte!")
        except: pass

        # Update Mod Log (EDIT original message)
        if bypass_used:
            if approver:
                status_text = f"MANUÁLNÍ BYPASS (Schválil {approver.display_name})"
            else:
                status_text = "BYPASS HESLEM"
        else:
            status_text = f"Schválil {approver.display_name}" if approver else "Schváleno"
        
        # We construct the final log content based on previous state or just append/modify
        # Simpler: Just replace the "Status" line or append result.
        # To do it cleanly, we need to regenerate the full message or just simplify.
        # Let's try to preserve the info header.
        
        header = (
            f"**Uživatel:** {member.mention} (`{member.name}`)\n"
            f"**ID:** {member.id}\n"
            f"**Výsledek:** ✅ **OVĚŘEN** ({status_text})"
        )
        
        await self._update_mod_message(guild, member.id, content=header, view=None)
        
        self.cleanup_state(member.id)
        return True

    # --- Events ---
    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        role = member.guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try: await member.add_roles(role)
            except: pass

        st = self.get_user_state(member.id)
        otp = st["otp"]
        
        # Info Gathering
        created_at_fmt = f"<t:{int(member.created_at.timestamp())}:f> (<t:{int(member.created_at.timestamp())}:R>)"
        avatar_url = member.display_avatar.url
        
        sec_ok, sec_reason = await self.check_security(member)
        
        mod_ch = member.guild.get_channel(MOD_CHANNEL_ID)
        if mod_ch:
            # Construct Detailed Message
            desc = (
                f"**Nový uživatel se připojil na server!**\n\n"
                f"**Uživatel:** {member.mention} ({member.name})\n"
                f"**ID:** {member.id}\n"
                f"**Účet vytvořen:** {created_at_fmt}\n"
                f"**Avatar:** {avatar_url}\n"
                f"**Bio:** Bio není dostupné\n\n"
                f"Automaticky mu byla přidělena ověřovací role.\n"
            )
            
            if not sec_ok:
                desc += f"\n⚠️ **Bezpečnostní varování:**\n{sec_reason}\n"
            
            view = VerificationModView(self.bot, member.id)
            try:
                m = await mod_ch.send(desc, view=view)
                # Store message ID in persistent state
                self.update_user_state(member.id, mod_message_id=m.id)
            except Exception as e:
                logging.error(f"Failed to send mod log: {e}")

        try: await self.send_verification_dm(member, otp)
        except: pass

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if str(member.id) in self.state:
            # Edit existing message
            header = (
               f"**Uživatel:** {member.mention} ({member.name})\n"
               f"**ID:** {member.id}\n"
               f"**Výsledek:** ❌ **Opustil server** během verifikace."
            )
            await self._update_mod_message(member.guild, member.id, content=header, view=None)
            self.cleanup_state(member.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild: return
        sid = str(message.author.id)
        if sid not in self.state: return
        
        st = self.state[sid]
        
        # Check Lock
        if st.get("status") == "LOCKED" or (st["locked_until"] > datetime.now().timestamp()):
            await message.channel.send("⛔ **Verifikace zablokována.** Kontaktuj moderátory na serveru.")
            return
            
        # Check Waiting
        if st.get("status") == "WAITING_FOR_APPROVAL":
            await message.channel.send("⏳ **Čekání na schválení.** Moderátoři byli upozorněni.")
            return

        user_input = message.content.strip()
        guild = self.bot.get_guild(GUILD_ID)
        if not guild: return
        member = guild.get_member(message.author.id)
        if not member: return

        # 1. BYPASS
        bypass_hash = self.settings.get("bypass_password_hash")
        if bypass_hash and verify_password(user_input, bypass_hash):
            await self.approve_user(member, bypass_used=True)
            await message.channel.send("✅ **Tajné heslo přijato.** Vstup povolen.")
            return

        # 2. OTP
        if user_input == st["otp"] or (VERIFICATION_CODE and user_input.upper() == VERIFICATION_CODE.upper()):
            self.update_user_state(member.id, status="WAITING_FOR_APPROVAL")
            await message.channel.send("✅ **Kód je správný.** Nyní prosím čekej, než moderátor potvrdí tvůj přístup.")
            
            # Update Mod Message to indicate "WAITING FOR APPROVAL"
            # Fetch original content or just append?
            # Ideally, we allow the mod view to stay interactive.
            # We can send a reply OR update the embed/text. 
            # User dislikes "million messages". So update text.
            
            try:
                mod_ch = guild.get_channel(MOD_CHANNEL_ID)
                if mod_ch and st.get("mod_message_id"):
                    msg = await mod_ch.fetch_message(st["mod_message_id"])
                    
                    # Keep original content roughly but add status
                    new_content = msg.content + "\n\n🟢 **Uživatel zadal správný kód.** Čeká na schválení tlačítkem."
                    await msg.edit(content=new_content)
            except: pass
            
            return

        # 3. Fail
        attempts = st["attempts"] + 1
        self.update_user_state(member.id, attempts=attempts)
        
        if attempts >= self.settings["max_attempts"]:
            self.update_user_state(member.id, status="LOCKED")
            await message.channel.send("⛔ **Vyčerpal jsi počet pokusů.** Kontaktuj moderátory na serveru pro manuální ověření.")
            # Log To Mod
            try:
                mod_ch = guild.get_channel(MOD_CHANNEL_ID)
                if mod_ch and st.get("mod_message_id"):
                    msg = await mod_ch.fetch_message(st["mod_message_id"])
                    new_content = msg.content + "\n\n⛔ **Uživatel vyčerpal pokusy a byl zablokován.**"
                    await msg.edit(content=new_content)
            except: pass
        else:
            left = self.settings["max_attempts"] - attempts
            await message.channel.send(f"❌ **Špatný kód.** Zbývá pokusů: {left}")

    # --- Commands ---
    verify_group = app_commands.Group(name="verify", description="Příkazy pro ověření")

    @verify_group.command(name="set_bypass", description="Nastaví tajné bypass heslo.")
    @app_commands.checks.has_permissions(administrator=True)
    async def set_bypass(self, itx: Interaction, password: str):
        self.settings["bypass_password_hash"] = hash_password(password)
        self.save_settings()
        await itx.response.send_message("✅ Heslo nastaveno.", ephemeral=True)

    @verify_group.command(name="bypass", description="Manuálně schválí uživatele (Bypass).")
    @app_commands.checks.has_permissions(ban_members=True)
    async def verify_bypass(self, itx: Interaction, user: discord.Member):
        await itx.response.defer()
        success = await self.approve_user(user, approver=itx.user, bypass_used=True)
        if success:
            await itx.followup.send(f"✅ **{user.display_name}** byl manuálně schválen.")
        else:
            await itx.followup.send("❌ Nepodařilo se schválit uživatele (nelze najít roli nebo uživatel už je ověřen?).")

    @verify_group.command(name="ping", description="Pošle ti testovací DM s OTP.")
    async def verify_ping(self, itx: Interaction):
        await itx.response.defer(ephemeral=True)
        otp = generate_otp()
        try:
             await self.send_verification_dm(itx.user, otp)
             await itx.followup.send("✅ Testovací DM odesláno.")
        except:
             await itx.followup.send("❌ Nelze poslat DM.")

    # Simplified Reverification
    reverify = app_commands.Group(name="reverify", description="Hromadná re-verifikace")

    @reverify.command(name="run", description="Spustí hromadné rozeslání kódů.")
    @app_commands.checks.has_permissions(administrator=True)
    async def rev_run(self, itx: Interaction, delay: float = 0.5):
        await itx.response.send_message("⚠️ Tato funkce je v režimu 2.1 omezena (vyžaduje manuální schválení každého člena).", ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
