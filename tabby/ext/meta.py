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
from discord import DiscordException, Member, Reaction, User
from discord.ext import commands
from discord.ext.commands import Context
from prettytable import PrettyTable

from . import register_handlers
from .. import util
from ..bot import Tabby, TabbyCog
from ..util import Codeblock


LOGGER = logging.getLogger(__name__)
_YIELD_MARKER = object()


class Meta(TabbyCog):
    @commands.command(aliases=["about"])
    async def hello(self, ctx: Context):
        """Display basic information about Tabby"""

        await ctx.send(
            "Hello! I'm a Discord bot written and maintained by Kaylynn#0001.\n"
            "You can find my source code at <https://github.com/kaylynn234/tabby>.\n"
            "\n"
            f"Currently connected to {len(self.bot.guilds)} guild(s)"
        )


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

        mangled = f"{mangled}\nyield None"
        indented = textwrap.indent(mangled, prefix=" " * 4)
        to_execute = f"async def __tabby_run():\n{indented}\n"

        globals_: dict[str, Any] = {"ctx": ctx, "bot": ctx.bot}

        # By executing the modified body, we place the `__tabby_run` generator into the `globals_` dict, which we then
        # fetch below in order to actually run the generator in async land.
        exec(to_execute, globals_)

        async def execute():
            generator: AsyncGenerator = globals_["__tabby_run"]()

            async for value in generator:
                if value is None:
                    continue

                try:
                    await ctx.send(str(value))
                except DiscordException:
                    # Likely a permission issue or empty message. We can probably ignore this.
                    pass

        # We use a "stop" reaction button so that the invoker can kill the task if it's taking too long for whatever
        # reason. To actually facilitate this, we start two tasks concurrently:
        # - The first task waits for a matching reaction from the invoker, and nothing more.
        # - The second task actually executes the provided code.
        #
        # We block until *one* of these tasks is completed, and then immediately cancel any pending tasks. Since the
        # "reaction listener" task resolves as soon as a matching reaction is received, this allows the invoker to react
        # to the invoking message and stop it early.
        await ctx.message.add_reaction("\N{OCTAGONAL SIGN}")

        check: Callable[[Reaction, Member | User], bool] = lambda reaction, user: (
            reaction.message.id == ctx.message.id
            and reaction.emoji == "\N{OCTAGONAL SIGN}"
            and user.id == ctx.author.id
        )

        execution_task = asyncio.create_task(execute())
        cancellation_task = asyncio.create_task(self.bot.wait_for("reaction_add", check=check))
        tasks = (execution_task, cancellation_task)

        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)

        for task in pending:
            task.cancel()

        # If anything went wrong, we need to let it propagate later. If we *don't* do this, the invoker won't know what
        # they fucked up, and - more pressingly! - the logs will get clogged up with a warning about a task exception
        # not being retrieved.
        error = util.task_exception(done)

        assert self.bot.user is not None

        # Once we're done running everything, we should remove the reaction button we added.
        try:
            await ctx.message.remove_reaction("\N{OCTAGONAL SIGN}", self.bot.user)
        except DiscordException:
            # Most likely the reaction was removed already.
            pass

        # Anything that went wrong should get bubbled up so that it's caught by the error handler
        if error:
            raise error

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
