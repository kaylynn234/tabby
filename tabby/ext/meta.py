import logging

import asyncpg
from discord.ext import commands
from discord.ext.commands import Context
from prettytable import PrettyTable

from . import register_handlers
from ..bot import Tabby, TabbyCog


LOGGER = logging.getLogger(__name__)


class Meta(TabbyCog):
    @commands.is_owner()
    @commands.command()
    async def sql(self, ctx: Context, *, query: str):
        """Execute a SQL command and display the results"""

        async with self.db() as connection:
            records = await connection.fetch(query)

        if records:
            field_names = [name for name, value in records[0].items()]
        else:
            field_names = []

        table = PrettyTable(field_names)
        table.add_rows(tuple(record) for record in records)

        await ctx.send(f"```\n{table}```")


register_handlers()
