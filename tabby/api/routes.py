import html
import random
import re
from re import Match
from typing import Annotated

from aiohttp import web
from aiohttp.web import HTTPNotFound
from discord import Asset, DefaultAvatar, NotFound
from pydantic import BaseModel

from .session import Session
from .. import routing
from .. import util
from ..bot import Tabby
from ..level import LevelInfo, LEVELS
from ..resources import RESOURCE_DIRECTORY
from ..routing import Response
from ..routing.extract import Query, Use


TEMPLATE_PATTERN = re.compile(fr"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")


class AuthParams(BaseModel):
    code: str
    state: str


@routing.get("/login", name="login")
async def auth_callback(
    params: Annotated[AuthParams, Query(AuthParams)],
    session: Annotated[Session, Use(Session)],
) -> Response:
    await session.authorize(params.code, params.state)

    # TODO: redirect to home page/dashboard
    return Response()


class LeaderboardPage(BaseModel):
    after: int | None


@routing.get("/guilds/{guild_id}/leaderboard")
async def guild_leaderboard(
    guild_id: int,
    page: Annotated[LeaderboardPage, Query(LeaderboardPage)],
    bot: Annotated[Tabby, Use(Tabby)],
)  -> Response:
    guild = bot.get_guild(guild_id)

    if guild is None:
        raise HTTPNotFound(text="Guild not found")

    query = """
        SELECT
            user_id,
            leaderboard_position,
            total_xp
        FROM tabby.leaderboard
        WHERE guild_id = $1 AND leaderboard_position > $2
    """

    async with bot.db() as connection:
        records = await connection.fetch(query, guild_id, page.after or 0)

    results = []
    for record in records:
        user_id: int = record["user_id"]

        try:
            member = guild.get_member(user_id) or await guild.fetch_member(user_id)
        except NotFound:
            member = None

        if member:
            avatar_url = member.display_avatar.url
            name = member.name
            discriminator = member.discriminator
        else:
            avatar_index = random.randrange(0, len(DefaultAvatar))
            avatar_url = Asset._from_default_avatar(bot._connection, avatar_index)
            name = "Unknown user"
            discriminator = 0

        level_info = LEVELS.get(record["total_xp"])

        results.append({
            "id": str(user_id),
            "name": name,
            "discriminator": f"{discriminator:0>4}",
            "avatar_url": avatar_url,
            "rank": record["leaderboard_position"],
            "level": level_info.level,
            "xp": {
                "total": level_info.xp,
                "this_level": level_info.gained_xp,
                "next_level": level_info.remaining_xp,
                "progress": level_info.progress,
            },
        })

    return web.json_response(results)


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
