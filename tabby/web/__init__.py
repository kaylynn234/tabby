import builtins
from http import HTTPStatus
from http.cookies import SimpleCookie
import logging
from typing import Annotated, Any

import slugify
from aiohttp import web
from aiohttp.web import HTTPException
from jinja2 import Environment, FileSystemLoader
from multidict import CIMultiDict
from pydantic import ValidationError

from .session import Session, SessionStorage
from .template import Templates
from .. import routing
from .. import util
from ..bot import Tabby
from ..resources import STATIC_DIRECTORY, TEMPLATE_DIRECTORY
from ..routing import Application, ErrorBoundary, Request, Response, Use
from ..routing.exceptions import RequestValidationError


LOGGER = logging.getLogger("tabby.web")


def setup_application(bot: Tabby) -> Application:
    """Build and configure an `Application` instance for the provided `bot`."""

    # These imports are delayed so that the extractor for `Tabby` is registered by the time they're imported.
    from . import endpoints
    from . import pages

    middlewares = [
        ErrorBoundary(error_handler),
        SessionStorage(bot),
        Templates(
            Environment(
                enable_async=True,
                loader=FileSystemLoader(TEMPLATE_DIRECTORY),
                trim_blocks=True,
                lstrip_blocks=True,
            ),
            globals={
                "humanize": util.humanize,
                "slugify": slugify.slugify,
                **vars(builtins),
            }
        ),
    ]

    if bot.config.web.serve_static_files:
        static_files = [web.static("/", STATIC_DIRECTORY)]
    else:
        static_files = []

    routes = [
        pages.home,
        pages.docs_placeholder,
        pages.dashboard,
        pages.invite,
        pages.guild_dashboard,
        pages.guild_leaderboard,
        pages.guild_autoroles,
        pages.guild_autoroles_edit,
        pages.guild_autoroles_delete,
        pages.guild_settings,
        pages.guild_settings_edit,
        pages.rank_card,
        endpoints.callback,
        endpoints.guild_leaderboard,
        endpoints.guild_member_profile,
        *static_files,
    ]

    app = Application(middlewares=middlewares)
    app["bot"] = bot
    bot._web = app

    app.add_routes(routes)

    return app


async def error_handler(error: Exception, request: Request) -> Response:
    should_log = True
    status = 500
    cookies = SimpleCookie()
    headers = CIMultiDict()
    payload: dict[str, Any] = {"error": f"Internal server error ({type(error).__name__}: {error})"}

    if isinstance(error, HTTPException):
        should_log = error.status >= 400
        status = error.status
        cookies = error.cookies
        headers = error.headers.copy()
        payload["error"] = error.text or _status_phrase(error.status)
    elif isinstance(error, RequestValidationError):
        status = 400
        payload["error"] = error.message

        if isinstance(error.original, ValidationError):
            payload["details"] = error.original.errors()

    # `web.json_response` will raise an exception if a Content-Type header is present, so it needs to be removed. Sorry
    # little guy.
    if "Content-Type" in headers:
        del headers["Content-Type"]

    if should_log:
        LOGGER.error("error occurred while handling request", exc_info=error)

    no_error_page = ("/api/", "/oauth/")

    # Only API endpoints need a JSON response, and we can return early in that scenario; there's no need to render an
    # error page.
    if any(request.path.startswith(prefix) for prefix in no_error_page):
        response = web.json_response(data=payload, status=status, headers=headers)
        response.cookies.load(cookies)

        return response

    # Otherwise, we render a graphical error page for the user. Fingers crossed that nothing goes wrong here!
    templates = await Templates.from_request(request)
    session = await Session.from_request(request)

    error_template = templates.environment.get_template("error.html")
    content = await error_template.render_async(
        status_code=status,
        reason=_status_phrase(status),
        message=payload["error"],
        session=session,
    )

    response = Response(
        text=content,
        content_type="text/html",
        status=status,
        headers=headers,
    )

    response.cookies.load(cookies)

    return response


def _status_phrase(status: int) -> str:
    try:
        phrase = HTTPStatus(status).phrase
    except ValueError:
        phrase = "Something Went Very Wrong"

    return f"{status} {phrase}"


@routing.register_extractor(Tabby)
async def _extract_bot(app: Annotated[Application, Use(Application)]) -> Tabby:
    return app["bot"]
