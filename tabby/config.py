from __future__ import annotations

import dataclasses
from string import Template
from typing import TYPE_CHECKING, Type, TypeVar
from typing_extensions import Self

import toml


if TYPE_CHECKING:
    from _typeshed import StrPath


class ConfigNotFoundError(FileNotFoundError):
    pass


class ConfigError(Exception):
    field: str
    reason: str

    def __init__(self, field: str, *, reason: str) -> None:
        super().__init__(field, reason)

        self.field = field
        self.reason = reason


@dataclasses.dataclass
class Config:
    auth: AuthConfig
    level: LevelConfig
    local_api: LocalAPIConfig

    @classmethod
    def load(cls, location: StrPath) -> Self:
        try:
            with open(location) as file:
                return cls.loads(file.read())
        except FileNotFoundError as error:
            raise ConfigNotFoundError(*error.args) from None

    @classmethod
    def loads(cls, content: str) -> Self:
        namespace = toml.loads(content)

        return Config(
            AuthConfig.from_namespace(namespace, key="auth"),
            LevelConfig.from_namespace(namespace, key="level"),
            LocalAPIConfig.from_namespace(namespace, key="local_api"),
        )


class FromNamespaceMixin:
    @classmethod
    def from_namespace(cls, namespace: dict, *, key: str) -> Self:
        result = namespace.get(key)
        reason = None

        if result is None:
            reason = "expected a namespace"
        elif not isinstance(result, dict):
            reason = f"expected a namespace, but found {type(result).__name__}"

        if reason:
            raise ConfigError(key, reason=reason)

        assert isinstance(result, dict)

        for attr, expected_type in cls.__annotations__.items():
            field = f"{key}.{attr}"
            reason = None

            if attr not in result:
                reason = f"expected {expected_type.__name__}"
            elif not isinstance(result[attr], expected_type):
                reason = f"expected {expected_type.__name__}, but found {type(result[attr]).__name__}"

            if reason:
                raise ConfigError(field, reason=reason)

        return cls(**result)


@dataclasses.dataclass
class AuthConfig(FromNamespaceMixin):
    bot_token: str
    database_url: str


@dataclasses.dataclass
class LevelConfig(FromNamespaceMixin):
    xp_rate: int
    xp_per: int


@dataclasses.dataclass
class LocalAPIConfig(FromNamespaceMixin):
    host: str
    port: int
