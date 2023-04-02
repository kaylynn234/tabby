import copy
import logging

import asyncpg
import slugify
from discord.ext import commands
from discord.ext.commands import Context
from prettytable import PrettyTable

from . import register_handlers
from ..bot import Tabby, TabbyCog
from ..util import Codeblock


LOGGER = logging.getLogger(__name__)


class Meta(TabbyCog):
    @commands.is_owner()
    @commands.command()
    async def sql(self, ctx: Context, *, query: Codeblock):
        """Execute a SQL command and display the results"""

        async with self.db() as connection:
            records = await connection.fetch(query.content)

        if not records:
            await ctx.send("(no results)")
            return

        field_names = (name for name, value in records[0].items())
        table = PrettyTable(field_names)
        table.add_rows(tuple(record) for record in records)

        await ctx.send(Codeblock(table.get_string()).markup())

    @commands.is_owner()
    @commands.command()
    async def sudo(self, ctx: Context, *, to_run: str):
        """Execute a command without running any of its checks."""

        assert ctx.prefix is not None

        # We need to lie to the type checker here. The method actually accepts partial updates, but the dictionary type
        # it takes as input isn't marked as partial.
        fake_message = copy.copy(ctx.message)
        fake_message._update({"content": f"{ctx.prefix}{to_run}"})  # type: ignore

        fake_ctx = await self.bot.get_context(fake_message)
        command = fake_ctx.command

        # We imitate the usual command invoke flow, down to the error message. The `sudo` command will complete without
        # issue - and dispatch any associated completion events - but the "sub-command" we just tried to execute won't.
        # It's delegated to the usual event handlers, and should spit out a normal error message. Hopefully.
        if not command:
            error = commands.CommandNotFound(f'Command "{fake_ctx.invoked_with}" is not found')
            self.bot.dispatch("command_error", fake_ctx, error)

            return

        # Time for evil undoc'd API abuse! We ignore all of the rules given to us and execute the command without
        # actually checking if it can run. Things will possibly fail horribly. But that's why we're here, is it not?
        try:
            await command.prepare(fake_ctx)
        except commands.CheckFailure:
            pass

        await command.reinvoke(fake_ctx)

    @sudo.error
    async def sudo_error(self, ctx: Context, error: commands.CommandError):
        if not isinstance(error, commands.NotOwner):
            await self.bot.on_command_error(ctx, error, force=True)

            return

        invocation = ctx.message.clean_content.removeprefix(ctx.clean_prefix)
        username = slugify.slugify(ctx.author.name)

        terminal_message = "\n".join((
            f"{username}@tabby:~$ {invocation}",
            f"[sudo] password for {username}:",
            f"{username} is not in the sudoers file.  This incident will be reported.",
        ))

        await ctx.send(Codeblock(terminal_message, language="console").markup())


register_handlers()
