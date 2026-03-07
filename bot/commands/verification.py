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
from shared.redis_client import get_redis_client
from shared.keycloak_client import keycloak_client


try:
    from config.config import GUILD_ID, MOD_CHANNEL_ID, WELCOME_CHANNEL_ID, BOT_PREFIX
    
    try:
        from config.config import RULES_CHANNEL_ID, INFO_CHANNEL_ID, INTRO_CHANNEL_ID
    except ImportError:
        RULES_CHANNEL_ID = None
        INFO_CHANNEL_ID = None
        INTRO_CHANNEL_ID = None
    
    
    try:
        from config.config import VERIFICATION_CHANNEL_ID
    except ImportError:
        VERIFICATION_CHANNEL_ID = MOD_CHANNEL_ID  
    
    
    try:
        from config.config import VERIFICATION_LOG_CHANNEL_ID
    except ImportError:
        VERIFICATION_LOG_CHANNEL_ID = MOD_CHANNEL_ID  
        
    from verification_config import VERIFICATION_CODE, VERIFIED_ROLE_ID
except ImportError:
    logging.warning("⚠️ Config import failed, using defaults.")
    GUILD_ID = None
    MOD_CHANNEL_ID = None
    VERIFICATION_CHANNEL_ID = None
    VERIFICATION_LOG_CHANNEL_ID = None
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
    "bypass_password_hash": None, 
    "max_attempts": 3,
    "attempt_timeout": 300,
    "verification_timeout": 86400,
    "min_account_age_days": 7,
    "log_failed_attempts": True,
    "require_avatar": False,
}

# Role Mapping: Keycloak Group Path -> Discord Role ID
GROUP_MAPPING = {
    "/Dobrovolníci/E-koučové": 1022056088062918707,
    "/Dobrovolníci/Moderátoři Discord": 1022049035705655316,
    "/Dobrovolníci/Moderátoři fórum": 1252505707534745681,
    "/Pracovníci NP/Koordinátoři": 1191708314673877124
}

class SSOStatusView(discord.ui.View):
    def __init__(self, bot: commands.Bot):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ověřit stav (Check Status)", style=discord.ButtonStyle.primary, emoji="🔄", custom_id="sso_check_status")
    async def btn_check_status(self, interaction: Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        r = await get_redis_client()
        user_id = str(interaction.user.id)
        
        # 1. Check if user is linked in Redis
        kc_user_id = await r.get(f"sso:keycloak_link:{user_id}")
        if not kc_user_id:
            await interaction.followup.send(
                "❌ **Tvůj Discord účet není propojen s NePornu ID.**\n"
                "Klikni na tlačítko 'Propojit účet' výše a přihlas se.",
                ephemeral=True
            )
            return

        # 2. Fetch groups from Keycloak
        groups = await keycloak_client.get_user_groups(kc_user_id)
        if not groups and not isinstance(groups, list):
            await interaction.followup.send("❌ Nepodařilo se načíst data z Keycloaku. Zkus to prosím později.", ephemeral=True)
            return

        # 3. Map groups to roles
        assigned_roles = []
        failed_roles = []
        
        group_paths = [g.get("path") for g in groups]
        logging.info(f"SSO Check for {interaction.user.name} ({user_id}): KC_UID={kc_user_id}, Groups={group_paths}")

        for group_path, role_id in GROUP_MAPPING.items():
            if group_path in group_paths:
                role = interaction.guild.get_role(role_id)
                if role:
                    if role not in interaction.user.roles:
                        try:
                            await interaction.user.add_roles(role, reason="SSO Verification")
                            assigned_roles.append(role.name)
                        except Exception as e:
                            logging.error(f"Failed to add role {role.name} to {user_id}: {e}")
                            failed_roles.append(role.name)
                else:
                    logging.warning(f"Role ID {role_id} not found in guild for group {group_path}")

        if assigned_roles:
            msg = f"✅ **Úspěšně ověřeno!** Byly ti přiděleny role: {', '.join(assigned_roles)}"
            if failed_roles:
                msg += f"\n⚠️ Nepodařilo se přidělit: {', '.join(failed_roles)} (Kontaktuj adminy)"
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.followup.send(
                "ℹ️ **Propojení je v pořádku**, ale ve tvém NePornu ID nemáš žádné speciální skupiny (např. E-kouč).\n"
                "Pokud si myslíš, že je to chyba, kontaktuj svého koordinátora.",
                ephemeral=True
            )


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
    def __init__(self, bot: commands.Bot, member_id: int, waiting_approval: bool = False):
        super().__init__(timeout=None)
        self.bot = bot
        self.member_id = member_id
        self.waiting_approval = waiting_approval
        
        if len(self.children) > 0:
            self.children[0].disabled = not waiting_approval

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
                "verification_message_id": None,
                "log_message_id": None,  
                "dm_message_id": None,
                "code_entered_at": None,
                "approved_at": None
            }
            self.bot.loop.create_task(self.save_state())
        return self.state[sid]

    def update_user_state(self, user_id: int, **kwargs):
        sid = str(user_id)
        if sid in self.state:
            self.state[sid].update(kwargs)
            self.bot.loop.create_task(self.save_state())

    def format_timestamp(self, timestamp: float = None) -> str:
        """Format timestamp to readable Czech format"""
        if timestamp is None:
            timestamp = datetime.now().timestamp()
        dt = datetime.fromtimestamp(timestamp)
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    async def check_security(self, member: discord.Member) -> tuple[bool, str]:
        issues = []
        age_days = (datetime.now(member.created_at.tzinfo) - member.created_at).days
        if age_days < self.settings["min_account_age_days"]:
            issues.append(f"⚠️ Účet mladší než {self.settings['min_account_age_days']} dní (stáří: {age_days} dní)")
        if self.settings["require_avatar"] and not member.avatar:
            issues.append("⚠️ Chybí profilový obrázek.")
        return (len(issues) == 0), "\n".join(issues)

    async def send_verification_dm(self, member: discord.Member, otp: str) -> Optional[discord.Message]:
        """Send verification DM and return the message object"""
        msg = (
            f"**🔒 Ověření účtu**\n\n"
            f"Ahoj **{member.name}**! Vítej na serveru.\n"
            f"Pro dokončení ověření prosím pošli sem do chatu tento kód:\n\n"
            f"> **`{otp}`**\n\n"
        )
        try:
            dm_msg = await member.send(msg)
            return dm_msg
        except Exception as e:
            logging.error(f"Failed to send verification DM to {member.id}: {e}")
            return None

    async def _update_verification_message(self, guild: discord.Guild, user_id: int, content: str = None, view = None):
        """Helper to update the verification message"""
        st = self.state.get(str(user_id))
        if not st or not st.get("verification_message_id"): return

        verification_ch = guild.get_channel(VERIFICATION_CHANNEL_ID)
        if not verification_ch: return
        
        try:
            msg = await verification_ch.fetch_message(st["verification_message_id"])
            await msg.edit(content=content, view=view)
        except discord.NotFound:
            pass 
        except Exception as e:
            logging.error(f"Failed to update verification message: {e}")

    async def _delete_verification_message_delayed(self, guild: discord.Guild, user_id: int, delay: int = 60, cleanup_after: bool = False):
        """Delete verification message after a delay"""
        try:
            st = self.state.get(str(user_id))
            if not st or not st.get("verification_message_id"):
                return
            
            msg_id = st["verification_message_id"]
            logging.info(f"Scheduled verification message deletion for user {user_id} in {delay} seconds")
            
            await asyncio.sleep(delay)
            
            verification_ch = guild.get_channel(VERIFICATION_CHANNEL_ID)
            if not verification_ch:
                return
            
            msg = await verification_ch.fetch_message(msg_id)
            await msg.delete()
            logging.info(f"Deleted verification message for user {user_id}")
            
            if cleanup_after:
                self.cleanup_state(user_id)
        except discord.NotFound:
            logging.debug(f"Verification message {msg_id} already deleted for user {user_id}")
            if cleanup_after:
                self.cleanup_state(user_id)
        except Exception as e:
            logging.error(f"Failed to delete verification message for user {user_id}: {e}")
            if cleanup_after:
                self.cleanup_state(user_id)

    async def approve_user(self, member: discord.Member, approver: Optional[discord.User] = None, bypass_used: bool = False) -> bool:
        guild = member.guild
        role = guild.get_role(VERIFIED_ROLE_ID)
        if not role:
            logging.error(f"Verified role {VERIFIED_ROLE_ID} not found.")
            return False

        st = self.get_user_state(member.id)
        approval_time = datetime.now().timestamp()
        self.update_user_state(member.id, approved_at=approval_time)

        try:
            await member.remove_roles(role, reason=f"Verification Approved (Bypass:{bypass_used}, Approver:{approver})")
        except Exception as e:
            logging.error(f"Failed to remove role: {e}")
            return False

        if WELCOME_CHANNEL_ID:
            ch = guild.get_channel(WELCOME_CHANNEL_ID)
            if ch:
                welcome_msg = (
                    f"Nový člen se k nám připojil! Všichni přivítejme {member.mention}!"
                )
                try: await ch.send(welcome_msg)
                except: pass

        try:
            await member.send("✅ **Ověření úspěšné!** Byli jste schváleni a máte přístup na server. Vítejte!")
        except: pass

        join_time = self.format_timestamp(st.get("created_at"))
        code_time = self.format_timestamp(st.get("code_entered_at")) if st.get("code_entered_at") else "N/A"
        approval_time_str = self.format_timestamp(approval_time)
        
        logging.info(
            f"VERIFICATION COMPLETE for {member.name} ({member.id})\n"
            f"  Joined: {join_time}\n"
            f"  Code entered: {code_time}\n"
            f"  Approved: {approval_time_str}\n"
            f"  Moderator: {approver.display_name if approver else 'Auto/Bypass'}\n"
            f"  Bypass: {bypass_used}"
        )

        log_ch = guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
        if log_ch and st and st.get("log_message_id"):
            try:
                log_msg_obj = await log_ch.fetch_message(st["log_message_id"])
                
                if bypass_used:
                    if approver:
                        approval_type = f"Manuální bypass - {approver.mention}"
                    else:
                        approval_type = "Bypass heslem"
                else:
                    approval_type = f"Schválil {approver.mention}" if approver else "Schváleno"
                
                updated_content = log_msg_obj.content
                join_time = self.format_timestamp(st.get("created_at"))
                code_time = self.format_timestamp(st.get("code_entered_at")) if st.get("code_entered_at") else "N/A"
                approval_time_str = self.format_timestamp(approval_time)
                
                updated_content = updated_content.replace("📥 **Nový uživatel se připojil!**", "✅ **Uživatel ověřen:**")
                
                timeline_start = updated_content.find("**Časový průběh:**")
                if timeline_start != -1:
                    warning_start = updated_content.find("\n\n⚠️", timeline_start)
                    if warning_start == -1:
                        warning_start = len(updated_content)
                    
                    new_timeline = (
                        f"**Časový průběh:**\n"
                        f"• Připojení: `{join_time}`\n"
                        f"• Zadání kódu: `{code_time}`\n"
                        f"• Schválení: `{approval_time_str}`\n\n"
                        f"**Moderátor:** {approval_type}"
                    )
                    updated_content = updated_content[:timeline_start] + new_timeline + updated_content[warning_start:]
                    await log_msg_obj.edit(content=updated_content)
            except Exception as e:
                logging.error(f"Failed to update approval log: {e}")
        
        if st and st.get("verification_message_id"):
            verification_ch = guild.get_channel(VERIFICATION_CHANNEL_ID)
            if verification_ch:
                try:
                    msg = await verification_ch.fetch_message(st["verification_message_id"])
                    await msg.delete()
                    logging.info(f"Deleted verification message for approved user {member.id}")
                except discord.NotFound:
                    pass  
                except Exception as e:
                    logging.error(f"Failed to delete verification message: {e}")
        
        self.cleanup_state(member.id)
        return True

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot: return
        role = member.guild.get_role(VERIFIED_ROLE_ID)
        if role:
            try: await member.add_roles(role)
            except: pass

        st = self.get_user_state(member.id)
        otp = st["otp"]
        
        created_at_fmt = f"<t:{int(member.created_at.timestamp())}:f> (<t:{int(member.created_at.timestamp())}:R>)"
        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
        
        sec_ok, sec_reason = await self.check_security(member)
        
        # NSFW Check Integration
        nsfw_score_str = "N/A"
        avatar_nsfw_cog = self.bot.get_cog("AvatarNSFW")
        if avatar_nsfw_cog:
            try:
                _, nsfw_score_str = await avatar_nsfw_cog.get_user_nsfw_score(member)
            except Exception as e:
                logging.error(f"Failed to get NSFW score for {member.id}: {e}")
        
        verification_ch = member.guild.get_channel(VERIFICATION_CHANNEL_ID)
        if verification_ch:
            try:
                bio_text = "Bio není dostupné"
                if hasattr(member, 'bio') and member.bio:
                    bio_text = member.bio
                
                desc = (
                    f"**Nový uživatel se připojil na server!**\n\n"
                    f"**Uživatel:** {member.mention} ({member.name})\n"
                    f"**ID:** {member.id}\n"
                    f"**Účet vytvořen:** {created_at_fmt}\n"
                    f"**Avatar:** {avatar_url}\n"
                    f"**Pravděpodobnost NSFW:** {nsfw_score_str}\n"
                    f"**Bio:** {bio_text}\n\n"
                    f"Automaticky mu byla přidělena ověřovací role.\n\n"
                    f"⏳ **Status:** Čeká na zadání kódu..."
                )
                
                if not sec_ok:
                    desc += f"\n\n⚠️ **Bezpečnostní varování:**\n{sec_reason}"
                
                view = VerificationModView(self.bot, member.id, waiting_approval=False)
                m = await verification_ch.send(desc, view=view)
                self.update_user_state(member.id, verification_message_id=m.id)
            except Exception as e:
                logging.error(f"Failed to send verification message: {e}")
        
        log_ch = member.guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
        if log_ch and VERIFICATION_LOG_CHANNEL_ID != VERIFICATION_CHANNEL_ID:  
            try:
                bio_text = "Bio není dostupné"
                if hasattr(member, 'bio') and member.bio:
                    bio_text = member.bio
                
                join_time = self.format_timestamp(st.get("created_at"))
                
                log_msg = (
                    f"📥 **Nový uživatel se připojil!**\n\n"
                    f"**Uživatel:** {member.mention} ({member.name})\n"
                    f"**ID:** {member.id}\n"
                    f"**Účet vytvořen:** {created_at_fmt}\n"
                    f"**Avatar:** {avatar_url}\n"
                    f"**Pravděpodobnost NSFW:** {nsfw_score_str}\n"
                    f"**Bio:** {bio_text}\n\n"
                    f"Automaticky mu byla přidělena ověřovací role.\n\n"
                    f"**Časový průběh:**\n"
                    f"• Připojení: `{join_time}`\n"
                    f"• Zadání kódu: `Čeká se...`\n"
                    f"• Schválení: `Čeká se...`"
                )
                if not sec_ok:
                    log_msg += f"\n\n⚠️ **Bezpečnostní varování:**\n{sec_reason}"
                
                log_m = await log_ch.send(log_msg)
                self.update_user_state(member.id, log_message_id=log_m.id)
            except Exception as e:
                logging.error(f"Failed to send log message: {e}")

        try:
            dm_msg = await self.send_verification_dm(member, otp)
            if dm_msg:
                self.update_user_state(member.id, dm_message_id=dm_msg.id)
                logging.info(f"Sent verification DM to {member.name} ({member.id}) at {self.format_timestamp()}")
        except Exception as e:
            logging.error(f"Failed to send verification DM: {e}")

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if str(member.id) in self.state:
            st = self.state.get(str(member.id))
            leave_time = self.format_timestamp(datetime.now().timestamp())
            
            log_ch = member.guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
            if log_ch and st and st.get("log_message_id"):
                try:
                    log_msg_obj = await log_ch.fetch_message(st["log_message_id"])
                    updated_content = log_msg_obj.content
                    
                    updated_content = updated_content.replace("📥 **Nový uživatel se připojil!**", "❌ **Uživatel opustil server**")
                    
                    warning_pos = updated_content.find("\n\n⚠️")
                    leave_info = f"\n\n**Výsledek:** ❌ Opustil server během verifikace.\n**Čas opuštění:** `{leave_time}`"
                    if warning_pos == -1:
                        updated_content += leave_info
                    else:
                        updated_content = updated_content[:warning_pos] + leave_info + updated_content[warning_pos:]
                    
                    await log_msg_obj.edit(content=updated_content)
                except Exception as e:
                    logging.error(f"Failed to update log on member leave: {e}")
            
            final_msg = (
               f"**Uživatel:** {member.mention} (`{member.name}`)\n"
               f"**ID:** {member.id}\n"
               f"**Výsledek:** ❌ **Opustil server** během verifikace."
            )
            await self._update_verification_message(member.guild, member.id, content=final_msg, view=None)
            
            self.bot.loop.create_task(self._delete_verification_message_delayed(member.guild, member.id, 60, cleanup_after=True))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.guild: return
        sid = str(message.author.id)
        if sid not in self.state: return
        
        st = self.state[sid]
        
        if st.get("status") == "LOCKED" or (st["locked_until"] > datetime.now().timestamp()):
            await message.channel.send("⛔ **Verifikace zablokována.** Kontaktuj moderátory na serveru.")
            return
            
        if st.get("status") == "WAITING_FOR_APPROVAL":
            await message.channel.send("⏳ **Čekání na schválení.** Moderátoři byli upozorněni.")
            return

        user_input = message.content.strip()
        guild = self.bot.get_guild(GUILD_ID)
        if not guild: return
        member = guild.get_member(message.author.id)
        if not member: return

        bypass_hash = self.settings.get("bypass_password_hash")
        if bypass_hash and verify_password(user_input, bypass_hash):
            await self.approve_user(member, bypass_used=True)
            await message.channel.send("✅ **Tajné heslo přijato.** Vstup povolen.")
            return

        if user_input == st["otp"] or (VERIFICATION_CODE and user_input.upper() == VERIFICATION_CODE.upper()):
            code_entered_time = datetime.now().timestamp()
            self.update_user_state(member.id, status="WAITING_FOR_APPROVAL", code_entered_at=code_entered_time)
            await message.channel.send("✅ **Kód je správný.** Nyní prosím čekej, než moderátor potvrdí tvůj přístup.")
            
            logging.info(f"User {member.name} ({member.id}) entered correct code at {self.format_timestamp(code_entered_time)}")
            
            try:
                log_ch = guild.get_channel(VERIFICATION_LOG_CHANNEL_ID)
                if log_ch and st.get("log_message_id"):
                    log_msg_obj = await log_ch.fetch_message(st["log_message_id"])
                    
                    updated_content = log_msg_obj.content
                    join_time = self.format_timestamp(st.get("created_at"))
                    code_time = self.format_timestamp(code_entered_time)
                    
                    timeline_start = updated_content.find("**Časový průběh:**")
                    if timeline_start != -1:
                        warning_start = updated_content.find("\n\n⚠️", timeline_start)
                        if warning_start == -1:
                            warning_start = len(updated_content)
                        
                        new_timeline = (
                            f"**Časový průběh:**\n"
                            f"• Připojení: `{join_time}`\n"
                            f"• Zadání kódu: `{code_time}`\n"
                            f"• Schválení: `Čeká se...`"
                        )
                        updated_content = updated_content[:timeline_start] + new_timeline + updated_content[warning_start:]
                        await log_msg_obj.edit(content=updated_content)
            except Exception as e:
                logging.error(f"Failed to update log message on code entry: {e}")
            
            try:
                verification_ch = guild.get_channel(VERIFICATION_CHANNEL_ID)
                if verification_ch and st.get("verification_message_id"):
                    msg = await verification_ch.fetch_message(st["verification_message_id"])
                    new_view = VerificationModView(self.bot, member.id, waiting_approval=True)
                    await msg.edit(view=new_view)
            except Exception as e:
                logging.error(f"Failed to update verification message: {e}")
            
            return

        attempts = st["attempts"] + 1
        self.update_user_state(member.id, attempts=attempts)
        
        await message.channel.send(f"❌ **Špatný kód.** Zkus to znovu. (Pokus #{attempts})")

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

    @verify_group.command(name="nepornu", description="Propojí tvůj Discord s interním systémem NePornu")
    async def verify_nepornu(self, interaction: Interaction):
        """Sends an interactive message to link Keycloak and Discord"""
        embed = discord.Embed(
            title="🔗 Propojení s NePornu ID",
            description=(
                "Tento příkaz slouží k propojení tvého Discord účtu s interním systémem NePornu (Keycloak).\n\n"
                "**Postup:**\n"
                "1. Klikni na tlačítko **'Propojit účet'** níže.\n"
                "2. Přihlas se svými údaji (nebo si je vyžádej od koordinátora).\n"
                "3. Po úspěšném přihlášení a schválení se vrať sem.\n"
                "4. Klikni na tlačítko **'Ověřit stav'**.\n\n"
                "*Tip: Pokud jsi E-kouč, Moderátor nebo Koordinátor, automaticky získáš své role.*"
            ),
            color=discord.Color.blue()
        )
        
        view = SSOStatusView(self.bot)
        # Add link button
        link_button = discord.ui.Button(
            label="Propojit účet (Link SSO)",
            url="https://portal.nepornu.cz",
            style=discord.ButtonStyle.link,
            emoji="🔑"
        )
        view.add_item(link_button)
        
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot: commands.Bot):
    await bot.add_cog(VerificationCog(bot))
    # Register persistent views
    bot.add_view(SSOStatusView(bot))
