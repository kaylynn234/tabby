import typing
from typing import Any, Awaitable, Callable, Generic, ParamSpec, Protocol, Type, TypeVar

import pydantic
from aiohttp.web import Request
from pydantic import BaseModel

from . import core
from . import util


EXTRACTORS: dict[type, util.Handler] = {}


@typing.runtime_checkable
class FromRequest(Protocol):
    from_request: Callable[[Request], Awaitable[Any]]


class Use:
    """The base extractor type, allowing dependency injection from a request."""

    _handler: util.Handler

    def __init__(self, dependency: Any) -> None:
        type_extractor = _extractor_for_type(dependency)

        if type_extractor is not None:
            self._handler = type_extractor
        elif isinstance(dependency, FromRequest):
            self._handler = dependency.from_request
        elif callable(dependency):
            self._handler = core.get_handler(dependency)
        else:
            raise TypeError(f"{dependency} is not a valid dependency type")

    async def from_request(self, request: Request) -> Any:
        return await self._handler(request)


InnerT = TypeVar("InnerT", bound=BaseModel)


class Param(Generic[InnerT]):
    """Extract data from a request's path parameters.

    This type is used internally for path parameters, so it's unlikely that you'll need to use it yourself.
    """

    _type: Type[InnerT]
    _param: str

    def __init__(self, type: Type[InnerT], param: str) -> None:
        self._type = type
        self._param = param

    async def from_request(self, request: Request) -> InnerT:
        return pydantic.parse_obj_as(self._type, request.match_info)


class Body(Generic[InnerT]):
    """Extract data from the request body."""

    _type: Type[InnerT]

    def __init__(self, type: Type[InnerT]) -> None:
        self._type = type

    async def from_request(self, request: Request) -> InnerT:
        return self._type.parse_obj(await request.json())


class Query(Generic[InnerT]):
    """Extract data from a request's query parameters."""

    _type: Type[InnerT]

    def __init__(self, type: Type[InnerT]) -> None:
        self._type = type

    async def from_request(self, request: Request) -> InnerT:
        return self._type.parse_obj(request.query)


def _extractor_for_type(dependency: Any) -> util.Handler | None:
    if not isinstance(dependency, type):
        return None

    for base in dependency.__mro__:
        if base in EXTRACTORS:
            return EXTRACTORS[base]

    return None


ReturnT = TypeVar("ReturnT")
ParamsT = ParamSpec("ParamsT")


def register_extractor(type_: type) -> Callable[[Callable[ParamsT, Awaitable[ReturnT]]], Callable[ParamsT, Awaitable[ReturnT]]]:
    """A decorator that registers an asynchronous function as an extractor for a specific type.

    The wrapped function will be used to extract values annotated with the specified type or one of its subclasses.
    """

    def wrapper(func: Callable[ParamsT, Awaitable[ReturnT]]) -> Callable[ParamsT, Awaitable[ReturnT]]:
        injected = func if util.is_bare_handler(func) else core.get_handler(func)
        base_type = typing.get_origin(type_) or type_

        if not isinstance(base_type, type):
            raise TypeError(f"expected type, found {type(base_type)}")
        elif base_type in EXTRACTORS:
            raise TypeError(f"an extractor for {base_type.__name__} is already registered")

        EXTRACTORS[base_type] = injected

        return func  # type: ignore

    return wrapper


@register_extractor(Request)
async def _extract_request(request: Request) -> Request:
    return request
