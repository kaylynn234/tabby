from typing import Any, Awaitable, Callable

from aiohttp.web import (
    Application as Application,
    Request as Request,
    Response as Response,
)

from .core import Route as Route
from .error_boundary import ErrorBoundary as ErrorBoundary
from .extract import (
    register_extractor as register_extractor,
    run_extractor as run_extractor,
    FromRequest as FromRequest,
    Use as Use,
    Query as Query,
    Bytes as Bytes,
    JSON as JSON,
)


# TODO: update the documentation note to be more immediately helpful & not just redirect to `routing.core.Route`
def route(
    method: str,
    path: str,
    **kwargs,
) -> Callable[[Callable[..., Awaitable[Any]]], Route]:
    """A decorator that wraps an asynchronous handler function into a `Route`.

    This decorator forwards to the `routing.core.Route` constructor. See its documentation for more details.
    """

    def inner(func: Callable[..., Awaitable[Any]]) -> Route:
        return Route(method, path, func, **kwargs)

    return inner


# Necessary for correct type information :/


def connect(path: str, **kwargs):
    return route("CONNECT", path, **kwargs)


def head(path: str, **kwargs):
    return route("HEAD", path, **kwargs)


def get(path: str, **kwargs):
    return route("GET", path, **kwargs)


def delete(path: str, **kwargs):
    return route("DELETE", path, **kwargs)


def options(path: str, **kwargs):
    return route("OPTIONS", path, **kwargs)


def patch(path: str, **kwargs):
    return route("PATCH", path, **kwargs)


def post(path: str, **kwargs):
    return route("POST", path, **kwargs)


def put(path: str, **kwargs):
    return route("PUT", path, **kwargs)


def trace(path: str, **kwargs):
    return route("TRACE", path, **kwargs)
