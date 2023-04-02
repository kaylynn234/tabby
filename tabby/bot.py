from __future__ import annotations
import asyncio

import sys
import logging
import traceback
from typing import ClassVar

import asyncpg
import discord
from aiohttp import ClientSession
from asyncpg import Pool
from asyncpg.exceptions import CannotConnectNowError
from asyncpg.pool import PoolAcquireContext
from discord import Guild, Intents, Member, Message
from discord.backoff import ExponentialBackoff
from discord.ext import commands
from discord.ext.commands import Bot, Cog, Context

from .config import Config
from .local_api import LocalAPI


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
        self.pool = asyncpg.create_pool(**vars(self.config.database))  # type: ignore
        self.session = ClientSession()

    async def setup_hook(self) -> None:
        backoff = ExponentialBackoff()

        while True:
            try:
                await self.pool
            except CannotConnectNowError:
                delay = backoff.delay()
            else:
                break

            LOGGER.info("connection to database refused, trying again in %d seconds", delay)
            await asyncio.sleep(delay)

        LOGGER.info("connected to database!")

    async def close(self) -> None:
        await super().close()

        if not hasattr(self, "pool"):
            return

        await self.pool.close()
        await self.session.close()

    async def on_command_error(
        self,
        ctx: Context,
        exception: commands.CommandError,
        force: bool = False,
    ) -> None:
        command_name = ctx.command.name if ctx.command else "(none)"
        original = exception.original if isinstance(exception, commands.CommandInvokeError) else exception

        if isinstance(original, (discord.Forbidden, commands.CommandNotFound)):
            return

        has_cog_error_handler = ctx.cog.has_error_handler if ctx.cog else False
        has_local_error_handler = ctx.command.has_error_handler if ctx.command else False
        has_any_error_handler = has_local_error_handler or has_cog_error_handler

        # Unless this handler was called forcefully, we should assume that the command-local or cog-local error handler
        # has already handled anything that needed to be dealt with
        if has_any_error_handler and not force:
            return

        LOGGER.error("exception in command %s", command_name, exc_info=original)
        message = original.args[0] if original.args else f"Unhandled {type(original).__name__} exception."

        await ctx.send(message)

    def db(self) -> PoolAcquireContext:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection, reusing an older
        connection if necessary.
        """

        return self.pool.acquire()


class TabbyCog(Cog):
    _should_register: ClassVar[bool] = False

    bot: Tabby

    def __init__(self, bot: Tabby) -> None:
        self.bot = bot

    def __init_subclass__(cls) -> None:
        cls._should_register = True

    def db(self) -> PoolAcquireContext:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection.
        """

        return self.bot.db()

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
