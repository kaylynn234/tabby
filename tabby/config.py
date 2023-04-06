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
from pydantic import BaseModel, PydanticTypeError, PydanticValueError

import toml
from typing_extensions import Self



if TYPE_CHECKING:
    from _typeshed import StrPath


LOGGER = logging.getLogger(__name__)

_VALUE = r"(?P<value>[\-\./_a-zA-Z][\-\./_a-zA-Z0-9]*)"
_TYPE = r"(?P<type>[_a-zA-Z]+)"
_PATTERN = re.compile(fr"\${{{_TYPE}\:{_VALUE}}}")


class Config(BaseModel):
    bot: BotConfig
    database: DatabaseConfig
    level: LevelConfig
    local_api: LocalAPIConfig
    limits: LimitsConfig


class LimitsConfig(BaseModel):
    webdrivers: int


class BotConfig(BaseModel):
    token: str


class DatabaseConfig(BaseModel):
    host: str
    port: int
    user: str
    password: str

class LevelConfig(BaseModel):
    xp_awards_before_cooldown: int
    xp_gain_cooldown: int


class LocalAPIConfig(BaseModel):
    host: str
    port: int


class ConfigError(Exception):
    pass


class ConfigNotFoundError(ConfigError):
    def __str__(self) -> str:
        return "Configuration file not found"


class InvalidConfigError(ConfigError):
    original: PydanticValueError | PydanticTypeError

    def __init__(self, original: PydanticValueError | PydanticTypeError) -> None:
        super().__init__(original)

    def __str__(self) -> str:
        return f"Invalid configuration file: {self.original}"


class InvalidSubstitutionError(ConfigError):
    type: str

    def __init__(self, type: str) -> None:
        super().__init__(type)

        self.type = type

    def __str__(self) -> str:
        return f"Invalid substitution type '{self.type}'"


def substitute(raw: str) -> str:
    return _PATTERN.sub(_substitute_one, raw)


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
        raise InvalidSubstitutionError(type)

    if result is None:
        full_message = f"{message}; using default value of empty string"
        LOGGER.warning(full_message, value)

    return result.strip() if result else ""
