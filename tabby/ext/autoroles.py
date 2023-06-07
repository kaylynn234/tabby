from __future__ import annotations

import logging

from discord import Member, Object, Role
from discord.ext import commands
from discord.ext.commands import Context


from . import register_handlers
from ..bot import Tabby, TabbyCog
from ..level import LEVELS
from ..web import common


LOGGER = logging.getLogger(__name__)


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
    @commands.has_guild_permissions(manage_guild=True)
    @autoroles.command(aliases=["create", "new", "edit"])
    async def add(self, ctx: Context, level: int, role: Role):
        """Configure new autoroles or update existing ones

        You must have the "manage server" permission to use this command.

        level:
            The level that this autorole should be granted at. If this value is 0, the role will be granted when a member
            joins.

        role:
            The role to grant when a member reaches the specified level.

            This option can be specified either using a role ID, a role name (enclosed in quotes if the name is multiple
            words) or by using a role mention.

        If the specified role is already an autorole, the existing autorole definition is updated with the level
        specified by this command.
        """

        assert ctx.guild is not None

        updated = await common.create_or_update_guild_autorole(ctx.guild.id, role.id, level, self.bot)

        if updated:
            message = f"Updated autorole configuration for \"{role.name}\""
        else:
            message = f"Registered \"{role.name}\" as an autorole"

        await ctx.send(message)

    @commands.guild_only()
    @commands.has_guild_permissions(manage_guild=True)
    @autoroles.command()
    async def remove(self, ctx: Context, role: Role):
        """Remove configured autoroles

        You must have the "manage server" permission to use this command.

        role:
            The autorole to remove. You can specify a role by its ID, its name (enclosed in quotes if the name is
            multiple words) or by using a role mention.

        If the specified role is not configured as an autorole, it will be ignored.
        """

        assert ctx.guild is not None

        await common.remove_guild_autorole(ctx.guild.id, role.id, self.bot)

        await ctx.send(f"\"{role.name}\" is no longer configured as an autorole")

    @TabbyCog.listener()
    async def on_member_join(self, member: Member):
        query = """
            SELECT total_xp
            FROM tabby.levels
            WHERE guild_id = $1 AND user_id = $2
        """

        async with self.bot.db() as connection:
            total_xp: int = await connection.fetchval(query, member.guild.id, member.id) or 0

        info = LEVELS.get(total_xp)

        self.bot.dispatch("level", member, info.level)

    @TabbyCog.listener()
    async def on_level(self, member: Member, level: int):
        query = """
            WITH autorole_groups AS
               (SELECT
                    guild_id,
                    role_id,
                    granted_at,
                    dense_rank() OVER autoroles_in_guild AS group_number
                FROM tabby.autoroles
                WHERE guild_id = $1 AND granted_at <= $2
                WINDOW autoroles_in_guild AS
                   (PARTITION BY guild_id
                    ORDER BY granted_at DESC))
            SELECT
                role_id,
                stack_autoroles OR group_number = 1 AS should_keep
            FROM autorole_groups
            LEFT JOIN tabby.guild_options_for($1) USING (guild_id)
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
            reason = f"Member is level {level}" if should_keep else "Autorole stacking is disabled"

            LOGGER.debug(
                "%s member %s; %s",
                "Added role to" if should_keep else "Removed role from",
                member,
                reason,
            )

            await process_role(Object(role_id), reason=reason)


register_handlers()
