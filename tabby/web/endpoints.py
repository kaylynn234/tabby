import base64
import re
from typing import Annotated

from aiohttp import web
from aiohttp.web import HTTPFound
from pydantic import BaseModel
from selenium.webdriver import Firefox
from selenium.webdriver.common.by import By
from yarl import URL

from . import common
from .common import LeaderboardParams
from .session import AuthorizedSession
from .template import Templates
from .. import routing
from ..bot import Tabby
from ..routing import Response, Request
from ..routing.extract import Query, Use


TEMPLATE_PATTERN = re.compile(rf"{{{{\s*(?P<name>[_a-zA-Z][a-zA-Z0-9_]+)\s*}}}}")
CDN_URL = URL("https://cdn.discordapp.com")


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


@routing.get("/api/guilds/{guild_id}/leaderboard")
async def guild_leaderboard(
    guild_id: int,
    params: Annotated[LeaderboardParams, Query(LeaderboardParams)],
    bot: Annotated[Tabby, Use(Tabby)],
) -> Response:
    results = await common.get_guild_leaderboard(guild_id, params, bot)

    return web.json_response(results)


@routing.get("/api/guilds/{guild_id}/members/{member_id}/profile", name="profile")
async def guild_member_profile(
    guild_id: int,
    member_id: int,
    templates: Annotated[Templates, Use(Templates)],
    bot: Annotated[Tabby, Use(Tabby)],
) -> Response:
    image = await common.get_guild_member_profile(guild_id, member_id, templates, bot)

    return web.json_response({"data": base64.b64encode(image).decode()})


def _render_rank_card(driver: Firefox, url: URL | str) -> bytes:
    driver.get(str(url))
    element = driver.find_element(By.CLASS_NAME, value="container")

    return element.screenshot_as_png


def _data_url(content: str, *, content_type: str) -> str:
    content = base64.b64encode(content.encode()).decode()

    return f"data:{content_type};base64,{content}"
