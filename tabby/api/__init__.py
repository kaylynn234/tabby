from typing import Annotated

import aiohttp_session
from aiohttp import web
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from . import routes
from .. import routing
from ..bot import Tabby
from ..resources import STATIC_DIRECTORY
from ..routing import Application, ErrorBoundary, Use


def setup_application(bot: Tabby, error_boundary: ErrorBoundary | None = None) -> Application:
    """Build and configure an `Application` instance for the provided `bot`."""

    storage = EncryptedCookieStorage(bot.config.api.secret_key, cookie_name="TABBY_SESSION")

    middlewares = [
        error_boundary or ErrorBoundary.default(),
        aiohttp_session.session_middleware(storage),
    ]

    app = Application(middlewares=middlewares)
    app["bot"] = bot

    app.add_routes([
        routes.member_profile,
        routes.guild_leaderboard,
        web.static("/", STATIC_DIRECTORY),
    ])

    bot._api = app

    return app


@routing.register_extractor(Tabby)
async def _extract_bot(app: Annotated[Application, Use(Application)]) -> Tabby:
    return app["bot"]
