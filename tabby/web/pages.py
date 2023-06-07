import functools
import math
from typing import Annotated

from aiohttp.web import HTTPForbidden, HTTPFound, HTTPNotFound
from discord import Enum, Guild, Member, Role
from pydantic import BaseModel

from . import common
from .common import LeaderboardParams, Settings
from .session import AuthorizedSession, Session
from .template import Templates
from .. import routing
from ..bot import Tabby
from ..routing import Form, Query, Response, Use


class DashboardPage(Enum):
    home = "Home"
    leaderboard = "Leaderboard"
    autoroles = "Autoroles"
    settings = "Settings"

    def __str__(self) -> str:
        return self.value


class WebContext:
    """Represents the context of the invoking web request.

    This class contains the `Tabby` instance associated with the web application, the `Session` of the user who submitted the
    request, and the `Templates` instance containing the template environment.

    Additionally, this class has several helper methods for common tasks, such as rendering templates and checking the
    validity of guild/member arguments.
    """

    bot: Annotated[Tabby, Use(Tabby)]
    session: Annotated[Session | AuthorizedSession, Use(Session)]
    templates: Annotated[Templates, Use(Templates)]

    def __init__(
        self,
        bot: Tabby,
        session: Session | AuthorizedSession,
        templates: Templates,
    ) -> None:
        self.bot = bot
        self.session = session
        self.templates = templates

    @functools.cached_property
    def mutual_guilds(self) -> list[Guild] | None:
        """The list of guilds that the logged-in user shares with the bot.

        If the user is not logged in, this evaluates to `None`.
        """

        if not self.session.authorized:
            return None

        assert isinstance(self.session, AuthorizedSession)

        return self.session.user.mutual_guilds

    def check_guild(self, guild_id: int) -> Guild:
        """Ensure that `guild_id` represents a valid guild, and return the corresponding `Guild` instance.

        If no guild matches the specified ID, this method raises a HTTPException.
        """

        guild = self.bot.get_guild(guild_id)

        if not guild:
            raise HTTPNotFound(text="Server not found")

        return guild

    def check_member_can_edit(self, guild: Guild) -> Member:
        """Ensure that the logged-in user has the "Manage Server" permission in `guild`, and return their corresponding
        `Member` instance.

        If the logged-in user is not a member of `guild`, or if they're missing the "Manage Server" permission, this
        method raises a HTTPException.
        """

        if not isinstance(self.session, AuthorizedSession):
            raise HTTPForbidden(text="Only logged-in users can edit settings")

        member = self.session.as_member_of(guild)

        if not member:
            raise HTTPForbidden(text="You must be a member of this server to edit its settings")

        if not member.guild_permissions.manage_guild:
            raise HTTPForbidden(text="Only members with the \"Manage Server\" permission can edit settings")

        return member

    async def render_page(self, template_name: str, **context) -> Response:
        template = self.templates.environment.get_template(template_name)
        content = await template.render_async(session=self.session, **context)

        return Response(
            text=content,
            content_type="text/html"
        )

    async def render_dashboard_page(
        self,
        template_name: str,
        current_guild: Guild | None = None,
        current_page: DashboardPage | None = None,
        **context
    ) -> Response:
        user_guilds = []
        current_member = None
        can_manage = False

        if self.session.authorized:
            assert isinstance(self.session, AuthorizedSession)

            user_guilds = self.mutual_guilds
            current_member = self.session.as_member_of(current_guild) if current_guild else None
            can_manage = current_member.guild_permissions.manage_guild if current_member else False

        return await self.render_page(
            template_name=template_name,
            guilds=user_guilds,
            current_guild=current_guild,
            current_member=current_member,
            current_page=current_page,
            can_manage=can_manage,
            dashboard_pages=DashboardPage.__members__,
            **context,
        )


@routing.get("/")
async def home(ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    return await ctx.render_page("home.html")


@routing.get("/docs")
async def docs_placeholder(ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    return await ctx.render_page("docs.html")


@routing.get("/dashboard")
async def dashboard(ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    if ctx.mutual_guilds and len(ctx.mutual_guilds) == 1:
        guild: Guild = ctx.mutual_guilds[0]

        raise HTTPFound(f"/dashboard/{guild.id}")

    return await ctx.render_dashboard_page("dashboard.html")


@routing.get("/dashboard/{guild_id}")
async def guild_dashboard(guild_id: int, ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    guild = ctx.check_guild(guild_id)
    params = LeaderboardParams(page=1, limit=3)

    query = """
        SELECT coalesce(count(*), 0)
        FROM tabby.autoroles
        WHERE guild_id = $1
    """

    async with ctx.bot.db() as connection:
        autorole_count: int = await connection.fetchval(query, guild_id)

    leaderboard_preview = await common.get_guild_leaderboard(guild.id, params, ctx.bot)

    return await ctx.render_dashboard_page(
        "guild_dashboard.html",
        current_guild=guild,
        current_page=DashboardPage.home,
        leaderboard_preview=leaderboard_preview,
        autorole_count=autorole_count,
    )


@routing.get("/dashboard/{guild_id}/leaderboard")
async def guild_leaderboard(
    guild_id: int,
    params: Annotated[LeaderboardParams, Query(LeaderboardParams)],
    ctx: Annotated[WebContext, Use(WebContext)]
) -> Response:
    guild = ctx.check_guild(guild_id)

    query = """
        SELECT total_users
        FROM tabby.user_count
        WHERE guild_id = $1
    """

    async with ctx.bot.db() as connection:
        total_users: int = await connection.fetchval(query, guild.id)

    entries = await common.get_guild_leaderboard(guild.id, params, ctx.bot)

    return await ctx.render_dashboard_page(
        "guild_leaderboard.html",
        current_guild=guild,
        current_page=DashboardPage.leaderboard,
        leaderboard_entries=entries,
        leaderboard_page=max(params.page, 1),
        leaderboard_total_pages=math.ceil(total_users / 100),
    )


@routing.get("/dashboard/{guild_id}/autoroles")
async def guild_autoroles(guild_id: int, ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    guild = ctx.check_guild(guild_id)
    autoroles = await common.get_guild_autoroles(guild_id, ctx.bot)
    current_autorole_ids = {int(autorole.role_id) for autorole in autoroles}

    def is_available(role: Role) -> bool:
        return role.is_assignable() and role.id not in current_autorole_ids

    available_roles = sorted(filter(is_available, guild.roles), reverse=True)

    return await ctx.render_dashboard_page(
        "guild_autoroles.html",
        current_guild=guild,
        current_page=DashboardPage.autoroles,
        available_roles=available_roles,
        autoroles=autoroles,
    )


class EditAutorole(BaseModel):
    role_id: int
    granted_at: int


@routing.post("/dashboard/{guild_id}/autoroles/edit")
async def guild_autoroles_edit(
    guild_id: int,
    params: Annotated[EditAutorole, Form(EditAutorole)],
    ctx: Annotated[WebContext, Use(WebContext)],
) -> Response:
    guild = ctx.check_guild(guild_id)
    ctx.check_member_can_edit(guild)

    await common.create_or_update_guild_autorole(guild.id, params.role_id, params.granted_at, ctx.bot)

    raise HTTPFound(f"/dashboard/{guild.id}/autoroles")


class DeleteAutorole(BaseModel):
    role_id: int


@routing.post("/dashboard/{guild_id}/autoroles/delete")
async def guild_autoroles_delete(
    guild_id: int,
    params: Annotated[DeleteAutorole, Form(DeleteAutorole)],
    ctx: Annotated[WebContext, Use(WebContext)],
) -> Response:
    guild = ctx.check_guild(guild_id)
    ctx.check_member_can_edit(guild)

    await common.remove_guild_autorole(guild.id, params.role_id, ctx.bot)

    raise HTTPFound(f"/dashboard/{guild.id}/autoroles")


@routing.get("/dashboard/{guild_id}/settings")
async def guild_settings(guild_id: int, ctx: Annotated[WebContext, Use(WebContext)]) -> Response:
    guild = ctx.check_guild(guild_id)

    current_settings = await common.get_guild_settings(guild_id, ctx.bot)

    return await ctx.render_dashboard_page(
        "guild_settings.html",
        current_guild=guild,
        current_page=DashboardPage.settings,
        current_settings=current_settings,
    )


@routing.post("/dashboard/{guild_id}/settings/edit")
async def guild_settings_edit(
    guild_id: int,
    params: Annotated[Settings, Form(Settings)],
    ctx: Annotated[WebContext, Use(WebContext)],
) -> Response:
    guild = ctx.check_guild(guild_id)
    ctx.check_member_can_edit(guild)

    await common.edit_guild_settings(guild_id, params, ctx.bot)

    raise HTTPFound(f"/dashboard/{guild.id}/settings")


@routing.get("/card/{guild_id}/{member_id}")
async def rank_card(
    guild_id: int,
    member_id: int,
    ctx: Annotated[WebContext, Use(WebContext)]
) -> Response:
    image = await common.get_guild_member_profile(guild_id, member_id, ctx.templates, ctx.bot)

    return Response(
        body=image,
        content_type="image/png",
    )
