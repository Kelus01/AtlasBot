import asyncio
import os
from pathlib import Path

import disnake
from disnake.ext import commands
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).parent

async def main() -> None:
    load_dotenv(ROOT_DIR / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing.")

    bot = commands.InteractionBot(intents=disnake.Intents.default())

    for cog_file in (ROOT_DIR / "cogs").glob("*.py"):
        if cog_file.name != "__init__.py":
            await bot.load_extension(f"cogs.{cog_file.stem}")

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
