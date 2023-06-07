from typing import Any, Awaitable, Callable, Mapping

from aiohttp import web
from aiohttp.web import StreamResponse
from jinja2 import Environment

from ..routing import Request, Response


TEMPLATE_ENVIRONMENT_KEY = "tabby_template_environment"


class Templates:
    _environment: Environment

    def __init__(
        self,
        environment: Environment,
        *,
        globals: Mapping[str, Any] = {},
    ) -> None:
        self._environment = environment

        if globals:
            self._environment.globals.update(globals)

        # Necessary to make class instances usable as middleware
        web.middleware(self)

    async def __call__(
        self,
        request: Request,
        handler: Callable[[Request], Awaitable[StreamResponse]],
    ) -> StreamResponse:
        request[TEMPLATE_ENVIRONMENT_KEY] = self

        return await handler(request)

    @classmethod
    async def from_request(cls, request: Request) -> "Templates":
        try:
            return request[TEMPLATE_ENVIRONMENT_KEY]
        except KeyError:
            raise RuntimeError("`Templates` not added as middleware") from None

    @property
    def environment(self) -> Environment:
        """The `Environment` stored by this `Templates` instance."""

        return self._environment
