import discord
import os
import asyncio
from datetime import datetime, timezone

TOKEN = None
try:
    with open('/app/.env', 'r') as f:
        for line in f:
            if line.startswith('BOT_TOKEN='):
                TOKEN = line.split('=')[1].strip().strip('"')
except Exception as e:
    print(f"Error reading .env: {e}")

GUILD_ID = 615171377783242769

class PatternAnalyzerClient(discord.Client):
    async def on_ready(self):
        print(f'Logged in as {self.user}')
        guild = self.get_guild(GUILD_ID)
        if not guild:
            print("Guild not found")
            await self.close()
            return

        leave_keywords = ['končím', 'odcházím', 'mějte se', 'sbohem', 'vzdávám', 'nemá to cenu']
        relapse_keywords = ['relaps', 'selhal', 'znovu jsem', 'zase', 'upadl']
        activation_keywords = ['začínám', 'výzva', 'den 1', 'jsem tu nový', 'rozhodl jsem se', 'přidávám se']

        patterns = {
            'leave': [],
            'relapse': [],
            'activation': []
        }

        print("Scanning channels for contexts...")
        target_channels = ['hlavní-chat', 'zdravé-návyky', 'denik-abstinence', 'potřebuji-pomoc']
        for channel in guild.text_channels:
            if not any(tc in channel.name for tc in target_channels):
                continue
            if not channel.permissions_for(guild.me).read_message_history:
                continue
                
            try:
                # Limit to 1000 messages
                messages = [msg async for msg in channel.history(limit=1000)]
                messages.reverse()
                
                for i, msg in enumerate(messages):
                    if msg.author.bot: continue
                    content = msg.content.lower()
                    
                    found_category = None
                    if any(kw in content for kw in leave_keywords):
                        found_category = 'leave'
                    elif any(kw in content for kw in relapse_keywords):
                        found_category = 'relapse'
                    elif any(kw in content for kw in activation_keywords):
                        found_category = 'activation'
                        
                    if found_category:
                        # Grab context window (-1 to +2 messages)
                        start = max(0, i - 1)
                        end = min(len(messages), i + 3)
                        context_strs = []
                        for j in range(start, end):
                            m = messages[j]
                            indicator = ">> " if j == i else "   "
                            name = "Bot" if m.author.bot else m.author.name
                            text = m.clean_content.replace('\n', ' ')
                            context_strs.append(f"{indicator}{name}: {text}")
                            
                        patterns[found_category].append({
                            'channel': channel.name,
                            'context': context_strs
                        })
            except Exception as e:
                print(f"Could not read {channel.name}: {e}")

        # Output results
        for category, items in patterns.items():
            print(f"\n================ {category.upper()} CONTEXTS ================")
            for item in items[:15]:  # Limit output to avoid massive logs
                print(f"[{item['channel']}]")
                for line in item['context']:
                    print(line[:150]) # truncate long messages
                print("-" * 50)
                
        await self.close()

if not TOKEN:
    print("No Discord token found. Make sure to run inside the bot container or source .env")
    exit(1)
    
intents = discord.Intents.default()
intents.message_content = True
client = PatternAnalyzerClient(intents=intents)
client.run(TOKEN)
