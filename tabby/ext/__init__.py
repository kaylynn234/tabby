import inspect
import logging

from ..bot import Tabby, TabbyCog


LOGGER = logging.getLogger(__name__)
EXTENSIONS = [
    "tabby.ext.autoroles",
    "tabby.ext.levels",
    "tabby.ext.meta",
    "tabby.ext.silly",
]


def register_handlers() -> None:
    """Register a pair of (setup, teardown) handlers for the calling module."""

    caller = inspect.currentframe()
    assert caller is not None and caller.f_back is not None

    module_globals = caller.f_back.f_globals
    module_values = module_globals.copy().values()

    cogs = [
        value
        for value in module_values
        if inspect.isclass(value) and issubclass(value, TabbyCog) and value._should_register
    ]

    async def setup(bot: Tabby) -> None:
        for cog in cogs:
            await bot.add_cog(cog(bot))

    async def teardown(bot: Tabby) -> None:
        for cog in cogs:
            await bot.remove_cog(cog.__name__)

    module_globals.update(setup=setup, teardown=teardown)


async def load_extensions(bot: Tabby):
    for name in EXTENSIONS:
        LOGGER.info("loading extension %s", name)
        await bot.load_extension(name)
