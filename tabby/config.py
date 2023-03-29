from __future__ import annotations

from string import Template
from typing import TYPE_CHECKING
from typing_extensions import Self

import toml


if TYPE_CHECKING:
    from _typeshed import StrPath


class Config:
    bot_token: str
    database_url: str
    xp_rate: int
    xp_per: int

    def __init__(
        self,
        database_url: str,
        bot_token: str,
        xp_rate: int = 1,
        xp_per: int = 60,
    ) -> None:
        self.database_url = database_url
        self.bot_token = bot_token

    @classmethod
    def load(cls, location: StrPath) -> Self:
        with open(location) as file:
            return cls.loads(file.read())

    @classmethod
    def loads(cls, content: str) -> Self:
        return Config(**toml.loads(content))
