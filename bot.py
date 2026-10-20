"""Mr.Gambler entry point. Add future features as extensions in COGS."""
import asyncio
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger('mr-gambler')

COGS = (
    'cogs.radio',
    # 'cogs.music',  # Add future features here.
)


class MrGambler(commands.Bot):
    async def setup_hook(self):
        for extension in COGS:
            await self.load_extension(extension)
            log.info('Loaded %s', extension)
        synced = await self.tree.sync()
        log.info('Globally registered commands: %s', ', '.join(cmd.name for cmd in synced))


intents = discord.Intents.default()
bot = MrGambler(command_prefix='!', intents=intents)


@bot.event
async def on_ready():
    log.info('Logged in as %s', bot.user)


async def main():
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        raise RuntimeError('Set DISCORD_TOKEN in your .env file')
    async with bot:
        await bot.start(token)


if __name__ == '__main__':
    asyncio.run(main())
