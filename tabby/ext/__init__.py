import inspect
from types import ModuleType
from typing import Awaitable, Callable, Coroutine, Type

from discord.ext.commands import CogMeta

from . import autoroles, levels
from ..bot import Tabby, TabbyCog


def add_handlers(module: ModuleType) -> None:
    """Add a pair of (setup, teardown) handlers to `module`."""

    cogs = (value for value in vars(module).values() if inspect.isclass(value) and issubclass(value, TabbyCog))

    async def setup(bot: Tabby) -> None:
        for cog in cogs:
            await bot.add_cog(cog(bot))

    async def teardown(bot: Tabby) -> None:
        for cog in cogs:
            await bot.remove_cog(cog.__name__)

    module.setup = setup  # type: ignore
    module.teardown = teardown  # type: ignore


add_handlers(autoroles)
add_handlers(levels)
