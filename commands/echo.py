from discord.ext import commands

class EchoCommand(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def echo(self, ctx, *, message: str):
        await ctx.message.delete()  # Smazání původní zprávy uživatele
        await ctx.send(message)

async def setup(bot):
    await bot.add_cog(EchoCommand(bot))