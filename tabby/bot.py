from __future__ import annotations

import sys
import logging
import traceback
from typing import ClassVar

import asyncpg
import discord
from aiohttp import ClientSession
from asyncpg import Pool
from discord import Guild, Intents, Member, Message
from discord.ext import commands
from discord.ext.commands import Bot, Cog, Context

from .config import Config
from .local_api import LocalAPI
from .util import Acquire


DEFAULT_INTENTS = Intents.default() | Intents(members=True, message_content=True)
LOGGER = logging.getLogger(__name__)


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
        self.pool = await asyncpg.create_pool(**vars(self.config.database))  # type: ignore
        self.session = ClientSession()

    async def close(self) -> None:
        await super().close()

        if not hasattr(self, "pool"):
            return

        await self.pool.close()
        await self.session.close()

    async def on_command_error(self, ctx: Context, exception: commands.CommandError) -> None:
        command_name = ctx.command.name if ctx.command else "(none)"

        original = exception.original if isinstance(exception, commands.CommandInvokeError) else exception

        if isinstance(original, discord.Forbidden):
            return

        LOGGER.error("exception in command %s", command_name, exc_info=original)
        message = original.args[0] if original.args else f"Unhandled {type(original).__name__} exception."

        await ctx.send(message)

    def db(self) -> Acquire:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection, reusing an older
        connection if necessary.
        """

        return Acquire(pool=self.pool)


class TabbyCog(Cog):
    _should_register: ClassVar[bool] = False

    bot: Tabby

    def __init__(self, bot: Tabby) -> None:
        self.bot = bot

    def __init_subclass__(cls) -> None:
        cls._should_register = True

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
