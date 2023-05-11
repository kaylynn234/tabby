from typing import Annotated

from .session import AuthorizedSession, Session
from .template import Templates
from .. import routing
from ..routing import Use, Response


@routing.get("/")
async def home(
    session: Annotated[Session | AuthorizedSession, Use(Session)],
    templates: Annotated[Templates, Use(Templates)],
) -> Response:
    return await templates.render(
        "home.html",
        context={"session": session},
    )
