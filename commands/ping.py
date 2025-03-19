import random
import time
from discord.ext import commands

QUOTES = [
    "Pornografie je iluze lásky - John Eldredge",
    "Sledování porna mění mozek - Gary Wilson",
    "Dej si pauzu od porna a zjistíš, jak se změní tvůj život - Noah Church",
    "Skutečná intimita není na obrazovce - Matt Fradd"
]

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def ping(self, ctx):
        start_time = time.perf_counter()
        message = await ctx.send("Měření odezvy...")
        end_time = time.perf_counter()
        latency = (end_time - start_time) * 1000
        quote = random.choice(QUOTES)
        await message.edit(content=f'🏓 Pong! Odezva: {latency:.2f} ms\n📖 Citát: "{quote}"')

async def setup(bot):
    await bot.add_cog(Ping(bot))
