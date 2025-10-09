import discord
from discord.ext import commands
import random

CHANNEL_ID = 1122603558026608681
ROLE_ID = 1375390390282354718
EMOJI_COMBO = [
    '<:panda:1079861118945738792>',
    '<:ninjaparek:1222282030641840129>',
    '<:enter:1348384401494507622>',
]
REACTION_EMOJI = '✅'
CONFIRM_MESSAGES = [
    "Vítej ve výzvě! První krok máš za sebou.",
    "Super, jsi ve hře. Teď je to na tobě!",
    "Přihláška úspěšná – vítej mezi ostatními účastníky.",
    "Začátek je tady. Vítej ve výzvě!",
    "Tvé místo ve výzvě je potvrzené.",
    "Připojení do výzvy proběhlo v pořádku.",
    "Vítej na startovní čáře. Hodně štěstí!",
    "Přijetí potvrzeno – výzva začíná.",
    "Všechno klaplo. Jsi součástí výzvy.",
    "Zapsán do výzvy. Těšíme se na tvůj postup.",
    "Jsi v týmu! Výzva může začít.",
    "Tvé rozhodnutí zkusit to nás těší – vítej!",
    "První krok za tebou, další už jsou na tobě.",
    "Přijali jsme tě do výzvy. Držíme palce!",
    "Výzva je tvoje – a my tu jsme s tebou.",
    "Přihláška přijatá, jdeme na to!",
    "Oficiálně vítej ve výzvě.",
    "Vstup do výzvy proběhl úspěšně.",
    "Vše nastaveno. Teď už je to na tobě.",
    "Vítej mezi těmi, kdo se rozhodli jít do toho.",
]

class EmojiRoleCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or message.channel.id != CHANNEL_ID:
            return

        if all(e in message.content for e in EMOJI_COMBO):
            role = message.guild.get_role(ROLE_ID)
            if role and role not in message.author.roles:
                try:
                    await message.author.add_roles(role, reason="Přihlášení přes emoji kombinaci")
                except Exception as e:
                    print(f"Chyba při přidávání role: {e}")
            try:
                await message.add_reaction(REACTION_EMOJI)
            except Exception as e:
                print(f"Chyba při přidávání reakce: {e}")

            try:
                confirm_msg = random.choice(CONFIRM_MESSAGES)
                await message.channel.send(
                    f"{message.author.mention} {confirm_msg}",
                    reference=message.to_reference()
                )
            except Exception as e:
                print(f"Chyba při posílání potvrzovací zprávy: {e}")

async def setup(bot: commands.Bot):
    await bot.add_cog(EmojiRoleCog(bot))
