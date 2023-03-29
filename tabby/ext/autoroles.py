from __future__ import annotations

import itertools
import operator
from typing import Any, Callable, Iterable

from asyncpg import Record
from discord import Member, Object
from discord.abc import Snowflake
from typing_extensions import Self

from ..bot import Tabby, TabbyCog


class Autoroles(TabbyCog):
    _cache: dict[int, AutoroleMapping]

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)

    async def refresh_cache(self):
        query = """
            SELECT guild_id, role_id, granted_at
            FROM tabby.autoroles
            ORDER BY guild_id, granted_at
        """

        async with self.db() as connection:
            records = await connection.fetch(query)

        by_guild = itertools.groupby(records, operator.itemgetter("guild_id"))
        self._cache = {guild: AutoroleMapping.from_records(group) for guild, group in by_guild}

    @TabbyCog.listener()
    async def on_level(self, member: Member, level: int):
        config = self._cache.get(member.guild.id)

        # No autoroles configured for this guild, so nothing to do
        if config is None:
            return

        await config.sync_roles(member, level)


class AutoroleMapping:
    _levels_to_roles: dict[int, set[Object]]

    def __init__(self, mapping: dict[int, set[Object]]) -> None:
        self._levels_to_roles = mapping

    @classmethod
    def from_records(cls, records: Iterable[Record]) -> Self:
        by_level = itertools.groupby(records, operator.itemgetter("granted_at"))
        mapping = {level: set(Object(record["role_id"]) for record in group) for level, group in by_level}

        return cls(mapping)

    async def sync_roles(self, member: Member, level: int):
        to_add = (roles for grant_at, roles in self._levels_to_roles.items() if grant_at <= level)

        await member.add_roles(
            *itertools.chain.from_iterable(to_add),
            reason=f"Member reached level {level}",
            atomic=False,
        )
