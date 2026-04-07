import os
import json
import time
import logging
from datetime import datetime, timezone
import re
from typing import List, Optional
import discord
from shared.python.config import config
from shared.python.redis_client import get_redis_client
from .common import K_ALERT, K_MUTE, K_MSG, K_THREAD, K_THREAD_UID, K_FOLLOWUP, K_NOTES, PatternAlert, is_staff

logger = logging.getLogger("PatternDetector")


class ResolveModal(discord.ui.Modal, title="Vyřešit a uzavřít kartu"):
    resolution = discord.ui.TextInput(
        label="Jak byl klient dořešen?",
        style=discord.TextStyle.paragraph,
        placeholder="Např. Probrali jsme krizový plán, uživatel je stabilizovaný...",
        required=True,
        max_length=1000,
    )

    def __init__(self, user_id: int, guild_id: int):
        super().__init__()
        self.user_id = user_id
        self.guild_id = guild_id

    async def on_submit(self, itx: discord.Interaction):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        gid = self.guild_id
        uid = self.user_id
        
        try:
            # 1. Save resolution note
            notes_data = await r.get(K_NOTES(gid, uid))
            notes_list = json.loads(notes_data) if notes_data else []
            notes_list.append({
                "ts": int(time.time()),
                "author": f"{itx.user.display_name} (ZÁVĚR)",
                "content": self.resolution.value
            })
            await r.set(K_NOTES(gid, uid), json.dumps(notes_list[-50:]), ex=730 * 86400)
            
            # 2. Mute alerts for 30 days
            await r.set(K_MUTE(gid, uid), "1", ex=30 * 86400)
            
            # 3. Clean up thread mapping
            await r.delete(K_THREAD(gid, uid))
            await r.close()
            
            await itx.followup.send(f"✅ Karta uživatele <@{uid}> byla vyřešena. Poznámka byla uložena a vlákno bude archivováno.", ephemeral=True)
            
            # 4. ARCHIVE thread
            if isinstance(itx.channel, discord.Thread):
                try:
                    await itx.channel.edit(archived=True, locked=False)
                except Exception as e:
                    logger.error(f"Failed to archive thread: {e}")
        except Exception as e:
            logger.error(f"Error in ResolveModal: {e}")
            await itx.followup.send(f"❌ Chyba při ukládání: {e}", ephemeral=True)

class ConfirmDeleteView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=60)
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="Ano, smazat kartu", style=discord.ButtonStyle.danger)
    async def confirm(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.defer(ephemeral=True)
        r = await get_redis_client()
        gid = self.guild_id
        uid = self.user_id
        
        # Mute user for 30 days (INFO) to prevent immediate re-detection
        await r.set(K_MUTE(gid, uid), "1", ex=30 * 86400)
        
        # Clean up thread reference
        from .common import K_THREAD
        await r.delete(K_THREAD(gid, uid))
        await r.close()
        
        await itx.followup.send(f"✅ Karta uživatele <@{uid}> byla smazána.", ephemeral=True)
        
        # DELETE thread if it is a thread
        if isinstance(itx.channel, discord.Thread):
            try:
                await itx.channel.delete()
            except Exception as e:
                logger.error(f"Failed to delete thread: {e}")

    @discord.ui.button(label="Zrušit", style=discord.ButtonStyle.secondary)
    async def cancel(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.send_message("Operace byla zrušena.", ephemeral=True)

class ModeratorAssistantView(discord.ui.View):
    def __init__(self, user_id: int, guild_id: int):
        super().__init__(timeout=None)
        self.user_id = user_id
        self.guild_id = guild_id

    @discord.ui.button(label="📁 Vyřešit", style=discord.ButtonStyle.success, custom_id="pat:resolve")
    async def resolve_trigger(self, itx: discord.Interaction, button: discord.ui.Button):
        await itx.response.send_modal(ResolveModal(self.user_id, self.guild_id))

    @discord.ui.button(label="🗑️ Smazat kartu", style=discord.ButtonStyle.danger, custom_id="pat:handled")
    async def mark_handled(self, itx: discord.Interaction, button: discord.ui.Button):
        view = ConfirmDeleteView(self.user_id, self.guild_id)
        await itx.response.send_message(
            "⚠️ **Opravdu chcete smazat tuto kartu?**\nTato akce je nevratná a vlákno bude odstraněno.", 
            view=view, 
            ephemeral=True
        )

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

    async def send_batched_alerts(self, user_id: int, alerts: List[PatternAlert], gid: int = None):
        if not alerts:
            return
        
        if gid is None:
            gid = self._guild_id
            
        if gid == 999:
            # Discourse Alert
            await self.send_discourse_alert(user_id, alerts)
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

    async def send_discourse_alert(self, user_id: int, alerts: List[PatternAlert]):
        if not alerts: return
        
        from .common import K_DISCOURSE_TOPIC
        r = await get_redis_client()
        existing_topic_id = await r.get(K_DISCOURSE_TOPIC(user_id))
        
        # 1. Get Discourse Username
        import subprocess
        cmd = f'docker exec app sudo -u postgres psql -d discourse -t -A -c "SELECT username FROM users WHERE id = {user_id}"'
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        username = res.stdout.strip() or f"User_{user_id}"
        
        # 2. Get Diagnostic Context
        from .detectors import PatternDetectors
        det = PatternDetectors(self._guild_id)
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y%m%d")
        ctx = await det.get_diagnostic_context(r, 999, user_id, now, today)

        # 3. Build Rich Markdown
        pattern_summaries = ", ".join([f"{a.emoji} {a.pattern_name}" for a in alerts])
        title = f"Karta: {username}" # Simpler title for better matching
        
        stats = ctx["stats_7d"]
        content = f"### 🔍 Diagnostický přehled: {username} (Update: {pattern_summaries})\n"
        content += f"Komplexní analýza aktivity a chování uživatele @{username}\n\n"
        
        content += "#### 📊 Klíčové metriky\n"
        content += "| Metrika | Hodnota |\n"
        content += "| :--- | :--- |\n"
        content += f"| 📅 Aktivita (7d) | {stats['msg_count']} zpráv |\n"
        content += f"| 📈 Celkem zpráv | {ctx['all_time']['total_msgs']} |\n"
        content += f"| ✍️ Délka zpráv | {stats['avg_words_per_msg']:.1f} slov/zpr |\n"
        content += f"| 🤝 Interaktivita | {int(ctx['interactivity'])}% (odpovědi) |\n"
        content += f"| 💤 Dny ticha | {ctx['days_inactive']} dní |\n"
        content += f"| 🕰️ Poslední aktivita | {ctx['last_msg_date']} |\n"
        content += f"| 🌱 V komunitě | {ctx['join_days']} dní (od {ctx['first_msg_date']}) |\n\n"
        
        content += f"#### 🚑 Naléhavost zásahu\n{ctx['urgency_text']}\n\n"
        
        if ctx.get("ai_summary"):
            content += f"#### 🤖 AI Shrnutí aktivity\n{ctx['ai_summary']}\n\n"
        
        notes = ctx["notes"]
        content += "#### 📝 Poznámky\n"
        if notes:
            for n in notes[-3:]:
                dt = datetime.fromtimestamp(n['ts']).strftime("%d.%m.")
                content += f"- `[{dt}]` **{n['author']}**: {n['content']}\n"
        else:
            content += "*Žádné poznámky k tomuto klientovi.*\n"
        content += "\n"
        
        affinities = ctx["affinities"]
        if affinities:
            content += "#### 🎯 Naplnění vzorců\n"
            for af in affinities:
                filled = int(af['score'] / 10)
                bar = "▰" * filled + "▱" * (10 - filled)
                content += f"{af['emoji']} **{af['name']}** `{af['score']}%`\n`{bar}`\n*{af['desc']}*\n\n"
        
        content += "#### 🚨 Aktivní poplachy\n"
        for a in alerts:
            content += f"**{a.emoji} {a.pattern_name}** ({a.level_label})\n"
            content += f"{a.description}\n"
            content += f"💡 *Doporučení:* {a.recommended_action}\n\n"
        
        content += f"[Profil na fóru](/u/{username})"
        
        # 4. Create or Reply via Rails Runner
        import base64
        title_b64 = base64.b64encode(title.encode('utf-8')).decode('ascii')
        content_b64 = base64.b64encode(content.encode('utf-8')).decode('ascii')
        target_topic_id = existing_topic_id or 0
        
        ruby_script = f"""
        require 'base64'
        title = Base64.decode64('{title_b64}').force_encoding('UTF-8')
        raw = Base64.decode64('{content_b64}').force_encoding('UTF-8')
        topic_id = {target_topic_id}
        
        if topic_id > 0 && Topic.exists?(topic_id)
          creator = PostCreator.new(Discourse.system_user, topic_id: topic_id, raw: raw, skip_validations: true)
          post = creator.create
          puts 'SUCCESS_REPLY:' + topic_id.to_s if post
        else
          # Double check by title if Redis is missing the key
          existing = Topic.where(category_id: 11, title: title).first
          if existing
             creator = PostCreator.new(Discourse.system_user, topic_id: existing.id, raw: raw, skip_validations: true)
             post = creator.create
             puts 'SUCCESS_REPLY:' + existing.id.to_s if post
          else
             creator = PostCreator.new(Discourse.system_user, title: title, raw: raw, category: 11, tags: ['novy'], skip_validations: true)
             post = creator.create
             puts 'SUCCESS_NEW:' + post.topic_id.to_s if post
          end
        end
        """
        
        cmd = ["docker", "exec", "-u", "discourse", "-w", "/var/www/discourse", "app", "bundle", "exec", "rails", "runner", ruby_script]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True)
            if "SUCCESS" in res.stdout:
                id_match = re.search(r'SUCCESS_(NEW|REPLY):(\d+)', res.stdout)
                if id_match:
                    new_id = id_match.group(2)
                    await r.set(K_DISCOURSE_TOPIC(user_id), new_id, ex=365 * 86400)
                    logger.info(f"Discourse alert {id_match.group(1)} for {username} (Topic ID: {new_id})")
            else:
                logger.error(f"Failed to create/reply Discourse alert: {res.stdout} {res.stderr}")
        except Exception as e:
            logger.error(f"Error calling rails runner: {e}")
        finally:
            await r.close()

    async def send_alert(self, alert: PatternAlert, gid: int = None):
        await self.send_batched_alerts(alert.user_id, [alert], gid=gid)

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
            
            if isinstance(channel, discord.ForumChannel):
                # Create a Forum Post
                thread_with_msg = await channel.create_thread(
                    name=f"🆔 Karta: {display_name}",
                    content=f"📂 **Karta klienta**: <@{user_id}>",
                    auto_archive_duration=10080
                )
                thread = thread_with_msg.thread
            else:
                # Standard Text Channel Thread
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
