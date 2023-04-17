import inspect
import re
from inspect import Parameter
from typing import Annotated, Any, Awaitable, Callable, ParamSpec, TypeVar

from aiohttp.web import Request, RouteDef

from . import util


ReturnT = TypeVar("ReturnT")
ParamsT = ParamSpec("ParamsT")

PATH_PARAMETER_PATTERN = re.compile(r"{(?P<name>.*?)(?:\:(?P<pattern>.*?))?}")
VARIADIC_PARAM_TYPES = (Parameter.VAR_POSITIONAL, Parameter.VAR_KEYWORD)
POSITIONAL_PARAM_TYPES = (Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD)


def get_handler(
    callback: Callable[..., Awaitable[Any]],
    path_params: set[str] = set(),
) -> util.Handler:
    # Necessary to avoid a circular import
    from .extract import Param, Use, FromRequest

    unhandled_params = path_params.copy()
    arg_dependencies: list[util.Handler] = []
    kwarg_dependencies: dict[str, util.Handler] = {}
    signature = inspect.signature(callback)

    for name, parameter in signature.parameters.items():
        description = f"the parameter {name} of the dependency {callback.__name__} (from {callback.__module__})"
        annotation = util.flatten_annotated(parameter.annotation)

        if name in path_params:
            annotation = Param(annotation, name)
            unhandled_params.discard(name)
        elif annotation is inspect.Parameter.empty:
            raise TypeError(
                f"{description} is missing a type annotation; only annotated parameters may be used with "
                "dependencies and extractors"
            )
        elif parameter.kind in VARIADIC_PARAM_TYPES:
            raise TypeError(
                f"{description} is variadic; variadic parameters (such as *args and **kwargs) cannot be used with "
                "dependencies and extractors"
            )

        prerequisite = annotation.from_request if isinstance(annotation, FromRequest) else Use(annotation)._handler

        if parameter.kind in POSITIONAL_PARAM_TYPES:
            arg_dependencies.append(prerequisite)
        else:
            kwarg_dependencies[name] = prerequisite

    if unhandled_params:
        missing = ", ".join(unhandled_params)
        count = len(unhandled_params)

        raise TypeError(
            f"the route for {callback.__name__} defines path parameters, but the definition of {callback.__name__} is "
            f"missing {count} of them ({missing}) - did you forget to add a parameter to {callback.__name__}?"
        )

    wrapped_callback = util.maybe_coro(callback)

    async def request_wrapper(request: Request) -> Any:
        args = [await dependency(request) for dependency in arg_dependencies]
        kwargs = {name: await dependency(request) for name, dependency in kwarg_dependencies.items()}

        return await wrapped_callback(*args, **kwargs)

    return request_wrapper


def build_route(method: str, path: str, func: Callable[..., Awaitable[Any]], **kwargs) -> RouteDef:
    """Wrap an asynchronous handler function into a standard aiohttp `RouteDef`.

    `method` sets which HTTP method to use for the route. "*" may be used as a wildcard.

    `path` sets the path that the route should be served from.
    Similarly to `aiohttp.web`, variable resources are supported within route paths.

    `func` is the callback function to be executed when the route is matched. Arguments for the function are extracted
    from the request based on the callback's type annotations. Anything that matches the `FromRequest` protocol (such as
    the `Use`, `Body` and `Query` extractors) may be used as a type annotation.

    Additionally, `Annotated` may be used to properly annotate the type of an extractor. This is the recommended
    approach when writing handler functions, as it provides correct type information to your editor/IDE while still
    allowing you to use dependency injection within handlers.
    """

    path_params = set()

    for part in path.split("/"):
        if not part:
            continue

        match = PATH_PARAMETER_PATTERN.fullmatch(part)
        if not match:
            continue

        path_params.add(match.group("name"))

    handler = get_handler(func, path_params=path_params)

    return RouteDef(
        method,
        path,
        handler,
        kwargs,
    )
