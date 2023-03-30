from __future__ import annotations

import dataclasses
import logging
import os
import re
from pathlib import Path
from re import Match
from string import Template
from typing import TYPE_CHECKING, Any
import typing
from typing_extensions import Self

import toml


if TYPE_CHECKING:
    from _typeshed import StrPath


LOGGER = logging.getLogger(__name__)

_VALUE = r"(?P<value>[\-\./_a-zA-Z][\-\./_a-zA-Z0-9]*)"
_TYPE = r"(?P<type>[_a-zA-Z]+)"
_PATTERN = re.compile(fr"\${{{_TYPE}\:{_VALUE}}}")


class FromValuesMixin:
    @classmethod
    def from_values(cls, values: Any) -> Self:
        result = {}

        if not isinstance(values, dict):
            raise InvalidConfigError(
                None,
                reason=_expected_found(FromValuesMixin, type(values)),
            )

        for attr, expected_type in typing.get_type_hints(cls).items():
            field_value = values.get(attr)

            if issubclass(expected_type, FromValuesMixin):
                try:
                    result[attr] = expected_type.from_values(field_value)
                except InvalidConfigError as error:
                    raise error.nest(attr) from None
            elif isinstance(field_value, expected_type):
                result[attr] = field_value
            else:
                raise InvalidConfigError(
                    attr,
                    reason=_expected_found(expected_type, type(field_value)),
                )

        return cls(**result)


@dataclasses.dataclass
class Config(FromValuesMixin):
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

        return cls.from_values(values)


@dataclasses.dataclass
class LimitsConfig(FromValuesMixin):
    webdrivers: int


@dataclasses.dataclass
class BotConfig(FromValuesMixin):
    token: str


@dataclasses.dataclass
class DatabaseConfig(FromValuesMixin):
    host: str
    port: int
    user: str
    password: str

@dataclasses.dataclass
class LevelConfig(FromValuesMixin):
    xp_awards_before_cooldown: int
    xp_gain_cooldown: int


@dataclasses.dataclass
class LocalAPIConfig(FromValuesMixin):
    host: str
    port: int


class ConfigError(Exception):
    pass


class ConfigNotFoundError(FileNotFoundError, ConfigError):
    pass


class InvalidSubstitutionError(ConfigError):
    pass


class InvalidConfigError(ConfigError):
    field: str | None
    reason: str

    def __init__(self, field: str | None, *, reason: str) -> None:
        super().__init__(field, reason)

        self.field = field
        self.reason = reason

    def nest(self, attr: str) -> Self:
        previous_field = f"{self.field}." if self.field else ""
        field = f"{previous_field}{attr}"

        return InvalidConfigError(field, reason=self.reason)


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


def _typename(type: type) -> str:
    if issubclass(type, FromValuesMixin):
        return "a namespace"

    return type.__name__


def _expected_found(expected: type, found: type | None = None) -> str:
    base_message = f"expected {_typename(expected)}"

    if found is None or found is type(None):
        return base_message

    return f"{base_message}, but found {_typename(found)}"
