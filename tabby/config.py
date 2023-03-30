from __future__ import annotations

import dataclasses
import logging
import os
from string import Template
from typing import TYPE_CHECKING, Any
from typing_extensions import Self

import toml


if TYPE_CHECKING:
    from _typeshed import StrPath


LOGGER = logging.getLogger(__name__)


class FromValuesMixin:
    @classmethod
    def from_values(cls, values: Any) -> Self:
        result = {}

        if not isinstance(values, dict):
            raise ConfigError(
                None,
                reason=_expected_found(FromValuesMixin, type(values)),
            )

        for attr, expected_type in cls.__annotations__.items():
            field_value = values.get(attr)

            if issubclass(expected_type, FromValuesMixin):
                try:
                    result[attr] = expected_type.from_values(field_value)
                except ConfigError as error:
                    raise error.nest(attr) from None
            elif isinstance(field_value, expected_type):
                result[attr] = field_value
            else:
                raise ConfigError(
                    attr,
                    reason=_expected_found(expected_type, type(field_value)),
                )

        return cls(**result)


class EnvDict(dict):
    def __missing__(self, key: str):
        value = os.getenv(key)

        if value is None:
            LOGGER.warning(
                "environment variable %s used in configuration but not set; using default value of an empty string",
                key,
            )

        return value or ""


@dataclasses.dataclass
class Config(FromValuesMixin):
    auth: AuthConfig
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
        values = toml.loads(Template(content).substitute(EnvDict()))

        return cls.from_values(values)


@dataclasses.dataclass
class LimitsConfig(FromValuesMixin):
    webdrivers: int


@dataclasses.dataclass
class AuthConfig(FromValuesMixin):
    bot_token: str
    database_url: str


@dataclasses.dataclass
class LevelConfig(FromValuesMixin):
    xp_rate: int
    xp_per: int


@dataclasses.dataclass
class LocalAPIConfig(FromValuesMixin):
    host: str
    port: int


class ConfigError(Exception):
    field: str | None
    reason: str

    def __init__(self, field: str | None, *, reason: str) -> None:
        super().__init__(field, reason)

        self.field = field
        self.reason = reason

    def nest(self, attr: str) -> Self:
        previous_field = f"{self.field}." if self.field else ""
        field = f"{previous_field}{attr}"

        return ConfigError(field, reason=self.reason)


class ConfigNotFoundError(FileNotFoundError):
    pass


def _typename(type: type) -> str:
    if issubclass(type, FromValuesMixin):
        return "a namespace"

    return type.__name__


def _expected_found(expected: type, found: type | None = None) -> str:
    base_message = f"expected {_typename(expected)}"

    if found is None or found is type(None):
        return base_message

    return f"{base_message}, but found {_typename(found)}"
