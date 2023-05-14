from typing import Any, Awaitable, Callable, Mapping

from aiohttp import web
from aiohttp.web import StreamResponse
from jinja2 import Environment

from ..routing import Request, Response


TEMPLATE_ENVIRONMENT_KEY = "tabby_template_environment"


class Templates:
    _environment: Environment

    def __init__(self, environment: Environment) -> None:
        self._environment = environment
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

    async def render(
        self,
        path: str,
        *,
        context: Mapping[str, Any] = {},
    ) -> str:
        """Render a template using the provided context and return the resulting text.

        `path` is the path of the template you wish to render. This will be looked up in the current environment using
        any configured loaders.

        `context` is the context mapping to use when rendering the template. If not provided, an empty dictionary is
        used as the default value.
        """

        template = self._environment.get_template(path)
        return await template.render_async(context)

    async def render_page(
        self,
        path: str,
        *,
        context: Mapping[str, Any] = {},
        **kwargs,
    ) -> Response:
        """Render a template using the provided context and return a `Response`.

        `path` is the path of the template you wish to render. This will be looked up in the current environment using
        any configured loaders.

        `context` is the context mapping to use when rendering the template. If not provided, an empty dictionary is
        used as the default value.

        If a `content_type` argument is not provided, it defaults to "text/html". With some exceptions, any remaining
        keyword arguments are passed as-is to the `Response` constructor.

        If a keyword argument named `text` is passed, this method raises `TypeError`. The `text` argument is used
        internally and its value cannot be overridden.
        """

        if "text" in kwargs:
            raise TypeError("the `text` parameter cannot be used when rendering a template")

        rendered = await self.render(path, context=context)
        content_type = kwargs.pop("content_type", "text/html")

        return Response(
            text=rendered,
            content_type=content_type,
            **kwargs,
        )
