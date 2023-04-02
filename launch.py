import asyncio
import logging
import sys
from typing import NoReturn

from aiohttp.web import AppRunner, TCPSite
from discord import Enum

from tabby import ext
from tabby.bot import Tabby
from tabby.config import Config, InvalidConfigError, ConfigNotFoundError
from tabby.local_api import LocalAPI


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
    except ConfigNotFoundError:
        LOGGER.error("couldn't find config.toml - does the file exist?")
    except InvalidConfigError as error:
        LOGGER.error("config is invalid; %s", error)
    except Exception as error:
        LOGGER.error("unhandled exception", exc_info=error)
    else:
        LOGGER.info("exiting gracefully")
        outcome = Outcome.ok

    outcome.exit()


async def run():
    config = Config.load("config.toml")

    LOGGER.info("using config %s", config)

    async with Tabby(config=config) as bot:
        await bot.login(config.bot.token)
        await ext.load_extensions(bot)

        runner = AppRunner(LocalAPI(bot=bot))
        await runner.setup()

        site = TCPSite(runner, **vars(config.local_api))
        tasks = (bot.connect(), site.start())

        await asyncio.wait(map(asyncio.ensure_future, tasks))


if __name__ == "__main__":
    main()
