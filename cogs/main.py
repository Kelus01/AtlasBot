import disnake
from disnake.ext import commands


class General(commands.Cog):
    def __init__(self, bot: commands.InteractionBot) -> None:
        self.bot = bot

    @commands.slash_command(description="test")
    async def ping(self, inter: disnake.ApplicationCommandInteraction) -> None:
        latency_ms = round(self.bot.latency * 1000)
        await inter.response.send_message(f"Pong! Затримка: {latency_ms} мс")

    @commands.slash_command(description="Hi test")
    async def hello(self, inter: disnake.ApplicationCommandInteraction) -> None:
        await inter.response.send_message(f"Hi, {inter.author.mention}!")


def setup(bot: commands.InteractionBot) -> None:
    bot.add_cog(General(bot))


