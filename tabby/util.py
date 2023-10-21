from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
from asyncio import Queue, Task
from typing import Any, Awaitable, Callable, Coroutine, Generic, Hashable, Iterable, Mapping, MutableMapping, Type, TypeVar
from asyncpg import Record

import pydantic
from cryptography.fernet import Fernet
from discord import Asset, DefaultAvatar, Enum, User
from discord.state import ConnectionState
from discord.ext.commands import Context
from pydantic import BaseModel
from selenium.webdriver import Firefox
from typing_extensions import Self
from yarl import URL


API_URL = URL("https://discord.com/api/v10")
LOGGER = logging.getLogger(__name__)

HUMANIZE_UNITS = {
    1: "K",
    2: "M",
    3: "B",
    4: "T",
    5: "Q",
    # If somebody has more XP than this, we quite honestly have more pressing concerns
}


class Snowflake(BaseModel):
    """A special helper type for using snowflakes within Pydantic models.

    A `Snowflake` can be deserialized from either a string or an integer, but is always serialized as a string. This is
    specifically ideal when serializing API responses, since integers that are beyond the 53-bit range cannot be
    accurately interpreted by some JSON decoders.
    """

    __root__: int

    # `Snowflake`s are serialized as strings
    class Config:
        json_encoders = {int: str}

    def __init__(self, __root__: str | int) -> None:
        super().__init__(__root__=int(__root__))

    def __str__(self) -> str:
        return str(self.id)

    def __int__(self) -> int:
        return self.id

    def __hash__(self) -> int:
        return hash(int(self))

    @property
    def id(self) -> int:
        """The unique ID represented by this snowflake."""

        return self.__root__


ModelT = TypeVar("ModelT", bound=BaseModel)
class FernetSecret(Fernet):
    """A `Fernet` subclass with support for Pydantic models."""

    def serialize(self, model: BaseModel) -> bytes:
        return self.encrypt(model.json().encode())

    def deserialize(self, model: Type[ModelT], encrypted: bytes) -> ModelT:
        payload = json.loads(self.decrypt(encrypted).decode())

        return pydantic.parse_obj_as(model, payload)

    @classmethod
    def validate(cls, value: Any) -> "FernetSecret":
        key = pydantic.parse_obj_as(bytes, value)

        return cls(key)

    @classmethod
    def __get_validators__(cls):
        yield cls.validate


KeyT = TypeVar("KeyT", bound=Hashable)
ValueT = TypeVar("ValueT")
class TTLCache(MutableMapping[KeyT, ValueT]):
    _on_expiry: Callable[[], Awaitable] | None
    _expiry: int
    _values: dict[KeyT, _TTL[ValueT]]

    def __init__(self, *, expiry: int, on_expiry: Callable[[], Awaitable] | None = None) -> None:
        self._on_expiry = on_expiry
        self._expiry = expiry
        self._values = {}

    def _task_for_key(self, key: KeyT) -> Task:
        async def remover(expiry: int, values: dict[KeyT, _TTL[ValueT]]):
            await asyncio.sleep(expiry)

            try:
                del values[key]
            except KeyError:
                return

            if self._on_expiry:
                await self._on_expiry()

        return asyncio.create_task(remover(self._expiry, self._values))

    def __getitem__(self, key: KeyT) -> ValueT:
        return self._values[key].value

    def __setitem__(self, key: KeyT, value: ValueT):
        expiry = self._task_for_key(key)

        if key in self._values:
            self._values[key].replace_task(expiry)
        else:
            self._values[key] = _TTL(value, expiry)

    def __delitem__(self, key: KeyT) -> None:
        if key in self._values:
            self._values[key].task.cancel()

        del self._values[key]

    def __iter__(self) -> Iterable[KeyT]:
        return self._values.keys()

    def __len__(self) -> int:
        return len(self._values)


@dataclasses.dataclass(slots=True)
class _TTL(Generic[ValueT]):
    value: ValueT
    task: Task

    def replace_task(self, task: Task):
        self.task.cancel()
        self.task = task


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
            raise ValueError("a codeblock cannot be `inline` and specify a language")

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
                if first_line.end is None:
                    first_line.end = cursor
                if rest.start is None:
                    rest.start = cursor

                rest.end = cursor
                cursor += backticks
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


def task_exception(tasks: Iterable[Task]) -> BaseException | None:
    """Return the first exception in the `tasks` iterable, or `None` if no tasks raised an exception.

    Per `Task.exception`, this function will raise `CancelledError` if any of the tasks in `tasks` were cancelled, or
    `InvalidStateError` if any of the tasks in `tasks` have not yet completed.
    """

    errors = filter(None, map(Task.exception, tasks))
    error = next(errors, None)

    return error


def humanize(value: int) -> str:
    n_zeroes = math.log10(abs(value)) if value else 0
    scale = int(n_zeroes // 3)

    if not scale:
        return str(value)

    try:
        suffix = HUMANIZE_UNITS[scale]
    except KeyError:
        raise ValueError(f"unsupported scale for `humanize`: {scale} (number with {n_zeroes + 1} digits)") from None

    divisor: int = 10 ** (3 * scale)

    return f"{value / divisor:.1f}{suffix}"
