import functools
from typing import Any, Awaitable, Callable

from aiohttp import hdrs
from aiohttp.web import (
    RouteDef,
    Application as Application,
    Request as Request,
    Response as Response,
)

from .core import build_route
from .extract import (
    register_extractor as register_extractor,
    FromRequest as FromRequest,
    Use as Use,
    Query as Query,
    Bytes as Bytes,
    JSON as JSON,
)

def route(
    method: str,
    path: str,
    **kwargs,
) -> Callable[[Callable[..., Awaitable[Any]]], RouteDef]:
    """A decorator that wraps an asynchronous handler function into a standard aiohttp `RouteDef`.

    This decorator does the same work as `routing.core.build_route`. See its documentation for more details.
    """

    def inner(func: Callable[..., Awaitable[Any]]) -> RouteDef:
        return build_route(method, path, func, **kwargs)

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

