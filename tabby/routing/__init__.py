import functools
from typing import Any, Awaitable, Callable

from aiohttp import hdrs
from aiohttp.web import RouteDef

from .core import build_route
from .extract import (
    FromRequest as FromRequest,
    Use as Use,
    Query as Query,
    Body as Body,
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


def _route_with(method: str):
    def inner(path: str, **kwargs):
        return route(method, path, **kwargs)

    return inner


connect = _route_with(hdrs.METH_CONNECT)
head = _route_with(hdrs.METH_HEAD)
get = _route_with(hdrs.METH_GET)
delete = _route_with(hdrs.METH_DELETE)
options = _route_with(hdrs.METH_OPTIONS)
patch = _route_with(hdrs.METH_PATCH)
post = _route_with(hdrs.METH_POST)
put = _route_with(hdrs.METH_PUT)
trace = _route_with(hdrs.METH_TRACE)
