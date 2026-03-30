import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import List, Optional
import discord
from shared.python.config import config
from shared.python.redis_client import get_redis_client
from .common import K_ALERT, K_MUTE, K_MSG, K_THREAD, K_THREAD_UID, K_FOLLOWUP, K_NOTES, PatternAlert, is_staff

logger = logging.getLogger("PatternDetector")

class MentorDMModal(discord.ui.Modal, title="Poslat zprávu klientovi"):
    message = discord.ui.TextInput(
        label="Text zprávy",
        style=discord.TextStyle.paragraph,
        placeholder="Ahoj, všiml jsem si tvojí aktivity...",
        required=True,
        max_length=1000,
    )

    def __init__(self, user_id: int, guild_id: int):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        guild = itx.guild
        member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
        
        if not member:
            await itx.followup.send("❌ Klient nebyl nalezen (možná opustil server).", ephemeral=True)
            return

        try:
            # Send DM
            embed = discord.Embed(
                title="Zpráva od mentora NePornu",
                description=self.message.value,
                color=0x3498DB
            )
            embed.set_footer(text="Na tuto zprávu můžeš odpovědět přímo zde.")
            await member.send(embed=embed)
            
            # Log as note in thread
            r = await get_redis_client()
            notes_data = await r.get(K_NOTES(self.guild_id, self.user_id))
            notes_list = json.loads(notes_data) if notes_data else []
            notes_list.append({
                "ts": int(time.time()),
                "author": f"{itx.user.display_name} (DM)",
                "content": self.message.value
            })
            await r.set(K_NOTES(self.guild_id, self.user_id), json.dumps(notes_list[-50:]), ex=730 * 86400)
            await r.close()
            
            await itx.followup.send(f"✅ Zpráva byla odeslána uživateli <@{self.user_id}> a uložena do poznámek klienta.", ephemeral=True)
            
            # Post confirmation to thread
            if isinstance(itx.channel, discord.Thread):
                await itx.channel.send(f"✉️ **@Moderační tým**: {itx.user.mention} poslal klientovi zprávu:\n> {self.message.value[:200]}...")

        except discord.Forbidden:
            await itx.followup.send("❌ Nepodařilo se odeslat zprávu. Uživatel má pravděpodobně vypnuté DM.", ephemeral=True)
        except Exception as e:
            logger.error(f"Error in MentorDMModal: {e}")
            await itx.followup.send(f"❌ Nastala chyba při odesílání: {e}", ephemeral=True)

class ModeratorAssistantView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="✔ Vyřešit", style=discord.ButtonStyle.success, custom_id="pat:handled")
    async def mark_handled(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        gid = self.guild_id
        uid = self.user_id
        
        # Mute user for 30 days (INFO) or logic based on current state
        await r.set(K_MUTE(gid, uid), "1", ex=30 * 86400)
        
        # Clean up thread reference
        from .common import K_THREAD
        await r.delete(K_THREAD(gid, uid))
        await r.close()
        
        # Disable buttons on the original message
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True
        
        await itx.edit_original_response(view=self)
        await itx.followup.send(f"✅ Klient <@{uid}> byl označen jako vyřešený. Vlákno bude archivováno.", ephemeral=True)
        
        # Archive thread if it is a thread
        if isinstance(itx.channel, discord.Thread):
            try:
                await itx.channel.edit(archived=True, locked=False)
            except Exception as e:
                logger.error(f"Failed to archive thread: {e}")

    @discord.ui.button(label="Aktivita", emoji="📊", style=discord.ButtonStyle.secondary, custom_id="pat:activity")
    async def view_activity(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        
        try:
            from .detectors import PatternDetectors
            det = PatternDetectors(self.guild_id)
            
            # Fetch member for mention/name/avatar
            guild = itx.guild
            mention = f"<@{self.user_id}>"
            name = f"Uživatel {self.user_id}"
            avatar = None
            
            try:
                member = guild.get_member(self.user_id) or await guild.fetch_member(self.user_id)
                if member:
                    mention = member.mention
                    name = member.display_name
                    avatar = member.display_avatar.url
            except: pass

            embed = await det.build_diagnostic_embed(r, self.user_id, mention, name, avatar)
            await itx.followup.send(embed=embed, ephemeral=True)
        finally:
            await r.aclose()

    @discord.ui.button(label="📩 Poslat mentora", style=discord.ButtonStyle.primary, custom_id="pat:mentor")
    async def send_mentor(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.send_modal(MentorDMModal(self.user_id, self.guild_id))

    @discord.ui.button(label="⏳ Sledovat (48h)", style=discord.ButtonStyle.secondary, custom_id="pat:follow")
    async def follow_up(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        # Set 48h followup
        deadline = int(time.time()) + 48 * 3600
        await r.set(K_FOLLOWUP(self.guild_id, self.user_id), str(deadline), ex=60 * 3600)
        await r.close()
        
        await itx.followup.send(f"⏳ **Sledování nastaveno.** Pokud klient do 48 hodin nenapíše žádnou zprávu, bot sem do vlákna pošle připomínku.", ephemeral=True)
        if isinstance(itx.channel, discord.Thread):
            await itx.channel.send(f"⏳ {itx.user.mention} nastavil sledování klienta na 48 hodin.")

class DiagnosticResultView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int, alerts_mgr: 'PatternAlerts', detectors: 'PatternDetectors'):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.guild_id = guild_id
        self.alerts_mgr = alerts_mgr
        self.detectors = detectors

    @discord.ui.button(label="Otevřít kartu (Sledovat)", emoji="📩", style=discord.ButtonStyle.primary, custom_id="pat:open_case")
    async def open_case(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        
        # Check if thread already exists
        r = await get_redis_client()
        thread_id = await r.get(K_THREAD(self.guild_id, self.user_id))
        await r.close()
        
        if thread_id:
            await itx.followup.send("⚠️ Tento uživatel již má otevřenou kartu (vlákno).", ephemeral=True)
            button.disabled = True
            await itx.edit_original_response(view=self)
            return

        # Create manual thread
        success = await self.alerts_mgr.create_manual_thread(self.user_id, itx, self.detectors)
        if success:
            button.disabled = True
            button.label = "Karta otevřena"
            button.style = discord.ButtonStyle.success
            await itx.edit_original_response(view=self)
        else:
            await itx.followup.send("❌ Nepodařilo se vytvořit vlákno. Zkontrolujte logy.", ephemeral=True)

class PatternAlerts:
    def __init__(self, bot, guild_id):
        self.bot = bot
        self._guild_id = guild_id
        self._alert_channel = None

    async def get_alert_channel(self) -> discord.TextChannel:
        if self._alert_channel:
            return self._alert_channel
        guild = self.bot.get_guild(self._guild_id)
        if guild:
            self._alert_channel = guild.get_channel(config.PATTERN_ALERT_CHANNEL_ID)
        return self._alert_channel

    async def should_send_alert(self, r, gid: int, alert: PatternAlert) -> bool:
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        return not await r.exists(key)

    async def mark_alert_sent(self, r, gid: int, alert: PatternAlert):
        key = K_ALERT(gid, alert.user_id, alert.pattern_name)
        
        # Risk-based cooldowns
        cooldown_hours = config.PATTERN_ALERT_COOLDOWN_HOURS # Default 24h
        if alert.risk_level == "info":
            cooldown_hours = 30 * 24 # 30 days
        elif alert.risk_level == "warning":
            cooldown_hours = 7 * 24 # 7 days
        elif alert.risk_level == "critical":
            cooldown_hours = 3 * 24 # 3 days
            
        ttl = cooldown_hours * 3600
        await r.set(key, str(int(time.time())), ex=ttl)

    async def send_batched_alerts(self, user_id: int, alerts: List[PatternAlert]):
        if not alerts:
            return
            
        channel = await self.get_alert_channel()
        if not channel:
            logger.warning(f"Alert channel not found for batched alerts")
            return

        guild = self.bot.get_guild(self._guild_id)
        mention = f"<@{user_id}>"
        display_name = f"Uživatel {user_id}"
        avatar_url = None
        
        if guild:
            try:
                member = guild.get_member(user_id) or await guild.fetch_member(user_id)
                if member:
                    display_name = member.display_name
                    mention = member.mention
                    avatar_url = member.display_avatar.url
            except Exception as e:
                logger.debug(f"Could not fetch member {user_id}: {e}")

        # Determine highest risk level
        risk_levels = [a.risk_level for a in alerts]
        color = 0x3498DB # Info
        emoji = "⚪"
        if "critical" in risk_levels:
            color = 0xFF0000
            emoji = "🔴"
        elif "warning" in risk_levels:
            color = 0xFFA500
            emoji = "🟡"

        # 2. Get or Create Thread
        thread = await self.get_or_create_thread(user_id, display_name, avatar_url)
        if not thread:
            # Fallback to channel if thread creation failed
            thread = channel
        
        # 3. Handle Notification Logic
        pattern_summaries = ", ".join([f"{a.emoji} {a.pattern_name}" for a in alerts])
        
        # Pings for critical
        ping_role = ""
        if emoji == "🔴":
            staff_role_id = os.getenv("CRITICAL_ALERT_ROLE_ID")
            if staff_role_id:
                ping_role = f"<@&{staff_role_id}> "

        if thread == channel:
            # Fallback message
            await channel.send(f"{ping_role}{emoji} **Karta klienta {mention}**: {len(alerts)} vzorců ({pattern_summaries})")
        else:
            # Thread exists/created, post update if it's an auto-detection (no itx)
            await thread.send(f"{ping_role}🔄 **Nová detekce pro kartu:** {pattern_summaries}")

        # 3. Thread: Detailed Embed
        embed = discord.Embed(
            title="🎯 Detekce vzorců: Karta",
            description=f"U klienta **{mention}** byly zachyceny tyto vzorce:",
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)

        for alert in alerts:
            field_name = f"{alert.emoji} {alert.pattern_name}"
            field_val = (
                f"{alert.description}\n"
                f"⚠️ **Úroveň:** {alert.level_label}\n"
                f"💡 **Doporučení:** {alert.recommended_action}"
            )
            embed.add_field(name=field_name, value=field_val, inline=False)

        embed.set_footer(text=f"ID: {user_id} • NePornu Pattern Engine")

        view = ModeratorAssistantView(user_id, self._guild_id)
        
        try:
            await thread.send(embed=embed, view=view)
        except Exception as e:
            logger.error(f"Failed to send alert to thread: {e}")

    async def send_alert(self, alert: PatternAlert):
        await self.send_batched_alerts(alert.user_id, [alert])

    async def get_or_create_thread(self, user_id: int, display_name: str, avatar_url: Optional[str]) -> Optional[discord.Thread]:
        guild = self.bot.get_guild(self._guild_id)
        if not guild: return None
        
        r = await get_redis_client()
        try:
            thread_id = await r.get(K_THREAD(self._guild_id, user_id))
            if thread_id:
                thread = guild.get_thread(int(thread_id))
                if not thread:
                    # Try fetching it if not in cache
                    try:
                        thread = await guild.fetch_channel(int(thread_id))
                    except: pass
                
                if thread:
                    if thread.archived:
                        await thread.edit(archived=False)
                    return thread

            # Create new thread
            channel = await self.get_alert_channel()
            if not channel: return None
            
            main_msg = await channel.send(f"📂 **Otevírám kartu pro klienta**: <@{user_id}>")
            thread = await main_msg.create_thread(
                name=f"🆔 Karta: {display_name}",
                auto_archive_duration=10080
            )
            
            await r.set(K_THREAD(self._guild_id, user_id), str(thread.id), ex=14 * 86400)
            await r.set(K_THREAD_UID(thread.id), str(user_id), ex=14 * 86400)
            return thread
        except Exception as e:
            logger.error(f"Error in get_or_create_thread: {e}")
            return None
        finally:
            await r.close()

    async def create_manual_thread(self, user_id: int, itx: discord.Interaction, detectors) -> bool:
        guild = itx.guild
        member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        
        display_name = member.display_name if member else f"Uživatel {user_id}"
        avatar_url = member.display_avatar.url if member else None
        mention = member.mention if member else f"<@{user_id}>"

        thread = await self.get_or_create_thread(user_id, display_name, avatar_url)
        if not thread:
            return False

        # Build diagnostic embed to post into the new thread
        r = await get_redis_client()
        try:
            embed = await detectors.build_diagnostic_embed(r, user_id, mention, display_name, avatar_url)
            view = ModeratorAssistantView(user_id, self._guild_id)
            await thread.send(
                content=f"📝 **Manuální otevření karty** uživatelem {itx.user.mention}.",
                embed=embed, 
                view=view
            )
            return True
        except Exception as e:
            logger.error(f"Error sending diagnostic to manual thread: {e}")
            return False
        finally:
            await r.close()
