from __future__ import annotations
import asyncio

import math
from asyncio import Queue, Task
from contextvars import ContextVar

from asyncpg import Connection, Pool
from asyncpg.pool import PoolConnectionProxy
from selenium.webdriver import Firefox


_CONNECTION: ContextVar[PoolConnectionProxy] = ContextVar("connection")


class Acquire:
    """A helper for acquiring database connections.

    This type is intended for use within an asynchronous context manager. If a connection to the database has not
    already been acquired, this type will acquire one and make it available in the current context. If a connection
    already exists within the current context, it is reused.
    """

    _pool: Pool
    _connection: PoolConnectionProxy | None
    _needs_cleanup: bool

    def __init__(self, *, pool: Pool) -> None:
        self._pool = pool
        self._connection = None
        self._needs_cleanup = False

    async def __aenter__(self) -> Connection:
        connection = _CONNECTION.get(None)

        if connection is None:
            self._connection = connection = await self._pool.acquire()
            self._needs_cleanup = True

            _CONNECTION.set(connection)

        # Technically this is a lie - we return a `PoolConnectionProxy`, not a `Connection` - but `PoolConnectionProxy`
        # is usable as a `Connection`, by way of forwarding attribute lookups to a wrapped `Connection` object. Lying in
        # our type annotations like this gives us better completions at the call site, which is mostly what we care
        # about. But it is unfortunate that we need to do something like this in the first place.
        return connection  # type: ignore

    async def __aexit__(self, *_):
        assert self._connection is not None

        if self._needs_cleanup:
            await self._pool.release(self._connection)


class DriverPool:
    _drivers: list[Firefox]
    _available: Queue[Firefox]

    def __init__(self) -> None:
        self._drivers = []
        self._available = Queue()

    def __del__(self):
        for driver in self._drivers:
            driver.quit()

    async def setup(self, *, driver_count: int, **kwargs) -> None:
        def _build_driver():
            driver = Firefox(**kwargs)

            self._drivers.append(driver)
            self._available.put_nowait(driver)

        loop = asyncio.get_running_loop()
        futures = [loop.run_in_executor(None, _build_driver) for _ in range(driver_count)]

        await asyncio.wait(futures)

    def get(self) -> DriverGuard:
        """Retrieve a driver from the pool"""

        return DriverGuard(self)


class DriverGuard:
    _loaned: Firefox
    _pool: DriverPool

    def __init__(self, pool: DriverPool) -> None:
        self._pool = pool

    async def __aenter__(self) -> Firefox:
        driver = self._loaned = await self._pool._available.get()

        return driver

    async def __aexit__(self, *_):
        self._pool._available.put_nowait(self._loaned)


def humanize(value: int) -> str:
    scale = math.log10(abs(value))

    # This could be done in a ~cooler~ way, but I'm tired
    if scale > 6:
        return f"{value / 1_000_000:.2}M"
    elif scale > 3:
        return f"{value / 1_000:.2}K"
    else:
        return str(value)
