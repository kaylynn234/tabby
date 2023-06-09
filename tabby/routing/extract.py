import json
import typing
from abc import abstractmethod
from typing import Any, Awaitable, Callable, Generic, ParamSpec, Protocol, Type, TypeVar

import pydantic
from aiohttp.web import Application, Request
from pydantic import BaseModel, ValidationError

from . import core
from . import util
from .exceptions import (
    InvalidHandler,
    InvalidHandlerReason,
    RequestValidationError,
    ErrorPart,
    ExtractorError,
    RouteError,
)


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
            raise InvalidHandler(
                reason=InvalidHandlerReason.invalid_annotation,
                message=f"{dependency} is not a valid dependency type",
            )

    async def from_request(self, request: Request) -> Any:
        return await self._handler(request)


InnerT = TypeVar("InnerT", bound=BaseModel)


class Param(Generic[InnerT]):
    """Extract data from the request's path parameters.

    This type is used internally for path parameters, so it's unlikely that you'll need to use it yourself.
    """

    _type: Type[InnerT]
    _param: str
    _parser: Type[BaseModel]

    def __init__(self, type: Type[InnerT], param: str) -> None:
        # `fields` is a mapping of field name to (type, default) pairs. `...` indicates that the field is required, but
        # has no default value. Yes, pydantic sucks.
        fields = {param: (type, ...)}

        # We create a dynamic model in order to parse a named value out of the path parameter dictionary. This allows
        # us to handle missing path parameters a lot more gracefully in error messages.
        self._type = type
        self._param = param
        self._parser = pydantic.create_model("Parser", **fields)

    async def from_request(self, request: Request) -> InnerT:
        try:
            parsed = self._parser.parse_obj(request.match_info)
        except ValidationError as error:
            raise RequestValidationError(
                part=ErrorPart.path_parameters,
                original=error,
            )

        # We still need to pull the actual value from the parsed dictionary
        return getattr(parsed, self._param)


class Bytes:
    """Extract the contents of the request body as `bytes`."""

    async def from_request(self, request: Request) -> bytes:
        return await request.read()


class _FromBody(Protocol[InnerT]):
    type: Type[InnerT]

    def __init__(self, type: Type[InnerT]) -> None:
        """Deserialize the request body into a value of `type`."""

        self.type = type

    @abstractmethod
    async def deserialize(self, request: Request) -> Any:
        raise NotImplementedError

    async def from_request(self, request: Request) -> InnerT:
        try:
            result = self.type.parse_obj(await self.deserialize(request))
        except Exception as error:
            raise RequestValidationError(
                part=ErrorPart.request_body,
                original=error,
                message="unable to deserialize body content"
            )

        return result


class JSON(_FromBody[InnerT]):
    """Deserialize JSON data from the request body."""

    async def deserialize(self, request: Request) -> Any:
        return json.loads(await request.text())


class Form(_FromBody[InnerT]):
    """Deserialize form data from the request body."""

    async def deserialize(self, request: Request) -> Any:
        return await request.post()


class Query(Generic[InnerT]):
    """Extract data from a request's query parameters."""

    _type: Type[InnerT]

    def __init__(self, type: Type[InnerT]) -> None:
        self._type = type

    async def from_request(self, request: Request) -> InnerT:
        try:
            return self._type.parse_obj(request.query)
        except ValidationError as error:
            raise RequestValidationError(
                part=ErrorPart.query_parameters,
                original=error,
            )


def _extractor_for_type(dependency: Any) -> util.Handler | None:
    if not isinstance(dependency, type):
        return None

    for base in dependency.__mro__:
        if base in EXTRACTORS:
            return EXTRACTORS[base]

    return None


ReturnT = TypeVar("ReturnT")
ParamsT = ParamSpec("ParamsT")


async def run_extractor(dependency: Any, request: Request) -> Any:
    """Extract a dependency from a request.

    `dependency` is the dependency or extractor to run.
    `request` is the request instance to extract from.

    Any errors that occur during extraction will be wrapped in `ExtractionError`.
    """

    try:
        return await Use(dependency).from_request(request)
    except RouteError:
        raise
    except Exception as error:
        raise ExtractorError(
            extractor=dependency,
            original=error,
            message="running extractors failed",
        )


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
