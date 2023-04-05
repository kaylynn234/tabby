from __future__ import annotations

import dataclasses
import itertools
import operator
import re
from collections import Counter, defaultdict
from typing import Any, AsyncGenerator, Callable, Iterable, Mapping, NamedTuple

import discord.utils
from asyncpg import Record
from discord import AllowedMentions, Member, Object, Role
from discord.abc import Snowflake
from discord.ext import commands
from discord.ext.commands import Context
from discord.ext.commands import FlagConverter
from typing_extensions import Self

from . import register_handlers
from ..bot import Tabby, TabbyCog


LEVEL_FLAG = re.compile(r"(\d+)\s*:")


@dataclasses.dataclass
class AutoroleOption:
    level: int
    role: Role

    @classmethod
    async def convert(cls, ctx: Context, argument: str) -> Self:
        if match := LEVEL_FLAG.match(argument):
            level = int(match.group(1))
        else:
            raise ValueError(
                f"\"{discord.utils.escape_markdown(argument)}\" is invalid autorole syntax. When adding new autoroles "
                "- or editing existing ones - you specify them using a level and a role, separated by a colon.\n"
                "E.g, to register a role named \"Cool Role\" as an autorole that should be granted at level 20, "
                "you could use '20: \"Cool Role\"' as an argument to this command.\n"
                "You can also use a role ID or mention, instead of a role name. Note that role names need to be quoted "
                "if they're longer than one word."
            )

        ctx.view.skip_ws()
        raw_role = ctx.current_argument = ctx.view.get_quoted_word()

        if raw_role is None:
            raise ValueError(f"\"{argument}\" should be followed by a role name, ID or mention!")

        assert ctx.current_parameter is not None

        role = await commands.run_converters(ctx, Role, raw_role, ctx.current_parameter)

        return cls(level, role)


class Autoroles(TabbyCog):
    @commands.group(invoke_without_command=True)
    async def autoroles(self, ctx: Context):
        """Show, update and remove autoroles

        If no subcommand is used, this command acts like "autoroles show" was used.
        """

        await self.show(ctx)

    @autoroles.command(aliases=["list"])
    async def show(self, ctx: Context):
        """Show configured autoroles

        Displays a list of autoroles configured in this server, grouped by level.
        """

        assert ctx.guild is not None

        query = """
            SELECT granted_at, array_agg(role_id) AS roles
            FROM tabby.autoroles
            WHERE guild_id = $1
            GROUP BY granted_at
            ORDER BY granted_at DESC
        """

        async with self.db() as connection:
            records = await connection.fetch(query, ctx.guild.id)

        if not records:
            await ctx.send("No autoroles configured.")
            return

        def _format_role(role_id: int) -> str:
            assert ctx.guild is not None

            actual_role = ctx.guild.get_role(role_id)

            return actual_role.mention if actual_role else f"unknown role #{role_id}"

        by_level = ((level, f", ".join(map(_format_role, roles))) for level, roles in records)
        message = "\n".join(f"level {level}: {roles}" for level, roles in by_level)

        await ctx.send(message)


    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @autoroles.command(aliases=["create", "new", "edit"])
    async def add(self, ctx: Context, *autoroles: AutoroleOption):
        """Configure new autoroles or update existing ones

        You must have the "manage roles" permission to use this command.

        autoroles:
            A list of autoroles to configure. Each autorole is specified with a pair of "level" and "role" options. The
            "level" option determines the level to grant the role at, and the "role" option determines which role to
            grant.

            The value for the "role" option can be specified either using a role ID, a role name (enclosed in quotes if
            the name is multiple words) or by using a role mention.

            Each "level" and "role" pair needs to be separated with a colon, like '20: "Cool Role"'.

            If any of the provided roles are already configured as autoroles, their autorole configuration will be
            updated instead.
        """

        assert ctx.guild is not None

        counts = Counter(autorole.role for autorole in autoroles)
        if any(count > 1 for count in counts.values()):
            await ctx.send("Can't specify the same role multiple times")
            return

        no_permissions = [
            autorole.role
            for autorole in autoroles
            if autorole.role.position >= ctx.guild.me.top_role.position
        ]

        if no_permissions:
            mention_list = f", ".join(role.mention for role in no_permissions)
            message = (
                f"Some of the roles you specified ({mention_list}) are higher in the role hierarchy than my top role, "
                "so Discord won't let me give them to anybody."
            )

            await ctx.send(message)
            return

        query = """
            INSERT INTO tabby.autoroles(guild_id, role_id, granted_at)
            VALUES ($1, $2, $3)
            ON CONFLICT (guild_id, role_id)
            DO UPDATE SET granted_at = $3
        """

        async with self.db() as connection:
            to_update = ((ctx.guild.id, autorole.role.id, autorole.level) for autorole in autoroles)
            await connection.executemany(query, to_update)

        await ctx.send(f"Updated configuration for {len(autoroles)} autorole(s)")

    @commands.guild_only()
    @commands.has_guild_permissions(manage_roles=True)
    @autoroles.command()
    async def remove(self, ctx: Context, *roles: Role):
        """Remove configured autoroles

        You must have the "manage roles" permission to use this command.

        roles:
            A list of roles to remove. Each role can be specified by its ID, its name (enclosed in quotes if the name is
            multiple words) or by using a role mention. Any roles that are not configured as autoroles are ignored.
        """

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

                removed += 1

        message = f"Removed {removed} autorole(s)"

        if not_autoroles:
            mention_list = ", ".join(role.mention for role in not_autoroles)
            message = (
                f"{message}. Some of the roles you specified ({mention_list}) weren't autoroles, "
                "so they were ignored."
            )

        await ctx.send(message)

    @commands.guild_only()
    @autoroles.group(invoke_without_command=True)
    async def stack(self, ctx: Context, stack_autoroles: bool | None):
        """Configure "stacking" for autoroles

        You must have the "manage guild" permission to modify configuration using this command.
        If no arguments are provided, this command displays whether autorole stacking is currently enabled instead.

        If stacking is enabled, all previous autoroles are kept when a member levels up. If stacking is disabled,
        members only keep the role(s) for their highest level.

        stack_autoroles:
            Whether stacking should be enabled or not. You can specify this option using a value like "yes", "no",
            "true", "false", "0" or "1".
        """

        if stack_autoroles is None:
            await self.stack_show(ctx)
            return

        assert ctx.guild is not None

        await commands.has_guild_permissions(manage_guild=True).predicate(ctx)

        query = """
            INSERT INTO tabby.guild_options(guild_id, stack_autoroles)
            VALUES ($1, $2)
            ON CONFLICT (guild_id)
            DO UPDATE SET stack_autoroles = $2;
        """

        async with self.db() as connection:
            await connection.execute(query, ctx.guild.id, stack_autoroles)

        await ctx.send(f"{'Enabled' if stack_autoroles else 'Disabled'} autorole stacking in this guild")

    @commands.guild_only()
    @stack.command(name="show")
    async def stack_show(self, ctx: Context):
        """Display whether autorole stacking is currently enabled

        If stacking is enabled, all previous autoroles are kept
        when a member levels up. If stacking is disabled, members only keep the role(s) for their highest level.
        """

        assert ctx.guild is not None

        query = """
            SELECT stack_autoroles
            FROM tabby.guild_options
            WHERE guild_id = $1
        """

        async with self.db() as connection:
            enabled = await connection.fetchval(query, ctx.guild.id)

        await ctx.send(f"Autorole stacking is currently {'enabled' if enabled else 'disabled'} in this guild")

    @TabbyCog.listener()
    async def on_level(self, member: Member, level: int):
        query = """
            SELECT
                role_id,
                granted_at = $2 OR stack_autoroles AS should_keep
            FROM tabby.autoroles
            LEFT JOIN tabby.guild_options USING (guild_id)
            WHERE guild_id = $1 AND granted_at <= $2
        """

        async with self.db() as connection:
            records: list[tuple[int, bool]] = await connection.fetch(query, member.guild.id, level)

        # No autoroles matched by the user's level, so nothing to do.
        if not records:
            return

        for record in records:
            role_id, should_keep = record

            # When `should_keep` is `True`, this role might need to be added.
            # When `should_keep` is `False`, this role might need to be removed.
            #
            # Instead of doing extra work, we can compare the intended outcome to whether the member already has the
            # role. If the outcomes line up, we have nothing more to do this iteration.
            #
            # Hooray for the fast path!
            if should_keep is bool(member.get_role(role_id)):
                continue

            process_role = member.add_roles if should_keep else member.remove_roles
            reason = f"Member reached level {level}" if should_keep else "Autorole stacking is disabled"

            await process_role(Object(role_id), reason=reason)


register_handlers()
