from __future__ import annotations

import dataclasses
import logging
import os
import re
import typing
from pathlib import Path
from re import Match
from string import Template
from typing import TYPE_CHECKING, Any

import toml
from typing_extensions import Self

from .extract import Extractable, ExtractionError


if TYPE_CHECKING:
    from _typeshed import StrPath


LOGGER = logging.getLogger(__name__)

_VALUE = r"(?P<value>[\-\./_a-zA-Z][\-\./_a-zA-Z0-9]*)"
_TYPE = r"(?P<type>[_a-zA-Z]+)"
_PATTERN = re.compile(fr"\${{{_TYPE}\:{_VALUE}}}")


@dataclasses.dataclass
class Config(Extractable):
    bot: BotConfig
    database: DatabaseConfig
    level: LevelConfig
    local_api: LocalAPIConfig
    limits: LimitsConfig

    @classmethod
    def load(cls, location: StrPath) -> Self:
        try:
            with open(location) as file:
                return cls.loads(file.read())
        except FileNotFoundError as error:
            raise ConfigNotFoundError(*error.args) from None

    @classmethod
    def loads(cls, content: str) -> Self:
        values = toml.loads(substitute(content))

        try:
            return cls.extract(values)
        except ExtractionError as error:
            raise InvalidConfigError(
                field=error.field,
                expected_type=error.expected_type,
                reason=error.reason,
            ) from None


@dataclasses.dataclass
class LimitsConfig(Extractable):
    webdrivers: int


@dataclasses.dataclass
class BotConfig(Extractable):
    token: str


@dataclasses.dataclass
class DatabaseConfig(Extractable):
    host: str
    port: int
    user: str
    password: str

@dataclasses.dataclass
class LevelConfig(Extractable):
    xp_awards_before_cooldown: int
    xp_gain_cooldown: int


@dataclasses.dataclass
class LocalAPIConfig(Extractable):
    host: str
    port: int


class ConfigError(Exception):
    pass


class ConfigNotFoundError(FileNotFoundError, ConfigError):
    pass


class InvalidSubstitutionError(ConfigError):
    pass


class InvalidConfigError(ConfigError, ExtractionError):
    pass


def substitute(template: str) -> str:
    return _PATTERN.sub(_substitute_one, template)


def _substitute_one(match: Match[str]) -> str:
    type: str = match["type"]
    value: str = match["value"]

    result = None

    if type == "env":
        message = "environment variable %s used in configuration isn't set"
        result = os.getenv(value)
    elif type == "file":
        message = "file %s used in configuration doesn't exist"

        try:
            result = Path(value).read_text()
        except FileNotFoundError:
            pass
    else:
        raise InvalidSubstitutionError(f"{type} is an invalid substitution type")

    if result is None:
        full_message = f"{message}; using default value of empty string"
        LOGGER.warning(full_message, value)

    return result.strip() if result else ""
