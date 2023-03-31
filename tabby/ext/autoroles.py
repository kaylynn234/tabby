from __future__ import annotations
from collections import Counter, defaultdict

import itertools
import operator
from typing import Any, Callable, Iterable, NamedTuple

from asyncpg import Record
from discord import AllowedMentions, Member, Object, Role
from discord.abc import Snowflake
from discord.ext import commands
from discord.ext.commands import Context
from discord.ext.commands import FlagConverter
from typing_extensions import Self

from . import register_handlers
from ..bot import Tabby, TabbyCog


class Autorole(FlagConverter):
    role: Role
    level: int


class UpdatedAutorole(NamedTuple):
    role: Role
    granted_at: int
    granted_at_previously: int | None


class Autoroles(TabbyCog):
    _cache: defaultdict[int, AutoroleMapping]

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)
        self._cache = defaultdict(AutoroleMapping)

    async def cog_load(self) -> None:
        await self._refresh_cache()

    @commands.group(invoke_without_command=True)
    async def autoroles(self, ctx: Context):
        """Show, update and remove autoroles"""

        await self.show(ctx)

    @autoroles.command(aliases=["list"])
    async def show(self, ctx: Context):
        """Show configured autoroles"""

        assert ctx.guild is not None

        if not self._cache.get(ctx.guild.id):
            await ctx.send("No autoroles configured.")
            return

        raw_by_level = sorted(
            self._cache[ctx.guild.id]._levels_to_roles.items(),
            key=lambda item: item[0],
            reverse=True,
        )

        def _format_role(role: Object) -> str:
            assert ctx.guild is not None

            actual_role = ctx.guild.get_role(role.id)

            return actual_role.mention if actual_role else f"unknown role #{role.id}"

        roles_by_level = ((level, f", ".join(map(_format_role, roles))) for level, roles in raw_by_level)
        message = "\n".join(f"level {level}: {roles}" for level, roles in roles_by_level)

        await ctx.send(message, allowed_mentions=AllowedMentions.none())


    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @autoroles.command(aliases=["create", "new", "edit"])
    async def add(self, ctx: Context, autoroles: list[Autorole]):
        """Configure new  autoroles or update existing ones."""

        assert ctx.guild is not None

        counts = Counter(autorole.role for autorole in autoroles)
        if any(count > 1 for count in counts.values()):
            await ctx.send("Can't specify the same role multiple times")
            return

        no_permissions = [
            autorole.role
            for autorole in autoroles
            if autorole.role.position > ctx.guild.me.top_role.position
        ]

        if no_permissions:
            mention_list = f", ".join(role.mention for role in no_permissions)
            message = (
                f"Some of roles you specified ({mention_list}) are higher in the role hierarchy than my top role, "
                "so Discord won't let me give them to anybody."
            )

            await ctx.send(message, allowed_mentions=AllowedMentions.none())

        query = """
            INSERT INTO tabby.autoroles(guild_id, role_id, granted_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, role_id)
            DO UPDATE SET granted_at = $3
            RETURNING role_id, autoroles.granted_at, excluded.granted_at AS granted_at_previously
        """

        update_info: list[UpdatedAutorole] = []

        async with self.db() as connection:
            for autorole in autoroles:
                arguments = ctx.guild.id, autorole.role.id, autorole.level
                record = await connection.fetchrow(query, arguments)

                assert record is not None

                role = ctx.guild.get_role(record["role_id"])

                assert role is not None

                updated = UpdatedAutorole(
                    role,
                    record["granted_at"],
                    record["granted_at_previously"],
                )

                update_info.append(updated)

        # Cache consistency is important!
        self._cache[ctx.guild.id].update(update_info)

        new_autoroles = sum(1 for updated in update_info if updated.granted_at_previously is None)
        new_message = f"Configured {new_autoroles} new autoroles"

        level_changes = "\n".join(
            f"- {updated.role.mention}: level {updated.granted_at_previously} -> level {updated.granted_at}"
            for updated in update_info
        )

        updated_autoroles = len(update_info) - new_autoroles

        if updated_autoroles:
            updated_message = "."
        else:
            updated_message = f", and updated {updated_autoroles} existing autoroles:\n{level_changes}"

        await ctx.send(f"{new_message}{updated_message}", allowed_mentions=AllowedMentions.none())

    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @autoroles.command()
    async def remove(self, ctx: Context, *roles: Role):
        """Remove configured autoroles."""

        assert ctx.guild is not None

        not_autoroles = []
        removed = 0

        query = """
            DELETE FROM tabby.autoroles
            WHERE guild_id = $1 AND role_id = $2
            RETURNING granted_at
        """

        async with self.db() as connection:
            for role in roles:
                granted_at = await connection.fetchval(query, ctx.guild.id, role.id)

                if granted_at is None:
                    not_autoroles.append(role)
                    continue

                self._cache[ctx.guild.id].remove(granted_at, Object(role.id))
                removed += 1

        removed_message = f"Removed {len(roles)} autoroles"

        if not_autoroles:
            mention_list = ", ".join(role.mention for role in not_autoroles)
            not_autorole_message = (
                f". Some of the roles you specified ({mention_list}) weren't autoroles, "
                "so they were ignored."
            )
        else:
            not_autorole_message = "."

        await ctx.send(f"{removed_message}{not_autorole_message}", allowed_mentions=AllowedMentions.none())

    async def _refresh_cache(self):
        query = """
            SELECT guild_id, role_id, granted_at
            FROM tabby.autoroles
            ORDER BY guild_id, granted_at
        """

        async with self.db() as connection:
            records = await connection.fetch(query)

        by_guild = itertools.groupby(records, operator.itemgetter("guild_id"))

        self._cache = defaultdict(
            AutoroleMapping,
            {guild: AutoroleMapping.from_records(group) for guild, group in by_guild}
        )

    @TabbyCog.listener()
    async def on_level(self, member: Member, level: int):
        config = self._cache.get(member.guild.id)

        # No autoroles configured for this guild, so nothing to do
        if config is None:
            return

        await config.sync_roles(member, level)


class AutoroleMapping:
    _levels_to_roles: defaultdict[int, set[Object]]

    def __init__(self, mapping: dict[int, set[Object]] = {}) -> None:
        self._levels_to_roles = defaultdict(set, mapping)

    def __bool__(self) -> bool:
        return any(self._levels_to_roles.values())

    @classmethod
    def from_records(cls, records: Iterable[Record]) -> Self:
        by_level = itertools.groupby(records, operator.itemgetter("granted_at"))
        mapping = {level: set(Object(record["role_id"]) for record in group) for level, group in by_level}

        return cls(mapping)

    def update(self, updates: Iterable[UpdatedAutorole]):
        for updated in updates:
            snowflake = Object(updated.role.id)

            if updated.granted_at_previously:
                self._levels_to_roles[updated.granted_at_previously].discard(snowflake)

            self._levels_to_roles[updated.granted_at].add(snowflake)

    def remove(self, level: int, roles: Object | Iterable[Object] = {}):
        to_remove = {roles} if isinstance(roles, Object) else roles
        self._levels_to_roles[level].difference_update(to_remove)

    async def sync_roles(self, member: Member, level: int):
        to_add = (roles for grant_at, roles in self._levels_to_roles.items() if grant_at <= level)

        await member.add_roles(
            *itertools.chain.from_iterable(to_add),
            reason=f"Member reached level {level}",
            atomic=False,
        )


register_handlers()
