from typing import Any, Awaitable, Callable, Type, TypeVar

from aiohttp import web
from aiohttp.web import HTTPError, Request, Response, StreamResponse
from typing_extensions import Self

from pydantic import ValidationError

from .exceptions import RequestValidationError


ExceptionT = TypeVar("ExceptionT", bound=Exception)
HandlerT = Callable[[ExceptionT, Request], Awaitable[Response]]


class ErrorBoundary:
    """The base error handling primitive.

    `ErrorBoundary` is used to respond to errors that occur within a route, allowing you to render your own error page
    or return different responses based on the exception that occurred.
    """

    _handlers: dict[type, Callable[[Exception, Request], Awaitable[Response]]]

    def __init__(self) -> None:
        self._handlers = {}
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
            return await self.handle_exception(error, request)

    @classmethod
    def default(cls) -> Self:
        """Create an `ErrorBoundary` pre-configured with error handlers for common exception types."""

        new = cls()
        new.register_handler(Exception)(_fallback_error_handler)
        new.register_handler(HTTPError)(_handle_http_error)
        new.register_handler(RequestValidationError)(_handle_validation_error)

        return new

    async def handle_exception(self, exception: Exception, request: Request) -> Response:
        """Handle the provided exception.

        This method will search through the handlers registered on this `ErrorBoundary` until it finds an exception
        handler that matches the provided exception. If no handler matches, this method will re-raise the provided
        exception.
        """

        exception_type = type(exception)

        for base in exception_type.__mro__:
            if base not in self._handlers:
                continue

            handler = self._handlers[base]

            return await handler(exception, request)

        # No handler found, so re-raise the exception
        raise exception

    def register_handler(self, exception: Type[ExceptionT]) -> Callable[[HandlerT[ExceptionT]], HandlerT[ExceptionT]]:
        """A decorator that registers an exception handler for a specific exception type.

        An exception handler is an asynchronous function that takes two parameters and returns a `Response`. The first
        parameter is the raised exception (an `Exception` instance) and the second parameter is the `Request` that
        caused the exception.

        The decorator's `exception` argument is the exception type used for the exception handler.

        If an exception is raised within an exception handler, `ErrorBoundary` will fall back to using the default
        behaviour provided by aiohttp.
        """

        if not isinstance(exception, type):
            raise TypeError(f"expected an exception type, but received {exception!r} instead")

        if not issubclass(exception, Exception):
            raise TypeError(f"{exception} does not derive Exception")

        def inner(func: HandlerT[ExceptionT]) -> HandlerT[ExceptionT]:
            self._handlers[exception] = func  # type: ignore

            return func

        return inner


async def _fallback_error_handler(error: Exception, request: Request) -> Response:
    return web.json_response(
        {"error": str(error)},
        status=500,
    )


async def _handle_http_error(error: HTTPError, request: Request) -> Response:
    message = error.text or f"{error.status}: {error.reason}"

    return web.json_response(
        {"error": message},
        status=error.status,
        headers=error.headers,
    )


async def _handle_validation_error(error: RequestValidationError, request: Request) -> Response:
    response: dict[str, Any] = {"error": error.message}

    if isinstance(error.original, ValidationError):
        response["details"] = error.original.errors()

    return web.json_response(response, status=400)
