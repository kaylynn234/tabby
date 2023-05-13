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
from discord import AllowedMentions, Guild, Intents, Member, Message, User
from discord.backoff import ExponentialBackoff
from discord.ext import commands
from discord.ext.commands import Bot, Cog, Context
from yarl import URL

from .config import Config
from .routing import Application
from .util import TTLCache


DEFAULT_INTENTS = Intents.default() | Intents(members=True, message_content=True)
LOGGER = logging.getLogger(__name__)


class Tabby(Bot):
    _web: Application | None

    config: Config
    pool: Pool
    session: ClientSession
    cached_users: TTLCache[int, User]

    def __init__(self, *, config: Config, **kwargs) -> None:
        intents = kwargs.pop("intents", DEFAULT_INTENTS)

        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            description="A small Discord bot for servers that I like",
            allowed_mentions=AllowedMentions.none(),
            **kwargs,
        )

        self._web = None
        self.config = config
        self.pool = asyncpg.create_pool(**vars(self.config.database))  # type: ignore
        self.session = ClientSession()
        self.cached_users = TTLCache(expiry=60 * 120)

    @property
    def web(self) -> Application:
        """The bot's corresponding web application."""

        if self._web is None:
            raise RuntimeError("tried to access web application before initialization")

        return self._web

    @property
    def web_url(self) -> URL:
        return URL.build(
            scheme="http",
            host=self.config.web.host,
            port=self.config.web.port,
        )

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

    async def fetch_user(self, user_id: int, /, *, force: bool = False) -> User:
        """Fetch a `User` instance from the API.

        This method is overridden to return cached members where possible, avoiding repeated calls to Discord's API when
        they're unnecessary.

        If the internal cache is stale and needs to be updated, the `force` keyword-only argument may be used to fetch a
        new `User` object, regardless of its cache status.
        """

        if user_id in self.cached_users and not force:
            return self.cached_users[user_id]

        result = self.cached_users[user_id] = await super().fetch_user(user_id)

        return result

    async def on_command_error(
        self,
        ctx: Context,
        exception: commands.CommandError,
        force: bool = False,
    ) -> None:
        command_name = ctx.command.name if ctx.command else "(none)"
        original = exception.original if hasattr(exception, "original") else exception  # type: ignore
        LOGGER.error("exception in command %s", command_name, exc_info=original)

        if isinstance(original, (discord.Forbidden, commands.CommandNotFound)):
            return

        has_cog_error_handler = ctx.cog.has_error_handler() if ctx.cog else False
        has_local_error_handler = ctx.command.has_error_handler() if ctx.command else False
        has_any_error_handler = has_local_error_handler or has_cog_error_handler

        # Unless this handler was called forcefully, we should assume that the command-local or cog-local error handler
        # has already handled anything that needed to be dealt with
        if has_any_error_handler and not force:
            return

        message = original.args[0] if original.args else f"Unhandled {type(original).__name__} exception."

        await ctx.send(message)

    def web_url_for(self, resource: str, **kwargs) -> URL:
        """Build a URL to a route.

        `resource` is the name of the route/resource to generate a URL for.
        `kwargs` is a mapping of path segments to values. This mapping is used to fill in dynamic portions of the URL
        (i.e path parameters) with values.
        """

        url_parts = {attr: str(value) for attr, value in kwargs.items()}
        path = self.web.router[resource].url_for(**url_parts)

        return self.web_url.join(path)

    def db(self) -> PoolAcquireContext:
        """Retrieve a database connection guard.

        This value can be used within an asynchronous context manager to acquire a database connection.
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
    def api(self) -> Application:
        """An `Application` instance representing the bot's API."""

        return self.bot.web

    @property
    def config(self) -> Config:
        """The application-wide configuration value."""

        return self.bot.config

    @property
    def session(self) -> ClientSession:
        """The session used for making HTTP requests."""

        return self.bot.session
