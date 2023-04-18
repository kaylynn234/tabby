import html
import re
from re import Match
from typing import Annotated

from aiohttp import web
from pydantic import BaseModel

from . import routing
from . import util
from .bot import Tabby
from .level import LevelInfo, LEVELS
from .resources import RESOURCE_DIRECTORY, STATIC_DIRECTORY
from .routing import Application, Request, Response
from .routing.extract import Query, Use


TEMPLATE_PATTERN = re.compile(fr"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")


def setup_application(bot: Tabby) -> Application:
    """Build and configure an `Application` instance for the provided `bot`."""

    app = Application()
    app["bot"] = bot
    app.add_routes([
        member_profile,
        web.static("/", STATIC_DIRECTORY),
    ])

    bot._api = app

    return app


@routing.register_extractor(Tabby)
async def extract_bot(app: Annotated[Application, Use(Application)]) -> Tabby:
    return app["bot"]


class ProfileParams(BaseModel):
    username: str
    tag: int
    avatar: str


@routing.get("/guilds/{guild_id}/members/{member_id}/profile", name="profile")
async def member_profile(
    guild_id: int,
    member_id: int,
    params: Annotated[ProfileParams, Query(ProfileParams)],
    bot: Annotated[Tabby, Use(Tabby)],
) -> Response:
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

    async with bot.db() as connection:
        record = await connection.fetchrow(query, guild_id, member_id)

    assert record is not None

    rank = record["leaderboard_position"]
    level = LEVELS.get(record["total_xp"])

    if level.level_ceiling:
        required_xp = util.humanize(level.level_ceiling - level.level_floor)
    else:
        required_xp = "???"

    raw_context = {
        "avatar": params.avatar,
        "name": params.username,
        "tag": f"#{params.tag:0>4}",
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
