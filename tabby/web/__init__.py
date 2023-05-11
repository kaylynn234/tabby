from typing import Annotated, Any

from aiohttp import web
from aiohttp.web import HTTPError
from pydantic import ValidationError

from . import routes
from .session import SessionStorage
from .. import routing
from ..bot import Tabby
from ..routing import Application, ErrorBoundary, Request, Response, Use
from ..routing.exceptions import RequestValidationError


def setup_application(bot: Tabby) -> Application:
    """Build and configure an `Application` instance for the provided `bot`."""

    middlewares = [
        ErrorBoundary(error_handler),
        SessionStorage(bot),
    ]

    app = Application(middlewares=middlewares)
    app["bot"] = bot



async def error_handler(error: Exception, request: Request) -> Response:
    if isinstance(error, RequestValidationError):
        payload: dict[str, Any] = {"error": error.message}

        if isinstance(error.original, ValidationError):
            payload["details"] = error.original.errors()

        response = web.json_response(payload, status=400)
    elif isinstance(error, HTTPError):
        message = error.text or f"{error.status}: {error.reason}"
        headers = error.headers.copy()

        if "Content-Type" in headers:
            del headers["Content-Type"]

        response = web.json_response({"error": message}, status=error.status, headers=headers)
    else:
        response = web.json_response({"error": str(error)}, status=500)

    no_error_page = ("/api/", "/oauth/")

    if any(request.path.startswith(prefix) for prefix in no_error_page):
        return response

    return Response(
        text=f"{response.status} {response.reason}",
        status=response.status,
    )


@routing.register_extractor(Tabby)
async def _extract_bot(app: Annotated[Application, Use(Application)]) -> Tabby:
    return app["bot"]
