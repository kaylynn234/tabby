import asyncio
import base64
import random

from aiohttp.web import HTTPForbidden, HTTPNotFound
from asyncpg import Record
from discord import Asset, DefaultAvatar, Enum, NotFound
from pydantic import BaseModel
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from yarl import URL

from .template import Templates
from .. import util
from ..bot import Tabby
from ..level import LEVELS
from ..util import Snowflake


CDN_URL = URL("https://cdn.discordapp.com")


class XPBreakdown(BaseModel):
    total: int
    this_level: int
    next_level: int
    progress: float


class LeaderboardEntry(BaseModel):
    id: Snowflake
    name: str
    discriminator: str
    avatar_url: str
    rank: int
    level: int
    xp: XPBreakdown


class LeaderboardParams(BaseModel):
    page: int = 1
    limit: int = 100


async def get_guild_leaderboard(guild_id: int, params: LeaderboardParams, bot: Tabby) -> list[LeaderboardEntry]:
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
        ORDER BY leaderboard_position ASC
        LIMIT $3
    """

    result_limit = max(min(params.limit, 100), 0)
    page_offset = max(params.page - 1, 0) * 100

    async with bot.db() as connection:
        records = await connection.fetch(query, guild_id, page_offset, result_limit)

    results: list[LeaderboardEntry] = []
    for record in records:
        user_id: int = record["user_id"]

        try:
            user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        except NotFound:
            user = None

        if user:
            avatar_url = user.display_avatar.url
            name = user.name
            discriminator = user.discriminator
        else:
            avatar_index = random.randrange(0, len(DefaultAvatar))
            avatar_url = Asset._from_default_avatar(bot._connection, avatar_index).url
            name = "(unknown user)"
            discriminator = 0

        level_info = LEVELS.get(record["total_xp"])

        xp = XPBreakdown(
            total=level_info.xp,
            this_level=level_info.gained_xp,
            next_level=level_info.gained_xp + level_info.remaining_xp,
            progress=level_info.progress,
        )

        entry = LeaderboardEntry(
            id=Snowflake(user_id),
            name=name,
            discriminator=f"{discriminator:0>4}",
            avatar_url=avatar_url,
            rank=record["leaderboard_position"],
            level=level_info.level,
            xp=xp,
        )

        results.append(entry)

    return results


async def get_guild_member_profile(
    guild_id: int,
    member_id: int,
    templates: Templates,
    bot: Tabby,
) -> bytes:
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
        user = bot.get_user(member_id) or await bot.fetch_user(member_id)
    except NotFound:
        raise HTTPNotFound(text="Member not found") from None

    async with bot.db() as connection:
        record = await connection.fetchrow(query, guild_id, member_id)

    if record is None:
        raise HTTPNotFound(text="Member/guild not found")

    rank = record["leaderboard_position"]
    level = LEVELS.get(record["total_xp"])

    if level.level_ceiling:
        required_xp = util.humanize(level.level_ceiling - level.level_floor)
    else:
        required_xp = "???"

    rank_template = templates.environment.get_template("rank.html")
    raw_page_data = await rank_template.render_async(
        internal_url=bot.web_url,
        avatar=user.display_avatar.url,
        name=user.display_name,
        tag=f"#{user.discriminator:0>4}",
        progress=f"{level.progress * 100:2f}%",
        current_xp=util.humanize(level.gained_xp),
        required_xp=required_xp,
        level=level.level,
        rank=f"#{rank:,}",
    )

    page_data = _data_url(raw_page_data, content_type="text/html")

    async with bot.webdrivers.get() as driver:
        loop = asyncio.get_running_loop()
        image = await loop.run_in_executor(None, lambda: _render_rank_card(driver, page_data))

    return image


class Autorole(BaseModel):
    guild_id: Snowflake
    role_id: Snowflake
    granted_at: int


async def get_guild_autoroles(guild_id: int, bot: Tabby) -> list[Autorole]:
    if not bot.get_guild(guild_id):
        raise HTTPNotFound(text="Guild not found")

    query = """
        SELECT *
        FROM tabby.autoroles
        WHERE guild_id = $1
        ORDER BY granted_at DESC
    """

    async with bot.db() as connection:
        records = await connection.fetch(query, guild_id)

    return [Autorole.parse_obj(record) for record in records]


def check_autorole(guild_id: int, role_id: int, bot: Tabby):
    guild = bot.get_guild(guild_id)
    if not guild:
        raise HTTPNotFound(text="Guild not found")

    role = guild.get_role(role_id)
    if not role:
        raise HTTPNotFound(text="Role not found")

    assert bot.user is not None

    me = guild.get_member(bot.user.id)

    assert me is not None

    if role.is_assignable():
        return

    raise HTTPForbidden(text="Tabby can't assign that role to users!")


async def create_or_update_guild_autorole(guild_id: int, role_id: int, granted_at: int, bot: Tabby) -> bool:
    check_autorole(guild_id, role_id, bot)

    # This is what one would consider Woefully Evil; in short, `xmax` is a system column with *many* meanings, but in
    # this case it can be used to divine whether a row was /actually/ inserted, or whether it was instead simply just
    # updated. See the stack overflow answer at `https://stackoverflow.com/questions/39058213` for concrete details on
    # how and why this works.

    query = """
        INSERT INTO tabby.autoroles(guild_id, role_id, granted_at)
        VALUES ($1, $2, $3)
        ON CONFLICT (guild_id, role_id)
        DO UPDATE SET granted_at = $3
        WHERE EXCLUDED.granted_at <> tabby.autoroles.granted_at
        RETURNING (xmax <> 0) AS updated
    """

    async with bot.db() as connection:
        updated = await connection.fetchval(query, guild_id, role_id, granted_at)

    return updated


async def remove_guild_autorole(guild_id: int, role_id: int, bot: Tabby):
    query = """
        DELETE FROM tabby.autoroles
        WHERE guild_id = $1 AND role_id = $2
    """

    async with bot.db() as connection:
        await connection.execute(query, guild_id, role_id)


class Settings(BaseModel):
    stack_autoroles: bool = False


async def get_guild_settings(guild_id: int, bot: Tabby) -> Settings:
    query = """
        SELECT *
        FROM tabby.guild_options
        WHERE guild_id = $1
    """

    async with bot.db() as connection:
        record: Record | None = await connection.fetchrow(query, guild_id)

    if not record:
        return Settings()

    return Settings(**dict(record))


async def edit_guild_settings(guild_id: int, settings: Settings, bot: Tabby):
    query = """
        INSERT INTO tabby.guild_options(guild_id, stack_autoroles)
        VALUES ($1, $2)
        ON CONFLICT (guild_id)
        DO UPDATE SET stack_autoroles = $2
    """

    async with bot.db() as connection:
        await connection.execute(query, guild_id, settings.stack_autoroles)


def _render_rank_card(driver: Firefox, url: URL | str) -> bytes:
    driver.get(str(url))
    element = driver.find_element(By.CLASS_NAME, value="container")

    return element.screenshot_as_png


def _data_url(content: str, *, content_type: str) -> str:
    content = base64.b64encode(content.encode()).decode()

    return f"data:{content_type};base64,{content}"
