from __future__ import annotations

import asyncio
import math
from asyncio import Queue, Task
from contextvars import ContextVar

from selenium.webdriver import Firefox


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
