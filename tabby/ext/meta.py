import ast
import asyncio
import copy
import itertools
import logging
import textwrap
from asyncio import Task
from typing import Any, AsyncGenerator, Callable, Coroutine, Sequence

import asyncpg
import slugify
from discord import Member, Reaction, User
from discord.ext import commands
from discord.ext.commands import Context
from prettytable import PrettyTable

from . import register_handlers
from ..bot import Tabby, TabbyCog
from ..util import Codeblock


LOGGER = logging.getLogger(__name__)
_YIELD_MARKER = object()


class Meta(TabbyCog):
    # FIXME: Holy shit. This sucks so much.
    @commands.is_owner()
    @commands.command()
    async def run(self, ctx: Context, *, code: Codeblock):
        """Execute a snippet of Python code and display the results

        code:
            The code to execute, enclosed within a codeblock. async/await syntax may be used, and "yield" can be used as
            a shortcut to send a message to the invocation channel. If the last statement in the codeblock is an
            expression, its value is yielded implicitly.
        """

        parsed = ast.parse(code.content)
        if not parsed.body:
            return

        last = parsed.body[-1]
        mangled = code.content

        if isinstance(last, ast.Expr) and not isinstance(last.value, ast.Yield):
            offset = 0

            for line_number, line in enumerate(code.content.splitlines(keepends=True), start=1):
                if line_number == last.lineno:
                    offset += last.col_offset
                    break

                offset += len(line)

            mangled = f"{code.content[:offset]}\nyield {code.content[offset:]}"

        mangled = f"{mangled}\nyield __tabby_yield_marker"
        indented = textwrap.indent(mangled, prefix=" " * 4)
        to_execute = f"async def __tabby_run():\n{indented}\n"

        globals_: dict[str, Any] = {"ctx": ctx, "__tabby_yield_marker": _YIELD_MARKER}
        exec(to_execute, globals_)

        async def execute():
            generator: AsyncGenerator = globals_["__tabby_run"]()

            async for value in generator:
                if value is _YIELD_MARKER:
                    continue

                await ctx.send(str(value))

        await ctx.message.add_reaction("\N{OCTAGONAL SIGN}")

        check: Callable[[Reaction, Member | User], bool] = lambda reaction, user: (
            reaction.message.id == ctx.message.id
            and reaction.emoji == "\N{OCTAGONAL SIGN}"
            and user.id == ctx.author.id
        )

        execution_task = asyncio.create_task(execute())
        cancellation_task = asyncio.create_task(self.bot.wait_for("reaction_add", check=check))
        tasks = (execution_task, cancellation_task)

        _, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()

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
