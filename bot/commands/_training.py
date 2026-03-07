import discord
from discord import app_commands
from discord.ext import commands
import json
import asyncio
import random
import os
import time
from datetime import datetime, timezone

_TRAINING_GUILD_ID = None
try:
    with open("/app/training_ground_config.json", "r") as f:
        _TRAINING_GUILD_ID = int(json.load(f)["guild_id"])
except:
    try:
        with open("training_ground_config.json", "r") as f:
            _TRAINING_GUILD_ID = int(json.load(f)["guild_id"])
    except:
        pass

class TrainingCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.training_active = False
        self.pending_training_msgs = {} # msg_id -> {timestamp, type, channel_id}
        self.quiz_data = [
            {"q": "Jaká je minimální věková hranice pro moderátora?", "a": ["18", "18 let"]},
            {"q": "Jak dlouho musíte být pomocníkem, než se stanete moderátorem?", "a": ["3 měsíce", "3", "tři měsíce"]},
            {"q": "Co znamená zkratka PMO?", "a": ["porno masturbace orgasmus", "porno, masturbace, orgasmus"]},
            {"q": "Do kolika měsíců se uchovávají záznamy v archivních kanálech?", "a": ["24", "24 měsíců", "dva roky"]},
            {"q": "Jak se jmenuje role, která má provozní a právní odpovědnost za OKP?", "a": ["správce", "koordinátor", "správce/koordinátor"]},
            {"q": "Co je to 'Edging'?", "a": ["masturbování u porna bez orgasmu", "masturbace bez orgasmu"]},
            {"q": "Jaký je rozdíl mezi 'Laps' a 'Relaps'?", "a": ["laps je jednorázové, relaps je systematické", "laps je uklouznutí, relaps je vědomé porušení"]}
        ]

    def load_config(self):
        config_path = "/app/training_ground_config.json"
        if not os.path.exists(config_path):
             config_path = "training_ground_config.json"
        
        try:
            with open(config_path, "r") as f:
                return json.load(f)
        except:
            return None

    training = app_commands.Group(
        name="training", 
        description="Příkazy pro trénink moderátorů",
        guild_ids=[_TRAINING_GUILD_ID] if _TRAINING_GUILD_ID else []
    )

    async def get_training_webhook(self, channel):
        webhooks = await channel.webhooks()
        webhook = discord.utils.get(webhooks, name="Training Masquerade")
        if not webhook:
            webhook = await channel.create_webhook(name="Training Masquerade")
        return webhook

    @training.command(name="setup_info", description="Zobrazí informace o tréninkovém serveru")
    async def setup_info(self, interaction: discord.Interaction):
        config = self.load_config()
        if not config:
            return await interaction.response.send_message("❌ Tréninkové pole není nakonfigurováno.", ephemeral=True)
        
        guild_id = int(config["guild_id"])
        guild = self.bot.get_guild(guild_id)
        
        if not guild:
            return await interaction.response.send_message(f"❌ Server s ID {guild_id} nenalezen.", ephemeral=True)
            
        embed = discord.Embed(title="🎮 Moderator Training Ground", color=0x00ff00)
        embed.add_field(name="Název serveru", value=guild.name, inline=False)
        embed.add_field(name="ID serveru", value=str(guild.id), inline=False)
        
        channels = [f"#{c.name}" for c in guild.text_channels]
        embed.add_field(name="Kanály", value=", ".join(channels), inline=False)
        
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @training.command(name="quiz", description="Spustí vědomostní test z manuálu")
    async def quiz(self, interaction: discord.Interaction):
        question = random.choice(self.quiz_data)
        await interaction.response.send_message(f"❓ **Otázka z manuálu:**\n{question['q']}\n*(Odpověz přímo do chatu)*")

        def check(m):
            return m.channel == interaction.channel and m.author == interaction.user

        try:
            msg = await self.bot.wait_for('message', check=check, timeout=30.0)
            if any(ans.lower() in msg.content.lower() for ans in question['a']):
                await interaction.channel.send(f"✅ Správně, {interaction.user.mention}! Skvělá znalost manuálu.")
            else:
                await interaction.channel.send(f"❌ To není úplně ono. Správná odpověď by byla např.: `{question['a'][0]}`")
        except asyncio.TimeoutError:
            await interaction.channel.send(f"⏰ Čas vypršel! Správná odpověď: `{question['a'][0]}`")

    @training.command(name="simulate_nsfw", description="Zasílá simulovaný NSFW obsah (Masquerade)")
    async def simulate_nsfw(self, interaction: discord.Interaction):
        config = self.load_config()
        if not config: return await interaction.response.send_message("❌ Config nenalezen.", ephemeral=True)
        
        guild = self.bot.get_guild(int(config["guild_id"]))
        channel = discord.utils.get(guild.text_channels, name="nsfw-practice")
        if not channel: return await interaction.response.send_message("❌ Kanál nenalezen.", ephemeral=True)

        webhook = await self.get_training_webhook(channel)
        await interaction.response.send_message(f"🚀 Simulace NSFW (Masquerade) zahájena v {channel.mention}", ephemeral=True)

        scenarios = [
            {"username": "HornyTeen69", "avatar": "https://i.pravatar.cc/150?u=1", "content": "Koukněte na tyhle fotky! 🔥 http://leak-content.io/gallery/123"},
            {"username": "OnlyFansPromo", "avatar": "https://i.pravatar.cc/150?u=2", "content": "Sleva 50% na můj obsah jen dnes přes tento link: [SIMULOVANÝ LINK]"},
            {"username": "AnonymousUser", "avatar": "https://i.pravatar.cc/150?u=3", "content": "Posílám nějaké spicy věci... (Obrázek by tu byl, kdybych mohl posílat skutečné NSFW)"}
        ]

        for s in scenarios:
            msg = await webhook.send(content=s["content"], username=s["username"], avatar_url=s["avatar"], wait=True)
            self.pending_training_msgs[msg.id] = {
                "timestamp": datetime.now(timezone.utc),
                "type": "NSFW",
                "channel_id": channel.id
            }
            await asyncio.sleep(5)

    @training.command(name="simulate_spam", description="Simuluje spam od více uživatelů")
    async def simulate_spam(self, interaction: discord.Interaction, count: int = 15):
        config = self.load_config()
        if not config: return await interaction.response.send_message("❌ Config nenalezen.", ephemeral=True)
        
        guild = self.bot.get_guild(int(config["guild_id"]))
        channel = discord.utils.get(guild.text_channels, name="spam-practice")
        if not channel: return await interaction.response.send_message("❌ Kanál nenalezen.", ephemeral=True)

        webhook = await self.get_training_webhook(channel)
        await interaction.response.send_message(f"🚀 Simulace spamu zahájena v {channel.mention}", ephemeral=True)

        users = [
            {"name": "Spammer1", "avatar": "https://i.pravatar.cc/150?u=10"},
            {"name": "BotNet_A", "avatar": "https://i.pravatar.cc/150?u=11"},
            {"name": "FreeMoneyNow", "avatar": "https://i.pravatar.cc/150?u=12"}
        ]

        for i in range(min(count, 50)):
            u = random.choice(users)
            msg = await webhook.send(content=f"JOIN OUR CRYPTO GROUP: http://scam-link.top #{i}", username=u["name"], avatar_url=u["avatar"], wait=True)
            self.pending_training_msgs[msg.id] = {
                "timestamp": datetime.now(timezone.utc),
                "type": "SPAM",
                "channel_id": channel.id
            }
            await asyncio.sleep(random.uniform(0.2, 0.8))

    @training.command(name="simulate_boundary", description="Simuluje uživatele překračujícího hranice (Soukromá zpráva)")
    async def simulate_boundary(self, interaction: discord.Interaction):
        config = self.load_config()
        if not config: return await interaction.response.send_message("❌ Config nenalezen.", ephemeral=True)
        
        guild = self.bot.get_guild(int(config["guild_id"]))
        channel = discord.utils.get(guild.text_channels, name="rules-and-info") # Posting here for public view during training
        if not channel: return await interaction.response.send_message("❌ Kanál nenalezen.", ephemeral=True)

        webhook = await self.get_training_webhook(channel)
        await interaction.response.send_message("🚀 Simulace překročení hranic (Boundary Test) zahájena.", ephemeral=True)

        msg = await webhook.send(
            content="**[SOUKROMÁ ZPRÁVA - SIMULACE]**\nAhoj moderátore, cítím se hrozně sám. Mohl bys mi věnovat pár hodin každý večer? Nikdo jiný mi nerozumí a v chatu se stydím. Potřebuju, abys mě vedl. Ozvi se prosím.",
            username="ZmatenyUzivatel",
            avatar_url="https://i.pravatar.cc/150?u=50",
            wait=True
        )
        await channel.send("💡 *Moderátor by měl nyní v chatu vysvětlit, jak by na takovou zprávu reagoval podle části 'Práce s klienty' (např. nastavení hranic, nabídka komunitního prostoru).*")

    @training.command(name="simulate_crisis", description="Simuluje krizovou situaci (Sebevražedné tendence)")
    async def simulate_crisis(self, interaction: discord.Interaction):
        config = self.load_config()
        if not config: return await interaction.response.send_message("❌ Config nenalezen.", ephemeral=True)
        
        guild = self.bot.get_guild(int(config["guild_id"]))
        channel = discord.utils.get(guild.text_channels, name="chat-moderation")
        if not channel: return await interaction.response.send_message("❌ Kanál nenalezen.", ephemeral=True)

        webhook = await self.get_training_webhook(channel)
        await interaction.response.send_message(f"🚨 Simulace KRIZE zahájena v {channel.mention}", ephemeral=True)

        msg = await webhook.send(
            content="Už to nezvládám, všechno je zbytečné. Mám v šuplíku prášky a dneska s tím skončím. Sbohem všem.",
            username="Zoufalec",
            avatar_url="https://i.pravatar.cc/150?u=99",
            wait=True
        )
        self.pending_training_msgs[msg.id] = {
            "timestamp": datetime.now(timezone.utc),
            "type": "CRISIS",
            "channel_id": channel.id
        }
        await channel.send("‼️ **POZOR:** Toto je simulace krizové situace. Moderátor musí okamžitě nasadit krizový protokol (odkázání na linky bezpečí, eskalace správci).")

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.id in self.pending_training_msgs:
            data = self.pending_training_msgs.pop(message.id)
            now = datetime.now(timezone.utc)
            reaction_time = (now - data["timestamp"]).total_seconds()
            
            # Find common logging channel for results
            logging_channel = discord.utils.get(message.guild.text_channels, name="rules-and-info")
            if logging_channel:
                embed = discord.Embed(title="⚖️ Training Result: Successful Moderate", color=0x3498db)
                embed.add_field(name="Typ porušení", value=data["type"])
                embed.add_field(name="Reakční čas", value=f"{reaction_time:.2f} sekund")
                embed.set_footer(text="Moderátor zareagoval včas!")
                await logging_channel.send(embed=embed)

async def setup(bot):
    await bot.add_cog(TrainingCog(bot))
