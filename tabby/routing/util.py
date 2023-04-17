import functools
import inspect
import typing
from inspect import Parameter
from typing import Annotated, Any, Awaitable, Callable, ParamSpec, TypeGuard, TypeVar

from aiohttp.web import Request


Handler = Callable[[Request], Awaitable[Any]]


def flatten_annotated(dependency: Any) -> Any:
    origin = typing.get_origin(dependency)
    if origin is not Annotated:
        return dependency

    _, annotation, *extra_dependencies = typing.get_args(dependency)

    if extra_dependencies:
        raise TypeError(f"the annotation {dependency} is invalid; `Annotated` only supports a single dependency argument")

    return annotation


def is_bare_handler(func: Callable[..., Awaitable]) -> TypeGuard[Handler]:
    signature = inspect.signature(func)

    # This can't be a bare request handler; it has more than one parameter
    if len(signature.parameters) != 1:
        return False

    params = iter(signature.parameters.values())
    annotation = flatten_annotated(next(params).annotation)
    is_request = annotation is Parameter.empty or annotation is Request

    return is_request


def get_constructor(type: type) -> Callable:
    for base in reversed(type.__mro__):
        attrs = vars(base)
        effective_ctor = attrs.get("__new__") or attrs.get("__init__")

        if effective_ctor:
            return effective_ctor

    raise RuntimeError  # What the fuck?


ReturnT = TypeVar("ReturnT")
ParamsT = ParamSpec("ParamsT")


def maybe_coro(
    func: Callable[ParamsT, ReturnT] | Callable[ParamsT, Awaitable[ReturnT]]
) -> Callable[ParamsT, Awaitable[ReturnT]]:
    if inspect.iscoroutinefunction(func):
        return func

    @functools.wraps(func)
    async def wrapper(*args: ParamsT.args, **kwargs: ParamsT.kwargs) -> ReturnT:
        return func(*args, **kwargs)  # type: ignore

    return wrapper
