import asyncio
import base64
import random
import re
from typing import Annotated

from aiohttp import web
from aiohttp.web import HTTPBadRequest, HTTPFound, HTTPForbidden, HTTPNotFound
from discord import Asset, DefaultAvatar, NotFound, Permissions
from pydantic import BaseModel, ValidationError
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from yarl import URL

from .session import AuthorizedSession
from .template import Templates
from .. import routing
from .. import util
from ..bot import Tabby
from ..level import LEVELS
from ..routing import Response, Request
from ..routing.extract import Query, Use
from ..util import API_URL


TEMPLATE_PATTERN = re.compile(rf"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")
CDN_URL = URL("https://cdn.discordapp.com")
USER_GUILDS_URL = API_URL.join(URL("users/@me/guilds"))


class AuthParams(BaseModel):
    code: str
    state: str


@routing.get("/oauth/callback", name="callback")
async def callback(
    params: Annotated[AuthParams, Query(AuthParams)], request: Annotated[Request, Use(Request)]
) -> Response:
    await AuthorizedSession.complete_authorization(request, code=params.code, state=params.state)

    # TODO: redirect to home page/dashboard
    raise HTTPFound("/")


class PartialGuild(BaseModel):
    id: int
    name: str
    icon: str | None
    permissions: int


@routing.get("/api/guilds")
async def guilds(
    bot: Annotated[Tabby, Use(Tabby)],
    session: Annotated[AuthorizedSession, Use(AuthorizedSession)],
) -> Response:
    await session.refresh()

    headers = {"authorization": f"Bearer {session.access_token}"}

    async with bot.session.get(USER_GUILDS_URL, headers=headers) as response:
        payload = await response.json()

    assert isinstance(payload, list)

    results = []
    for raw_guild in payload:
        try:
            guild = PartialGuild.parse_obj(raw_guild)
        # Most likely the guild was unavailable
        except ValidationError:
            continue

        # We only care about guilds that Tabby shares with the user
        if not bot.get_guild(guild.id):
            continue

        if guild.icon:
            icon_url = Asset._from_guild_icon(bot._connection, guild.id, guild.icon).url
        else:
            icon_url = None

        results.append(
            {
                "id": guild.id,
                "name": guild.name,
                "icon_url": icon_url,
                "managed": Permissions(guild.permissions).manage_guild,
            }
        )

    return web.json_response(results)


class LeaderboardPage(BaseModel):
    after: int | None


@routing.get("/api/guilds/{guild_id}/leaderboard")
async def guild_leaderboard(
    guild_id: int,
    page: Annotated[LeaderboardPage, Query(LeaderboardPage)],
    bot: Annotated[Tabby, Use(Tabby)],
) -> Response:
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

        results.append(
            {
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
            }
        )

    return web.json_response(results)


class ProfileParams(BaseModel):
    username: str
    tag: int
    avatar_url: str


@routing.get("/api/guilds/{guild_id}/members/{member_id}/profile", name="profile")
async def guild_member_profile(
    guild_id: int,
    member_id: int,
    params: Annotated[ProfileParams, Query(ProfileParams)],
    templates: Annotated[Templates, Use(Templates)],
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

    try:
        avatar_url = URL(params.avatar_url)
    except ValueError:
        raise HTTPBadRequest(text="invalid avatar URL") from None

    # We don't want to make the API fetch completely arbitrary URLs. If somebody *tries*, we can be mean to them :)
    if avatar_url.host != CDN_URL.host:
        raise HTTPForbidden(text="only cdn.discordapp.com URLs may be passed as avatar URLs - try harder, jackass")

    async with bot.db() as connection:
        record = await connection.fetchrow(query, guild_id, member_id)

    if record is None:
        raise HTTPNotFound(text="member/guild not found")

    rank = record["leaderboard_position"]
    level = LEVELS.get(record["total_xp"])

    if level.level_ceiling:
        required_xp = util.humanize(level.level_ceiling - level.level_floor)
    else:
        required_xp = "???"

    style_context = {
        "background_url": bot.web_url.join(URL("assets/background.webp")),
        "level_background_url": bot.web_url.join(URL("assets/level_background.png")),
    }

    stylesheet = await templates.render("rank.css", context=style_context)

    page_context = {
        "avatar": params.avatar_url,
        "name": params.username,
        "tag": f"#{params.tag:0>4}",
        "progress": f"{level.progress * 100:2f}%",
        "current_xp": util.humanize(level.gained_xp),
        "required_xp": required_xp,
        "level": level.level,
        "rank": f"#{rank:,}",
        "styles": f"<style>{stylesheet}</style>",
    }

    page = await templates.render("rank.html", context=page_context)
    page_data = _data_url(page, content_type="text/html")

    async with bot.webdrivers.get() as driver:
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, lambda: _render_rank_card(driver, page_data))

    return web.json_response({"data": base64.b64encode(image).decode()})


def _render_rank_card(driver: Firefox, url: URL | str) -> bytes:
    driver.get(str(url))
    element = driver.find_element(By.CLASS_NAME, value="container")

    return element.screenshot_as_png


def _data_url(content: str, *, content_type: str) -> str:
    content = base64.b64encode(content.encode()).decode()

    return f"data:{content_type};base64,{content}"
