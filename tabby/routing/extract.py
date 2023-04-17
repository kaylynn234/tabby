from abc import ABCMeta, abstractmethod
import json
import typing
from typing import Annotated, Any, Awaitable, Callable, Generic, ParamSpec, Protocol, Type, TypeVar

import pydantic
from aiohttp.web import Application, Request
from pydantic import BaseModel

from . import core
from . import util


EXTRACTORS: dict[type, util.Handler] = {}


@typing.runtime_checkable
class FromRequest(Protocol):
    from_request: Callable[[Request], Awaitable[Any]]


ExtractorT = TypeVar("ExtractorT")


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
    """Extract data from the request's path parameters.

    This type is used internally for path parameters, so it's unlikely that you'll need to use it yourself.
    """

    _type: Type[InnerT]
    _param: str

    def __init__(self, type: Type[InnerT], param: str) -> None:
        self._type = type
        self._param = param

    async def from_request(self, request: Request) -> InnerT:
        return pydantic.parse_obj_as(self._type, request.match_info)


class Bytes:
    """Extract the contents of the request body as `bytes`."""

    async def from_request(self, request: Request) -> bytes:
        return await request.read()


class Deserialize(Generic[InnerT], metaclass=ABCMeta):
    """An ABC used to implement generic deserializers for the request body.

    When implementing a new deserialization strategy, you should extend this class and use your own implementation of
    the `deserialize` method.

    To deserialize the request body, the `deserialize` method is passed two values:

    1. The raw body contents, as bytes.
    2. The body's charset, specified using a charset name (a `str`) or `None`.

    The result of calling `deserialize` is then converted to an instance of the target type.

    Note that while an implementation of `deserialize` can mostly do whatever it wants to produce an output, the result
    still needs to be interpreted as the target type. For this reason, most implementations will want to return a `dict`
    or similar structure.

    If your needs are sufficiently unique, you can also access the target type using the `type` attribute when
    deserializing.

    One caveat to be aware of is that `Deserialize` is type-agnostic; you can pass any (supported) type to it when using
    it as an extractor. Because of this, you should avoid special-casing deserialization behaviour, lest you give
    yourself a nasty surprise! 
    """

    type: Type[InnerT]

    def __init__(self, type: Type[InnerT]) -> None:
        self.type = type

    async def from_request(self, request: Request) -> InnerT:
        content = await request.read()
        result = self.deserialize(content, request.charset)

        return self.type.parse_obj(result)

    @abstractmethod
    def deserialize(self, content: bytes, encoding: str | None):
        """Deserialize `content` into an arbitrary Python object."""

        raise NotImplementedError


class JSON(Deserialize[InnerT]):
    """Deserialize JSON data from the request body."""

    def deserialize(self, content: bytes, encoding: str | None):
        return json.loads(content.decode(encoding or "utf-8"))


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


@register_extractor(Application)
async def _extract_app(request: Request) -> Application:
    return request.app

