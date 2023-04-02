from __future__ import annotations

import asyncio
import dataclasses
import math
from asyncio import Queue, Task
from contextvars import ContextVar

from discord import Enum
from discord.ext.commands import Context
from selenium.webdriver import Firefox
from typing_extensions import Self


class Codeblock:
    """A codeblock on Discord"""

    content: str
    """The content of the codeblock"""

    language: str | None
    """The language specified for this codeblock

    Inline codeblocks cannot specify a language, so when `inline` is `True`, this attribute will always be `None`.
    """

    inline: bool
    """Whether this is an inline codeblock

    Inline codeblocks do not break up message content; they're displayed "in-line" with text. However, inline codeblocks
    do not support the specification of a language for syntax highlighting.
    """

    def __init__(
        self,
        content: str,
        *,
        language: str | None = None,
        inline: bool = False,
    ) -> None:
        if inline and language:
            raise ValueError("a codeblock cannot be both `inline` and specify a language")

        self.content = content
        self.language = language
        self.inline = inline

    def __str__(self) -> str:
        if self.inline:
            return f"`{self.content}`"

        return f"```{self.language or ''}\n{self.content}\n```"

    def markup(self) -> str:
        """Return the markup representation of this codeblock"""

        return str(self)

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        cursor = 0
        state: _State = _State.initial_whitespace

        backticks = 0
        closing_backticks = ""
        first_line = _Slice(None, None)
        rest = _Slice(None, None)

        def would_close() -> bool:
            return argument[cursor:cursor + backticks] == closing_backticks

        while cursor < len(argument):
            current = argument[cursor]

            could_close =  current == "`" and (state is _State.first_line or state is _State.content)

            if state is _State.initial_whitespace:
                if current == "`":
                    state = _State.opening_backticks
                    backticks = 1
                elif not current.isspace():
                    raise ValueError("codeblocks must begin with backticks")

            elif state is _State.opening_backticks:
                if current == "`":
                    backticks += 1
                else:
                    state = _State.first_line
                    first_line.start = cursor
                    closing_backticks = "`" * backticks

            elif could_close and would_close():
                if rest.start is None:
                    rest.start = cursor

                rest.end = cursor
                cursor += backticks - 1
                break

            elif state is _State.first_line:
                if current == "\n" and backticks > 2:
                    first_line.end = cursor
                    rest.start = cursor
                    state = _State.content
                elif current == "\n":
                    raise ValueError("inline codeblocks cannot contain line breaks")

            cursor += 1

        if argument[cursor:]:
            raise ValueError("codeblocks cannot contain trailing content")

        maybe_language = argument[first_line.start:first_line.end]
        if backticks < 3:
            return Codeblock(
                maybe_language,
                language=None,
                inline=True,
            )

        content = argument[rest.start:rest.end]

        # If there *is* further content in the codeblock, and the first line is *not* broken by whitespace, it must be a
        # language identifier.
        if content and all(not char.isspace() for char in maybe_language):
            return Codeblock(
                content[1:],  # We don't want to keep the leading newline
                language=maybe_language,
                inline=False,
            )

        return Codeblock(
            maybe_language + content,
            language=None,
            inline=False,
        )


@dataclasses.dataclass
class _Slice:
    start: int | None
    end: int | None


class _State(Enum):
    initial_whitespace = 0
    opening_backticks = 1
    first_line = 2
    content = 3


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
    scale = math.log10(abs(value)) if value else 0

    # This could be done in a ~cooler~ way, but I'm tired
    if scale > 6:
        return f"{value / 1_000_000:.2f}M"
    elif scale > 3:
        return f"{value / 1_000:.2f}K"
    else:
        return str(value)
