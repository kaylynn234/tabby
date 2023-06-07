import contextlib
import contextvars
import functools
import inspect
import re
from contextvars import ContextVar
from inspect import _ParameterKind, Parameter
from typing import (
    Any,
    Awaitable,
    Callable,
    Generic,
    List,
    Literal,
    Mapping,
    ParamSpec,
    Protocol,
    Type,
    TypeAlias,
    TypeVar,
)
import typing

from aiohttp.web import Request, AbstractRouteDef
from aiohttp.web_urldispatcher import AbstractRoute, UrlDispatcher
from pydantic import BaseModel

from . import util
from .exceptions import InvalidHandler, InvalidHandlerReason


ReturnT = TypeVar("ReturnT")
ParamsT = ParamSpec("ParamsT")


ParameterKind: TypeAlias = Literal[
    _ParameterKind.POSITIONAL_ONLY,
    _ParameterKind.POSITIONAL_OR_KEYWORD,
    _ParameterKind.VAR_POSITIONAL,
    _ParameterKind.KEYWORD_ONLY,
    _ParameterKind.VAR_KEYWORD,
]

PATH_PARAMETER_PATTERN = re.compile(r"{(?P<name>.*?)(?:\:(?P<pattern>.*?))?}")
VARIADIC_PARAM_TYPES = (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
POSITIONAL_PARAM_TYPES = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)

DEPENDENCY_STACK: ContextVar[list[Any]] = ContextVar("dependency_stack")


class FnParameterLike(Protocol):
    name: str
    default: Any | Parameter.empty
    annotation: Any | Parameter.empty
    kind: ParameterKind


class FnParameter:
    name: str
    default: Any | Parameter.empty
    annotation: Any | Parameter.empty
    kind: ParameterKind

    def __init__(
        self,
        name: str,
        default: Any | Parameter.empty,
        annotation: Any | Parameter.empty,
        kind: ParameterKind,
    ) -> None:
        self.name = name
        self.default = default
        self.annotation = annotation
        self.kind = kind


class Route(AbstractRouteDef, Generic[ParamsT, ReturnT]):
    """The cornerstone of the routing framework: a route definition.

    The most important component of a route is a handler function. This handler function is used to process each request that
    matches the route's *path pattern* and HTTP method.

    Routes can be called like functions, and expose some additional information for introspection as well.
    """

    handler: util.Handler
    """A request handler suitable for use with aiohttp. This function takes a single `Request` as an argument, and
    returns a `Response` on completion. This function may also raise `HTTPException` to encode a failure or redirect.

    This is the "erased" version of the route callback, where each extractor has been "injected" into the function body.
    For the original route callback, see the `original_handler` attribute.
    """

    original_handler: Callable[ParamsT, Awaitable[ReturnT]]
    """The original route callback function.

    This is an arbitrary asynchronous function that returns a `Response`.
    """

    method: str
    """The route's HTTP method. "*" indicates a wildcard route."""

    path: str
    """The route's path pattern."""

    kwargs: dict[str, Any]
    """Additional arguments provided to the route definition."""

    def __init__(
        self,
        method: str,
        path: str,
        callback: Callable[ParamsT, Awaitable[ReturnT]],
        **kwargs,
    ) -> None:
        """Wrap an asynchronous handler function into a route definition.

        `method` sets which HTTP method to use for the route. "*" may be used as a wildcard.

        `path` sets the path that the route should be served from.
        Similarly to `aiohttp.web`, variable resources are supported within route paths.

        `callback` is the callback function to be executed when the route is matched. Arguments for the function are
        extracted from the request based on the callback's type annotations. Anything that matches the `FromRequest`
        protocol (such as the `Use`, `Body` and `Query` extractors) may be used as a type annotation.

        Additionally, `Annotated` may be used to properly annotate the type of an extractor. This is the recommended
        approach when writing handler functions, as it provides correct type information to your editor/IDE while still
        allowing you to use dependency injection within handlers.

        Any additional keyword arguments are forwarded as-is when the route is registered.
        """

        path_params = set()

        for part in path.split("/"):
            if not part:
                continue

            match = PATH_PARAMETER_PATTERN.fullmatch(part)
            if not match:
                continue

            path_params.add(match.group("name"))

        self.handler = get_handler(callback, path_params=path_params)
        self.original_handler = callback
        self.method = method
        self.path = path
        self.kwargs = kwargs

    async def __call__(self, *args: ParamsT.args, **kwargs: ParamsT.kwargs) -> ReturnT:
        return await self.original_handler(*args, **kwargs)

    def register(self, router: UrlDispatcher) -> List[AbstractRoute]:
        return [router.add_route(self.method, self.path, self.handler, **self.kwargs)]


@contextlib.contextmanager
def _track_recursion(dependency: Any):
    try:
        stack = DEPENDENCY_STACK.get()
    except LookupError:
        stack = []
        DEPENDENCY_STACK.set(stack)

    conflict = next(filter(lambda previous: previous == dependency, stack), None)

    if conflict:
        trace = "\n".join(f"\t{n}: {ancestor}" for n, ancestor in enumerate(stack, start=1))
        lines = (
            f"the dependency \"{dependency.__name__}\" is recursive!",
            "dependency trace (most recent call last):",
            trace
        )

        raise RecursionError("\n".join(lines))

    stack.append(dependency)

    yield None

    try:
        stack.pop()
    # Most likely an exception was raised during the body of the context manager.
    except IndexError:
        pass


def _handler_wrapper(func: Callable[ParamsT, ReturnT]) -> Callable[ParamsT, ReturnT]:
    @functools.wraps(func)
    def _inner(*args: ParamsT.args, **kwargs: ParamsT.kwargs) -> ReturnT:
        _missing = object()

        dependency = _missing

        if args:
            dependency = args[0]
        elif "callback" in kwargs:
            dependency = kwargs["callback"]

        # The function has definitely been called incorrectly; we'll just let it fail per normal
        if dependency is _missing:
            return func(*args, **kwargs)

        with _track_recursion(dependency):
            return func(*args, **kwargs)

    return _inner


@_handler_wrapper
def get_handler(
    callback: Callable[..., Awaitable[Any]] | Type[BaseModel],
    path_params: set[str] = set(),
) -> util.Handler:
    # Necessary to avoid a circular import
    from .extract import Param, FromRequest, run_extractor

    unhandled_params = path_params.copy()
    arg_dependencies: list[util.Handler] = []
    kwarg_dependencies: dict[str, util.Handler] = {}

    parameters: Mapping[str, FnParameterLike]

    # When we're called with a class as a dependency, we'll need to fetch annotations from the class rather than the
    # signature.

    # TODO: In the future we could consider verifying that the class constructor's signature would be compatible with
    # the generated function (per its annotations) but I'm pretty tired so I'm going to deem it out of scope for now.
    try:
        annotations = typing.get_type_hints(callback, include_extras=True)
    except TypeError:
        annotations = None

    # We only use the class annotation behaviour for dependencies that we're sure are classes. Functions are legal
    # dependencies too (and `get_type_hints` will return a value for functions!) so we explicitly check that the
    # dependency derives `type` instead.
    if isinstance(callback, type) and annotations is not None:
        parameters = {
            name: FnParameter(
                name=name,
                default=Parameter.empty,
                annotation=annotation,
                kind=Parameter.KEYWORD_ONLY,
            )
            for name, annotation in annotations.items()
        }
    else:
        signature = inspect.signature(callback)
        parameters = signature.parameters  # type: ignore

    for name, parameter in parameters.items():
        description = f"the parameter {name} of the dependency {callback.__name__} (from {callback.__module__})"
        annotation = util.flatten_annotated(parameter.annotation)

        if name in path_params:
            annotation = Param(annotation, name)
            unhandled_params.discard(name)
        elif annotation is inspect.Parameter.empty:
            message = (
                f"{description} is missing a type annotation; only annotated parameters may be used with "
                "dependencies and extractors"
            )

            raise InvalidHandler(
                reason=InvalidHandlerReason.missing_annotation,
                message=message,
            )
        elif parameter.kind in VARIADIC_PARAM_TYPES:
            message = (
                f"{description} is variadic; variadic parameters (such as *args and **kwargs) cannot be used with "
                "dependencies and extractors"
            )

            raise InvalidHandler(
                reason=InvalidHandlerReason.variadic_parameter,
                message=message,
            )

        if isinstance(annotation, FromRequest):
            prerequisite = annotation.from_request
        else:
            prerequisite = functools.partial(run_extractor, annotation)

        if parameter.kind in POSITIONAL_PARAM_TYPES:
            arg_dependencies.append(prerequisite)
        else:
            kwarg_dependencies[name] = prerequisite

    if unhandled_params:
        missing = ", ".join(unhandled_params)
        count = len(unhandled_params)
        message = (
            f"the route for {callback.__name__} defines path parameters, but the definition of {callback.__name__} is "
            f"missing {count} of them ({missing}) - did you forget to add a parameter to {callback.__name__}?"
        )

        raise InvalidHandler(
            reason=InvalidHandlerReason.missing_parameters,
            message=message,
        )

    wrapped_callback = util.maybe_coro(callback)

    async def request_wrapper(request: Request) -> Any:
        args = [await dependency(request) for dependency in arg_dependencies]
        kwargs = {name: await dependency(request) for name, dependency in kwarg_dependencies.items()}

        return await wrapped_callback(*args, **kwargs)

    return request_wrapper
