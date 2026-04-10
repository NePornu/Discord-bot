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
from shared.python.config import config
from shared.python.redis_client import get_redis_client

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
            # Optimize CPU usage by limiting threads
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = 1
            opts.inter_op_num_threads = 1
            
            self.session = ort.InferenceSession(
                model_path,
                sess_options=opts,
                providers=["CPUExecutionProvider"]
            )
            self.input_name = self.session.get_inputs()[0].name
            print(f"[NSFW] Model úspěšně načten. Vstup: {self.input_name} (Threads: 1)")
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

    def format_nsfw_score(self, score: float) -> str:
        """Returns a human-readable representation of the NSFW score."""
        percentage = min(max(score * 100, 0), 100)
        
        if score < 0.2:
            level = "✅ Bezpečný"
        elif score < 0.5:
            level = "⚠️ Nízké riziko"
        elif score < 0.8:
            level = "🔥 Možné riziko"
        elif score < 0.95:
            level = "🚨 Vysoké riziko"
        else:
            level = "☢️ Kritické riziko"
            
        return f"{level} ({percentage:.1f}%)"

    async def get_user_nsfw_score(self, user: discord.User) -> tuple[float, str]:
        """
        Returns (raw_score, formatted_score) for a user's avatar.
        This method does not send any alerts.
        """
        if not user.display_avatar:
            return 0.0, "Žádný avatar"

        try:
            url = user.display_avatar.replace(size=256).url
            img_bytes = await self.download_image(url)
            if not img_bytes:
                return 0.0, "Nelze stáhnout"

            img_hash = hashlib.md5(img_bytes).hexdigest()

            if img_hash in self.cache:
                scores = self.cache[img_hash]
            else:
                arr = self.preprocess(img_bytes)
                if arr is None:
                    return 0.0, "Chyba při zpracování"
                scores = self.predict(arr)
                self.update_cache(img_hash, scores)

            score = scores[1]
            return score, self.format_nsfw_score(score)
        except Exception as e:
            print(f"[NSFW] Error in get_user_nsfw_score: {e}")
            return 0.0, f"Chyba: {str(e)}"

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

    async def check_avatar(self, user, trigger="manual"):
        """
        Checks a user's avatar.
        trigger: "join", "update", or "manual"
        """
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
            print(f"[NSFW] {trigger.upper()} check: User {user} ({user.id}) | Scores: {scores}")

            score = scores[1]
            threshold = getattr(config, "NSFW_THRESHOLD", 0.5)
            formatted_score = self.format_nsfw_score(score)
            is_nsfw = score > threshold

            # JOIN TRIGGER: Update mod log in "čekárna" and log to "logu čekárny"
            if trigger == "join":
                # 1. Update existing join message in Verification Channel
                verif_channel_id = getattr(config, "VERIFICATION_CHANNEL_ID", None)
                try:
                    r = await get_redis_client()
                    state_key = f"verify:state:{user.id}"
                    # Save score to Redis for Go Core to pick up in final report
                    await r.hset(state_key, "avatar_score", formatted_score)
                    
                    msg_id = None
                    for attempt in range(10): # 10 attempts * 0.5s = 5s total
                        msg_id = await r.hget(state_key, "approve_msg_id")
                        if msg_id:
                            break
                        await asyncio.sleep(0.5)
                        
                    await r.aclose()
                    
                    if not msg_id:
                        print(f"[NSFW] Warning: 'approve_msg_id' not found in Redis after 5s for user {user.id}. Cannot update join message.")
                        return

                    channel = self.bot.get_channel(int(verif_channel_id))
                    if not channel:
                        channel = await self.bot.fetch_channel(int(verif_channel_id))
                    
                    if channel:
                        try:
                            msg = await channel.fetch_message(int(msg_id))
                            new_content = msg.content
                            if "Avatar Check:" not in new_content:
                                new_content = new_content.replace("Status:", f"Avatar Check: `{formatted_score}`\nStatus:")
                            await msg.edit(content=new_content)
                            print(f"[NSFW] Updated join message {msg_id} with score {formatted_score}")
                        except Exception as e:
                            print(f"[NSFW] Failed to fetch or edit join message {msg_id}: {e}")
                except Exception as e:
                    print(f"[NSFW] Redis/Message update error: {e}")

                # 2. Log to SERVER_LOG_CHANNEL_ID (Wait Log)
                log_channel_id = getattr(config, "LOG_CHANNEL_ID", 1404416148077809705)
                log_channel = self.bot.get_channel(log_channel_id)
                if not log_channel:
                    try: log_channel = await self.bot.fetch_channel(log_channel_id)
                    except: pass
                    
                if log_channel:
                    status_text = "**NSFW DETEKOVAN** 🚨" if is_nsfw else "**OK** ✅"
                    log_embed = discord.Embed(
                        title="🛡️ Avatar Join Check",
                        description=f"Uživatel: {user.mention} (`{user.id}`)\nRiziko: `{formatted_score}`\nStatus: {status_text}",
                        color=discord.Color.red() if is_nsfw else discord.Color.green(),
                        timestamp=discord.utils.utcnow()
                    )
                    log_embed.set_thumbnail(url=url)
                    await log_channel.send(embed=log_embed)

            # UPDATE OR MANUAL: Log to Profile Logs (AVATAR_LOG_CHANNEL_ID / PROFILE_LOG_CHANNEL_ID)
            else:
                target_log_id = getattr(config, "PROFILE_LOG_CHANNEL_ID", 1404734262485450772)
                alert_channel = self.bot.get_channel(target_log_id)
                if not alert_channel:
                    try: alert_channel = await self.bot.fetch_channel(target_log_id)
                    except: pass

                if alert_channel:
                    if is_nsfw:
                        embed = discord.Embed(
                            title="🚨 NSFW Avatar Detekován (Změna)",
                            description=f"Uživatel {user.mention} (`{user.id}`) si změnil profilovku.\nRiziko: `{formatted_score}`",
                            color=discord.Color.red(),
                            timestamp=discord.utils.utcnow()
                        )
                        embed.set_thumbnail(url=url)
                        view = NSFWActionView(user)
                        await alert_channel.send(embed=embed, view=view)
                    else:
                        # Log SFW change too? Based on user request "při změně avatara to pošli do profile logs"
                        log_embed = discord.Embed(
                            title="✅ Avatar Check (Změna)",
                            description=f"Uživatel: {user.mention} (`{user.id}`)\nRiziko: `{formatted_score}`\nStatus: **OK**",
                            color=discord.Color.green(),
                            timestamp=discord.utils.utcnow()
                        )
                        log_embed.set_thumbnail(url=url)
                        await alert_channel.send(embed=log_embed)

        except Exception as e:
            print(f"[NSFW] Chyba při kontrole avataru {user}: {e}")

    @commands.Cog.listener()
    async def on_user_update(self, before, after):
        if before.avatar != after.avatar:
            if after.avatar:
                print(f"[NSFW] Globální změna avataru u {after} - provádím kontrolu...")
                await self.check_avatar(after, trigger="update")

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Catch server-specific avatar changes
        if before.guild_avatar != after.guild_avatar:
            if after.display_avatar:
                print(f"[NSFW] Serverová změna avataru u {after} v {after.guild} - provádím kontrolu...")
                await self.check_avatar(after, trigger="update")

    @commands.Cog.listener()
    async def on_member_join(self, member):
        """Checks the avatar of a newly joined member."""
        if member.bot:
            return
        print(f"[NSFW] Nový člen {member} - provádím kontrolu avataru...")
        await self.check_avatar(member, trigger="join")

    @commands.is_owner()
    @commands.command(name="nsfwsync")
    async def nsfw_sync_cmd(self, ctx, limit: int = None, user: discord.Member = None):
        """Ruční spuštění skenu avatarů (prefix)."""
        if user:
            await ctx.send(f"⏳ Skenuji uživatele: {user.display_name}")
            await self.run_user_scan(ctx.channel, user)
        else:
            msg = f"⏳ Spouštím sken {'všech' if not limit else limit} avatarů..."
            await ctx.send(msg)
            await self.run_full_scan(ctx.channel, limit)

    @discord.app_commands.command(name="nsfwsync", description="Manuální sken profilovek na serveru")
    @discord.app_commands.describe(limit="Maximální počet uživatelů k otestování (volitelné)", user="Konkrétní uživatel k otestování (volitelné)")
    @discord.app_commands.checks.has_permissions(administrator=True)
    async def nsfw_sync_slash(self, interaction: discord.Interaction, limit: int = None, user: discord.Member = None):
        """Ruční spuštění skenu avatarů (slash)."""
        if user:
            await interaction.response.send_message(f"⏳ Skenuji uživatele: {user.display_name}", ephemeral=True)
            await self.run_user_scan(interaction.channel, user)
        else:
            msg = f"⏳ Spouštím sken {'všech' if not limit else limit} profilovek..."
            await interaction.response.send_message(msg, ephemeral=True)
            await self.run_full_scan(interaction.channel, limit)

    async def run_user_scan(self, channel, user: discord.Member):
        if user.avatar or user.display_avatar:
             await self.check_avatar(user)
             if channel:
                 await channel.send(f"✅ Sken dokončen pro uživatele {user.display_name}.")
        else:
             if channel:
                 await channel.send(f"❌ Uživatel {user.display_name} nemá profilovku.")

    async def run_full_scan(self, channel, limit: int = None):
        count = 0
        for guild in self.bot.guilds:
            for member in guild.members:
                if limit and count >= limit:
                    break
                
                if member.avatar or member.display_avatar:
                    await self.check_avatar(member)
                    count += 1
                    await asyncio.sleep(0.3)
            
            if limit and count >= limit:
                break
        
        if channel:
            await channel.send(f"✅ Sken dokončen. Zkontrolováno {count} avatarů.")
            await asyncio.sleep(0.5) # Extra breath after full scan

async def setup(bot):
    await bot.add_cog(AvatarNSFW(bot))
