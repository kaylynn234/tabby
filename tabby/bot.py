import asyncpg
from asyncpg import Pool
from discord import Guild, Intents, Member, Message
from discord.ext import commands
from discord.ext.commands import Bot, Cog

from .config import Config
from .util import Acquire


DEFAULT_INTENTS = Intents.default() | Intents(members=True, message_content=True)


class Tabby(Bot):
    config: Config
    pool: Pool

    def __init__(self, *, config: Config, **kwargs) -> None:
        intents = kwargs.pop("intents", DEFAULT_INTENTS)

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            description="A small Discord bot for servers that I like",
            **kwargs,
        )

        self.config = config

    async def setup_hook(self) -> None:
        self.pool = asyncpg.create_pool(self.config.auth.database_url)

    async def close(self) -> None:
        await super().close()
        await self.pool.close()

    def db(self) -> Acquire:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection, reusing an older
        connection if necessary.
        """

        return Acquire(pool=self.pool)


class TabbyCog(Cog):
    bot: Tabby

    def __init__(self, bot: Tabby) -> None:
        self.bot = bot

    def db(self) -> Acquire:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection, reusing an older
        connection if necessary.
        """

        return Acquire(pool=self.bot.pool)
