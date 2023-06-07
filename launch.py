import asyncio
import logging
import sys
from pathlib import Path
from typing import NoReturn

import toml
from aiohttp.web import AppRunner, TCPSite
from discord import Enum
from pydantic import ValidationError

import tabby
from tabby.bot import Tabby
from tabby.config import Config, ConfigError, ConfigNotFoundError, InvalidConfigError


LOGGER = logging.getLogger("launch")


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

        tasks = (run_bot(bot), run_web(bot))

        done, pending = await asyncio.wait(
            map(asyncio.ensure_future, tasks),
            return_when=asyncio.FIRST_EXCEPTION,
        )

        for task in pending:
            task.cancel()

        error = tabby.util.task_exception(done)

        if error:
            raise error


async def run_bot(bot: Tabby):
    await tabby.ext.load_extensions(bot)

    LOGGER.info("all bot setup is done; connecting to gateway")

    await bot.connect()


async def run_web(bot: Tabby):
    runner = AppRunner(tabby.web.setup_application(bot))
    await runner.setup()

    config = bot.config.web.dict(include={"host", "port"})
    site = TCPSite(runner, **config)

    LOGGER.info("all web application setup is done; opening socket")

    await site.start()


if __name__ == "__main__":
    main()
