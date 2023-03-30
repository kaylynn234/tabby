import asyncio
import logging
import sys
from typing import NoReturn

from aiohttp.web import AppRunner, TCPSite
from discord import Enum

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
    logging.basicConfig()

    outcome = Outcome.error

    try:
        asyncio.run(run())
    except ConfigNotFoundError:
        LOGGER.error("couldn't find config.toml - does the file exist?")
    except InvalidConfigError as error:
        LOGGER.error("config field %s is invalid; %s", error.field, error.reason)
    except Exception as error:
        LOGGER.error("unhandled exception", exc_info=error)
    else:
        LOGGER.info("exiting gracefully")
        outcome = Outcome.ok

    outcome.exit()


async def run():
    config = Config.load("config.toml")

    async with Tabby(config=config) as bot:
        runner = AppRunner(LocalAPI(bot=bot))
        await runner.setup()

        site = TCPSite(runner, config.local_api.host, config.local_api.port)

        tasks = (
            bot.start(config.auth.bot_token),
            site.start(),
        )

        await asyncio.wait(map(asyncio.ensure_future, tasks))


if __name__ == "__main__":
    main()
