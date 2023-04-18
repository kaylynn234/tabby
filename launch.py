import asyncio
import logging
import sys
from pathlib import Path
from typing import NoReturn

import toml
from aiohttp.web import AppRunner, TCPSite
from discord import Enum
from pydantic import PydanticTypeError, PydanticValueError, ValidationError

import tabby
from tabby.bot import Tabby
from tabby.config import Config, ConfigError, ConfigNotFoundError, InvalidConfigError


LOGGER = logging.getLogger(__name__)


class Outcome(Enum):
    ok = 0
    error = 1

    def exit(self) -> NoReturn:
        sys.exit(self.value)


def main() -> NoReturn:
    logging.basicConfig(level=logging.INFO)

    outcome = Outcome.error

    try:
        asyncio.run(run())
    except ConfigError as error:
        LOGGER.error("error loading config", exc_info=error)
    except Exception as error:
        LOGGER.error("unhandled exception", exc_info=error)
    else:
        LOGGER.info("exiting gracefully")
        outcome = Outcome.ok

    outcome.exit()


async def run():
    try:
        raw = Path("config.toml").read_text()
        substituted = tabby.config.substitute(raw)
        config = Config.parse_obj(toml.loads(substituted))
    except FileNotFoundError:
        raise ConfigNotFoundError from None
    except ValidationError as error:
        raise InvalidConfigError(error) from None

    LOGGER.info("using config %s", config)

    async with Tabby(config=config) as bot:
        await bot.login(config.bot.token)
        await tabby.ext.load_extensions(bot)

        runner = AppRunner(tabby.api.setup_application(bot))
        await runner.setup()

        site = TCPSite(runner, **vars(config.api))
        tasks = (bot.connect(), site.start())

        await asyncio.wait(map(asyncio.ensure_future, tasks))


if __name__ == "__main__":
    main()
