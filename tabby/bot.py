import asyncpg
from aiohttp import ClientSession
from asyncpg import Pool
from discord import Guild, Intents, Member, Message
from discord.ext import commands
from discord.ext.commands import Bot, Cog

from .config import Config
from .local_api import LocalAPI
from .util import Acquire


DEFAULT_INTENTS = Intents.default() | Intents(members=True, message_content=True)


class Tabby(Bot):
    _local_api: LocalAPI | None

    config: Config
    pool: Pool
    session: ClientSession

    @property
    def local_api(self) -> LocalAPI:
        """The local API instance."""

        if self._local_api is None:
            raise RuntimeError("tried to access local API before initialization")

        return self._local_api

    def __init__(self, *, config: Config, **kwargs) -> None:
        intents = kwargs.pop("intents", DEFAULT_INTENTS)

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            description="A small Discord bot for servers that I like",
            **kwargs,
        )

        self._local_api = None
        self.config = config

    async def setup_hook(self) -> None:
        self.pool = asyncpg.create_pool(**vars(self.config.database))
        self.session = ClientSession()

    async def close(self) -> None:
        await super().close()
        await self.pool.close()
        await self.session.close()

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

    @property
    def local_api(self) -> LocalAPI:
        """The local API instance."""

        return self.bot.local_api

    @property
    def config(self) -> Config:
        """The application-wide configuration value."""

        return self.bot.config

    @property
    def session(self) -> ClientSession:
        """The session used for making HTTP requests."""

        return self.bot.session
