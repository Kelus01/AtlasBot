import asyncio
import logging
import os
from pathlib import Path

import disnake
from disnake.ext import commands
from dotenv import load_dotenv


ROOT_DIR = Path(__file__).parent

async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_dotenv(ROOT_DIR / ".env")
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN is missing.")

    intents = disnake.Intents.default()
    intents.message_content = True
    bot = commands.InteractionBot(intents=intents)

    for cog_file in (ROOT_DIR / "cogs").glob("*.py"):
        if cog_file.name != "__init__.py":
            try:
                bot.load_extension(f"cogs.{cog_file.stem}")
            except commands.errors.NoEntryPointError:
                continue

    await bot.start(token)


if __name__ == "__main__":
    asyncio.run(main())
