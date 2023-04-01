from __future__ import annotations

import html
import logging
import re
from re import Match
from string import Template
from typing import TYPE_CHECKING

import discord
from aiohttp import web
from aiohttp.web import Application, Request, Response
from discord import Enum, Member
from selenium.webdriver import Firefox
from yarl import URL

from . import util
from .config import Config
from .level import LevelInfo, LEVELS
from .resources import RESOURCE_DIRECTORY, STATIC_DIRECTORY


if TYPE_CHECKING:
    from .bot import Tabby


LOGGER = logging.getLogger(__name__)
TEMPLATE_PATTERN = re.compile(fr"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")


class LocalAPI(Application):
    bot: Tabby

    def __init__(self, *, bot: Tabby, **kwargs) -> None:
        super().__init__(**kwargs)

        self.bot = bot
        self.bot._local_api = self
        self.add_routes([
            web.get(r"/profiles/{guild_id:\d+}/{member_id:\d+}", self.render_profile, name="profiles"),
            web.static("/", STATIC_DIRECTORY),
        ])

    @property
    def config(self) -> Config:
        return self.bot.config

    @property
    def url(self) -> URL:
        return URL.build(scheme="http", host=self.config.local_api.host, port=self.config.local_api.port)

    def url_for(self, resource: str, **kwargs) -> URL:
        url_parts = {attr: str(value) for attr, value in kwargs.items()}
        path = self.router[resource].url_for(**url_parts)

        return self.url.join(path)

    async def render_profile(self, request: Request):
        guild = self.bot.get_guild(int(request.match_info["guild_id"]))
        if not guild:
            return Response(text="Unknown guild", status=404)

        member_id = int(request.match_info["member_id"])

        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
        except discord.NotFound:
            return Response(text="Unknown member", status=404)

        query = """
            SELECT
                guild_id,
                user_id,
                coalesce(tabby.levels.total_xp, 0) AS total_xp,
                coalesce(leaderboard_position, total_users + 1, 1) AS leaderboard_position
            FROM tabby.levels
            LEFT JOIN tabby.leaderboard USING (guild_id, user_id)
            LEFT JOIN tabby.user_count USING (guild_id)
            WHERE guild_id = $1 AND user_id = $2
        """

        async with self.bot.db() as connection:
            record = await connection.fetchrow(query, guild.id, member.id)

        assert record is not None

        rank = record["leaderboard_position"]
        level = LEVELS.get(record["total_xp"])

        if level.level_ceiling:
            required_xp = util.humanize(level.level_ceiling - level.level_floor)
        else:
            required_xp = "???"

        raw_context = {
            "avatar": member.display_avatar.with_format("webp").url,
            "name": member.name,
            "tag": f"#{member.discriminator}",
            "progress": f"{level.progress * 100:2f}%",
            "current_xp": util.humanize(level.gained_xp),
            "required_xp": required_xp,
            "level": level.level,
            "rank": f"#{rank:,}",
        }

        context = {key: html.escape(str(value)) for key, value in raw_context.items()}
        template = (RESOURCE_DIRECTORY / "rank.html").read_text()

        return Response(
            body=_substitute(template, context),
            content_type="text/html",
        )


def _substitute(content: str, context: dict) -> str:
    def _substitute_one(match: Match[str]) -> str:
        return context[match.group("name")]

    return TEMPLATE_PATTERN.sub(_substitute_one, content)
