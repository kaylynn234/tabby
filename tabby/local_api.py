from __future__ import annotations
import dataclasses

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
from .extract import Extractable, ExtractionError
from .level import LevelInfo, LEVELS
from .resources import RESOURCE_DIRECTORY, STATIC_DIRECTORY


if TYPE_CHECKING:
    from .bot import Tabby


LOGGER = logging.getLogger(__name__)
TEMPLATE_PATTERN = re.compile(fr"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")


@dataclasses.dataclass
class ProfileInfo(Extractable):
    guild_id: int
    member_id: int
    username: str
    tag: int
    avatar: str


class LocalAPI(Application):
    bot: Tabby

    def __init__(self, *, bot: Tabby, **kwargs) -> None:
        super().__init__(**kwargs)

        self.bot = bot
        self.bot._local_api = self
        self.add_routes([
            web.get(r"/profiles", self.render_profile, name="profiles"),
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
        try:
            info = ProfileInfo.extract(request.query)
        except ExtractionError as error:
            return Response(status=400, text=str(error))

        query = """
            WITH missing AS
               (SELECT
                    $1::BIGINT AS guild_id,
                    $2::BIGINT AS user_id,
                    0 AS total_xp,
                       (SELECT total_users + 1
                        FROM tabby.user_count
                        WHERE guild_id = $1) AS leaderboard_position),
            result AS
               (SELECT
                    guild_id,
                    user_id,
                    tabby.levels.total_xp,
                    leaderboard_position
                FROM tabby.levels
                LEFT JOIN tabby.leaderboard USING (guild_id, user_id)
                WHERE guild_id = $1 AND user_id = $2)
            SELECT
                guild_id,
                user_id,
                coalesce(result.total_xp, missing.total_xp) AS total_xp,
                coalesce(result.leaderboard_position, missing.leaderboard_position, 1) AS leaderboard_position
            FROM missing
            LEFT JOIN result USING (guild_id, user_id)
        """

        async with self.bot.db() as connection:
            record = await connection.fetchrow(query, info.guild_id, info.member_id)

        assert record is not None

        rank = record["leaderboard_position"]
        level = LEVELS.get(record["total_xp"])

        if level.level_ceiling:
            required_xp = util.humanize(level.level_ceiling - level.level_floor)
        else:
            required_xp = "???"

        raw_context = {
            "avatar": info.avatar,
            "name": info.username,
            "tag": f"#{info.tag:0>4}",
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
