import discord
from discord.ext import commands
import onnxruntime as ort
import numpy as np
from PIL import Image
import aiohttp
import io
import hashlib
import asyncio
import os
from config import config

from config import config

class WarnUserModal(discord.ui.Modal, title="⚠️ Upozornit uživatele"):
    def __init__(self, user: discord.User):
        super().__init__()
        self.user = user
        self.reason = discord.ui.TextInput(
            label="Důvod upozornění", 
            placeholder="Např. Nevhodná profilovka - prosím o změnu.", 
            style=discord.TextStyle.paragraph,
            max_length=500,
            default="Ahoj, tvoje profilovka byla vyhodnocena jako nevhodná. Prosím o její změnu, jinak může dojít k postihu. Děkujeme."
        )
        self.add_item(self.reason)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            msg = (
                f"⚠️ **Upozornění od moderátora NePornu**\n\n"
                f"{self.reason.value}\n\n"
                f"Tato zpráva je automaticky generovaná na základě analýzy tvého profilu."
            )
            await self.user.send(msg)
            await interaction.followup.send(f"✅ Upozornění odesláno uživateli {self.user.name}.", ephemeral=True)
            
            # Update the original message to show it was handled
            if interaction.message:
                embed = interaction.message.embeds[0]
                embed.add_field(name="Akce", value=f"✅ Uživatel upozorněn moderátorem {interaction.user.mention}", inline=False)
                await interaction.message.edit(embed=embed, view=None)
        except Exception as e:
            await interaction.followup.send(f"❌ Nepodařilo se poslat DM: {e}", ephemeral=True)

class NSFWActionView(discord.ui.View):
    def __init__(self, user: discord.User):
        super().__init__(timeout=None)
        self.user = user

    @discord.ui.button(label="Upozornit", style=discord.ButtonStyle.secondary, emoji="⚠️")
    async def warn_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WarnUserModal(self.user))

    @discord.ui.button(label="Je to OK", style=discord.ButtonStyle.success, emoji="✅")
    async def ok_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        try:
            # 1. Log to server-logs (LOG_CHANNEL_ID)
            target_sfw_id = getattr(config, "LOG_CHANNEL_ID", 1404416148077809705)
            log_channel = interaction.client.get_channel(target_sfw_id)
            if log_channel:
                log_embed = discord.Embed(
                    title="✅ Avatar Schválen (Výjimka)",
                    description=f"Moderátor {interaction.user.mention} označil avatar uživatele {self.user.mention} jako v pořádku.\n(Původně vyhodnoceno jako NSFW)",
                    color=discord.Color.blue(),
                    timestamp=discord.utils.utcnow()
                )
                log_embed.set_thumbnail(url=self.user.display_avatar.url)
                await log_channel.send(embed=log_embed)

            # 2. Delete the original alert message
            await interaction.message.delete()
            
            await interaction.followup.send("✅ Avatar byl schválen a upozornění bylo smazáno.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Chyba: {e}", ephemeral=True)

class AvatarNSFW(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        
        # Cesta k modelu
        model_path = os.path.join(os.getcwd(), "nsfw_model.onnx")
        if not os.path.exists(model_path):
            # Zkusíme v bot složce pokud tam není
            model_path = "/root/discord-bot/nsfw_model.onnx"
            
        print(f"[NSFW] Načítám model z: {model_path}")
        
        try:
            self.session = ort.InferenceSession(
                model_path,
                providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            print(f"[NSFW] Model úspěšně načten. Inpu jméno: {self.input_name}")
        except Exception as e:
            print(f"[NSFW] CHYBA při načítání modelu: {e}")
            self.session = None

        self.cache = {}
        self.cache_limit = 500
        self.http = None
        self.scan_task = None

    async def cog_load(self):
        self.http = aiohttp.ClientSession()
        # Start scanning task - DISABLED as per user request (only manual sync now)
        # self.scan_task = asyncio.create_task(self.initial_scan())

    async def cog_unload(self):
        if self.http:
            await self.http.close()
        if self.scan_task:
            self.scan_task.cancel()

    async def initial_scan(self):
        # Wait for bot to be ready if it's not
        await self.bot.wait_until_ready()
        
        # Additional buffer to ensure members are loaded
        await asyncio.sleep(15)
        
        print(f"[NSFW] Začínám úvodní sken všech členů...")
        
        count = 0
        total_scanned = 0
        for guild in self.bot.guilds:
            print(f"[NSFW] Skenuji guildu {guild.name} ({guild.id}), očekávaný počet členů: {guild.member_count}")
            try:
                # Fetch all members to ensure we have the full list in large guilds
                async for member in guild.fetch_members(limit=None):
                    total_scanned += 1
                    if total_scanned % 10 == 0:
                        print(f"[NSFW] Progress: Prohledáno {total_scanned} členů, zkontrolováno {count} avatarů...")
                    
                    if member.display_avatar:
                        await self.check_avatar(member)
                        count += 1
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"[NSFW] Chyba při stahování členů pro {guild.name}: {e}")
        
        print(f"[NSFW] Úvodní sken dokončen. Celkem prohledáno {total_scanned} členů, zkontrolováno {count} avatarů.")

    async def download_image(self, url):
        if not self.http:
            self.http = aiohttp.ClientSession()
        try:
            async with self.http.get(url, timeout=10) as resp:
                if resp.status != 200:
                    return None
                return await resp.read()
        except Exception as e:
            print(f"[NSFW] Chyba při stahování obrázku {url}: {e}")
            return None

    def preprocess(self, img_bytes):
        try:
            img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
            img = img.resize((224, 224))

            # Model expects BGR [0, 255] with mean subtraction (Caffe-style)
            arr = np.asarray(img, dtype=np.float32)
            
            # RGB -> BGR
            arr = arr[:, :, ::-1]
            
            # Mean subtraction (Caffe-style: B=104, G=117, R=123)
            mean = np.array([104, 117, 123], dtype=np.float32)
            arr = (arr - mean).astype(np.float32)
            
            arr = np.expand_dims(arr, axis=0)
            return arr
        except Exception as e:
            print(f"[NSFW] Chyba při preprocessingu: {e}")
            return None

    def predict(self, arr):
        if not self.session:
            return [0.0, 0.0]
        try:
            # Force float32 cast right before inference
            arr = np.asarray(arr, dtype=np.float32)
            out = self.session.run(None, {self.input_name: arr})
            # Return full array [sfw, nsfw]
            return [float(x) for x in out[0][0]]
        except Exception as e:
            print(f"[NSFW] Chyba při predikci: {e}")
            return [0.0, 0.0]

    def update_cache(self, key, value):
        if len(self.cache) >= self.cache_limit:
            # Odstraníme nejstarší
            self.cache.pop(next(iter(self.cache)))
        self.cache[key] = value

    async def check_avatar(self, user):
        if not user.display_avatar:
            return

        try:
            url = user.display_avatar.replace(size=256).url
            img_bytes = await self.download_image(url)
            if not img_bytes:
                return

            img_hash = hashlib.md5(img_bytes).hexdigest()

            if img_hash in self.cache:
                scores = self.cache[img_hash]
            else:
                arr = self.preprocess(img_bytes)
                if arr is None:
                    return
                scores = self.predict(arr)
                self.update_cache(img_hash, scores)

            # Debug log to console
            print(f"[NSFW] DEBUG: User {user} ({user.id}) | Scores: {scores}")

            # Predpokládáme, že index 1 je NSFW
            score = scores[1]
            
            threshold = getattr(config, "NSFW_THRESHOLD", 0.5)
            log_channel_id = getattr(config, "PROFILE_LOG_CHANNEL_ID", None)
            alert_channel_id = getattr(config, "NSFW_ALERT_CHANNEL_ID", config.LOG_CHANNEL_ID)
            
            log_channel = self.bot.get_channel(log_channel_id) if log_channel_id else None
            # Fallback if channel not in cache
            if not log_channel and log_channel_id:
                try:
                    log_channel = await self.bot.fetch_channel(log_channel_id)
                except Exception as e:
                    print(f"[NSFW] Nelze najít log channel {log_channel_id}: {e}")

            alert_channel = self.bot.get_channel(alert_channel_id)
            if not alert_channel and alert_channel_id:
                try:
                    alert_channel = await self.bot.fetch_channel(alert_channel_id)
                except Exception as e:
                    print(f"[NSFW] Nelze najít alert channel {alert_channel_id}: {e}")
            
            is_nsfw = score > threshold
            
            # ROUTING:
            # - NSFW: only to alert_channel (PROFILE_LOG_CHANNEL_ID) with buttons
            # - SFW: only to log_channel (LOG_CHANNEL_ID)
            
            # Define targets based on user preference:
            # Problematické -> PROFILE_LOG_CHANNEL_ID (1404734262485450772)
            # Vše ostatní -> LOG_CHANNEL_ID (1404416148077809705)
            
            target_nsfw_id = getattr(config, "PROFILE_LOG_CHANNEL_ID", 1404734262485450772)
            target_sfw_id = getattr(config, "LOG_CHANNEL_ID", 1404416148077809705)
            
            if is_nsfw:
                print(f"[NSFW] Detekován závadný avatar: {user} (score: {score:.3f})")
                alert_channel = self.bot.get_channel(target_nsfw_id)
                if not alert_channel:
                    try: alert_channel = await self.bot.fetch_channel(target_nsfw_id)
                    except: pass
                
                if alert_channel:
                    embed = discord.Embed(
                        title="🚨 NSFW Avatar Detekován",
                        description=f"Uživatel {user.mention} (`{user.id}`) má potenciálně závadnou profilovku.\nSkóre: `{score:.4f}`",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()
                    )
                    embed.set_thumbnail(url=url)
                    
                    try:
                        view = NSFWActionView(user)
                        await alert_channel.send(embed=embed, view=view)
                    except Exception as e:
                        print(f"[NSFW] Chyba při posílání alertu: {e}")
            else:
                # SFW logic - goes to server logs
                log_channel = self.bot.get_channel(target_sfw_id)
                if not log_channel:
                    try: log_channel = await self.bot.fetch_channel(target_sfw_id)
                    except: pass
                    
                if log_channel:
                    log_embed = discord.Embed(
                        title="✅ Avatar Check",
                        description=f"User: {user.mention} (`{user.id}`)\nScore: `{score:.4f}`\nStatus: **OK**",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    log_embed.set_thumbnail(url=url)
                    try:
                        await log_channel.send(embed=log_embed)
                    except Exception as e:
                        print(f"[NSFW] Chyba při posílání logu: {e}")

        except Exception as e:
            print(f"[NSFW] Chyba při kontrole avataru {user}: {e}")

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        if before.avatar != after.avatar:
            if after.avatar:
                print(f"[NSFW] Globální změna avataru u {after} - provádím kontrolu...")
                await self.check_avatar(after)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Catch server-specific avatar changes
        if before.guild_avatar != after.guild_avatar:
            if after.display_avatar:
                print(f"[NSFW] Serverová změna avataru u {after} v {after.guild} - provádím kontrolu...")
                await self.check_avatar(after)

    @commands.is_owner()
    @commands.command(name="nsfwsync")
    async def nsfw_sync_cmd(self, ctx):
        """Ruční spuštění skenu všech avatarů (prefix)."""
        await ctx.send("⏳ Spouštím sken všech avatarů...")
        await self.run_full_scan(ctx.channel)

    @discord.app_commands.command(name="nsfwsync", description="Manuální sken všech profilovek na serveru")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def nsfw_sync_slash(self, interaction: discord.Interaction):
        """Ruční spuštění skenu všech avatarů (slash)."""
        await interaction.response.send_message("⏳ Spouštím kompletní sken všech profilovek...", ephemeral=True)
        await self.run_full_scan(interaction.channel)

    async def run_full_scan(self, channel):
        count = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                if member.avatar:
                    await self.check_avatar(member)
                    count += 1
                    await asyncio.sleep(0.3)
        
        if channel:
            await channel.send(f"✅ Sken dokončen. Zkontrolováno {count} avatarů.")

async def setup(bot):
    await bot.add_cog(AvatarNSFW(bot))
