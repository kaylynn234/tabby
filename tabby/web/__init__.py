from typing import Annotated

from aiohttp import web

from . import routes
from .session import SessionStorage
from .. import routing
from ..bot import Tabby
from ..resources import STATIC_DIRECTORY
from ..routing import Application, ErrorBoundary, Use


def setup_application(bot: Tabby) -> Application:
    """Build and configure an `Application` instance for the provided `bot`."""

    middlewares = [
        ErrorBoundary.default(),
        SessionStorage(bot),
    ]

    app = Application(middlewares=middlewares)
    app["bot"] = bot

    app.add_routes([
        routes.auth_callback,
        routes.user_guilds,
        routes.member_profile,
        routes.guild_leaderboard,
        web.static("/", STATIC_DIRECTORY),
    ])

    bot._api = app

    return app


@routing.register_extractor(Tabby)
async def _extract_bot(app: Annotated[Application, Use(Application)]) -> Tabby:
    return app["bot"]
