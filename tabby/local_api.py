import html
import re
from string import Template

from aiohttp import web
from aiohttp.web import Application, Request, Response
from discord import Enum, Member
from selenium.webdriver import Firefox

from . import util
from .bot import Tabby
from .level import LevelInfo, LEVELS
from .resources import RESOURCE_DIRECTORY, STATIC_DIRECTORY


class LocalAPI(Application):
    bot: Tabby

    def __init__(self, *, bot: Tabby, **kwargs) -> None:
        super().__init__(**kwargs)
        self.bot = bot

        self.add_routes([
            web.static("/", STATIC_DIRECTORY),
            web.get(r"/profiles/{guild_id:\d+}/{member_id:\d+}", self.render_profile),
        ])

    async def render_profile(self, request: Request):
        guild = self.bot.get_guild(int(request.match_info["guild_id"]))
        if not guild:
            return RenderError.unknown_guild.response(status=404)

        member = guild.get_member(int(request.match_info["user_id"]))
        if not member:
            return RenderError.unknown_member.response(status=404)

        query = """
            SELECT
                guild_id,
                user_id,
                coalesce(total_xp, 0) AS total_xp,
                coalesce(leaderboard_position, total_users + 1, 1) AS leaderboard_position,
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
            "completion": f"{level.progress * 100:2f}%",
            "current_xp": util.humanize(level.gained_xp),
            "required_xp": required_xp,
            "level": level.level,
            "rank": f"#{rank:,}",
        }

        context = {key: html.escape(str(value)) for key, value in raw_context.items()}
        template = HTMLTemplate((RESOURCE_DIRECTORY / "rank.html").read_text())

        return Response(
            body=template.substitute(context),
            content_type="text/html",
        )


class RenderError(Enum):
    unknown_guild = "unknown guild"
    unknown_member = "unknown member"

    def response(self, *, status: int = 200) -> Response:
        return Response(text=self.value, status=status)


class HTMLTemplate(Template):
    pattern = re.compile(fr"{{{{\s*(?P<braced>{Template.idpattern})\s*}}}}")
