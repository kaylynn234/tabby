from http import HTTPStatus
from http.cookies import SimpleCookie
import logging
from typing import Annotated, Any

from aiohttp import web
from aiohttp.web import HTTPException
from jinja2 import Environment, FileSystemLoader
from multidict import CIMultiDict
from pydantic import ValidationError

from .session import SessionStorage
from .template import Templates
from .. import routing
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
            )
        ),
    ]

    routes = [
        pages.home,
        endpoints.callback,
        endpoints.guilds,
        endpoints.guild_leaderboard,
        endpoints.guild_member_profile,
        web.static("/", STATIC_DIRECTORY),
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
    payload: dict[str, Any] = {"error": f"Internal server error ({type(error)}: {error})"}

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

    # `web.json_response` will raise an exception if a Content-Type header is present. Meaning that when a Content-Type
    # header exists, it needs to be removed. Sorry little guy.
    if "Content-Type" in headers:
        del headers["Content-Type"]

    if should_log:
        LOGGER.error("error occurred while handling request", exc_info=error)

    no_error_page = ("/api/", "/oauth/")

    # Only API endpoints need a JSON response.
    if any(request.path.startswith(prefix) for prefix in no_error_page):
        response = web.json_response(data=payload, status=status, headers=headers)
        response.cookies.load(cookies)

        return response

    # TODO: render an error page here
    response = Response(
        text=_status_phrase(status),
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
