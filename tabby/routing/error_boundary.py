import logging
from typing import Awaitable, Callable

from aiohttp import web
from aiohttp.web import Request, Response, StreamResponse


LOGGER = logging.getLogger(__name__)


Handler = Callable[[Exception, Request], Awaitable[Response]]


class ErrorBoundary:
    """The base error handling primitive.

    `ErrorBoundary` is used to respond to errors that occur within a route, allowing you to render your own error page
    or return different responses based on the exception that occurred.
    """

    _handler: Handler

    def __init__(self, handler: Handler) -> None:
        self._handler = handler
        # Necessary to mark the instance as a callable middleware.
        web.middleware(self)

    # `handler` is passed as a kwarg when we use middleware, so it must be named `handler` **exactly**, otherwise things
    # will go very terribly wrong.
    #
    # We need to use `StreamResponse` here so that the type is compatible with the `middleware` parameter in the
    # `Application` constructor
    async def __call__(
        self,
        request: Request,
        handler: Callable[[Request], Awaitable[StreamResponse]]
    ) -> StreamResponse:
        try:
            return await handler(request)
        except Exception as error:
            return await self._handler(error, request)
