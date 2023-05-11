from __future__ import annotations

import logging
import os
import re
from re import Match
from pathlib import Path

from pydantic import BaseModel, ValidationError

from .util import FernetSecret


LOGGER = logging.getLogger(__name__)
_PATTERN = re.compile(r"\${(?P<type>\w+)\:(?P<value>[^}]+)}", re.IGNORECASE)


class Config(BaseModel):
    bot: BotConfig
    database: DatabaseConfig
    level: LevelConfig
    web: WebConfig
    limits: LimitsConfig


class LimitsConfig(BaseModel):
    webdrivers: int


class BotConfig(BaseModel):
    token: str
    """The Discord token for Tabby's bot account.

    You can find this in Discord's developer portal."""

    client_id: str
    """Tabby's OAuth2 client ID.

    You can find this in Discord's developer portal.
    """

    client_secret: str
    """Tabby's OAuth2 client secret.

    You can find this in Discord's developer portal.
    """


class DatabaseConfig(BaseModel):
    host: str
    """The database host."""

    port: int
    """The database port."""

    user: str
    """The database user to log in as.

    While not a requirement, you should use a separate Postgres account for Tabby if you can. Regardless of the user you
    choose to log in as, they must have permission to execute the `CREATE SCHEMA` and `CREATE TABLE` commands when the
    application is run for the first time.

    Likewise, the user must have permission to execute `SELECT`/`INSERT`/`UPDATE`/`DELETE` commands on any table within
    the created `tabby` schema.
    """

    password: str
    """The database user's password."""


class LevelConfig(BaseModel):
    xp_awards_before_cooldown: int
    """The number of times a user should be able to receive XP before being put on cooldown.

    This value should usually be set to 1 to match the behaviour of Mee6.
    """

    xp_gain_cooldown: int
    """The number of seconds a user must wait until they can be awarded XP again.

    This value should usually be set to 60 to match the behaviour of Mee6.
    """


class WebConfig(BaseModel):
    host: str
    """The host used to run the web application.

    This should generally be set to `127.0.0.1` when running the application behind a reverse proxy. In some cases,
    you'll want to use `0.0.0.0` instead, so that the application is exposed over the network. This is most common when
    Docker or another form of containerization is involved.
    """

    port: int
    """The port used to run the web application."""

    secret_key: FernetSecret
    """The secret key used to encrypt/decrypt sensitive data throughout the web application.

    The secret key must be exactly 32 bytes in length, and must be encoded in base64. If you have `openssl` installed,
    you can generate a suitable key using the `openssl rand -base64 32` command.
    """

    redirect_uri: str
    """The redirect URI used when a user logs in with Discord.

    As a rule of thumb, this should just be the web application's public URL suffixed with "/oauth/callback"; if you
    were using `tabby.example.com` for the web application, you would set this to `tabby.example.com/oauth/callback`.
    """


class ConfigError(Exception):
    pass


class ConfigNotFoundError(ConfigError):
    def __str__(self) -> str:
        return "Configuration file not found"


class InvalidConfigError(ConfigError):
    original: ValidationError

    def __init__(self, original: ValidationError) -> None:
        self.original = original
        self.args = original,

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


# Dumb pydantic garbage
Config.update_forward_refs()
