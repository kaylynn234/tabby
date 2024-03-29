import asyncio
import base64
from io import BytesIO
import logging
import random
from datetime import timedelta

import discord.utils
from discord import File, Guild, Member, Message
from discord.ext import commands
from discord.ext.commands import BucketType, Context, CooldownMapping, Cooldown
from pydantic import BaseModel
from yarl import URL

from . import register_handlers
from ..bot import Tabby, TabbyCog
from ..level import LEVELS
from ..web import common
from ..web.template import Templates


LOGGER = logging.getLogger(__name__)


class ImportedLevel(BaseModel):
    guild_id: int
    id: int
    xp: int


class Levels(TabbyCog):
    cooldowns: CooldownMapping

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)

        self.cooldowns = CooldownMapping(
            Cooldown(
                rate=bot.config.level.xp_awards_before_cooldown,
                per=bot.config.level.xp_gain_cooldown,
            ),
            BucketType.member,
        )

    @commands.guild_only()
    @commands.command()
    async def rank(self, ctx: Context[Tabby], who: Member | None = None):
        """Display a member's rank and level

        who:
            The person to display a rank for. If not provided, defaults to the message author.
        """

        assert ctx.guild is not None

        if who is None:
            assert isinstance(ctx.author, Member)
            who = ctx.author

        templates = discord.utils.find(
            lambda middleware: isinstance(middleware, Templates),
            ctx.bot.web.middlewares,
        )

        assert isinstance(templates, Templates)

        image = await common.get_guild_member_profile(ctx.guild.id, who.id, templates, ctx.bot)
        buffer = BytesIO(image)
        buffer.seek(0)

        await ctx.send(file=File(buffer, filename="rank.png"))

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="import")
    async def import_levels(self, ctx: Context, import_from: Guild | None = None):
        """Import levels and XP from Mee6

        You must have the "manage server" permission to use this command.
        When importing levels from Mee6, the existing level and XP information in this guild will be overwritten by the
        Mee6 data.

        import_from:
            The server that XP and levels should be imported from, specified with a server ID or name. If this value is
            not provided, it defaults to the server that the command was used in.
        """

        assert ctx.guild is not None

        if import_from is None:
            import_from = ctx.guild

        base_url = URL(f"https://mee6.xyz/api/plugins/levels/leaderboard/{import_from.id}")
        results: list[ImportedLevel] = []
        page = 0

        base_message = (
            "Importing levels might take a long time, so sit tight! "
            "I'll edit this message periodically with my progress."
        )

        progress = await ctx.send(base_message)

        while True:
            async with self.session.get(base_url.with_query(page=page)) as response:
                body: dict = await response.json() if response.ok else {}

            if retry_after := response.headers.get("retry-after"):
                cooldown = int(retry_after) + 1
                resume_at = discord.utils.utcnow() + timedelta(seconds=cooldown)
                timestamp = discord.utils.format_dt(resume_at, style="t")

                extra = f"I'm being rate-limited by Cloudflare! I can keep going at {timestamp}"
                await progress.edit(content=f"{base_message}\n\n{extra}")
                await discord.utils.sleep_until(resume_at)

                continue

            if not response.ok:
                failure_reason = f"({response.reason.title()})" if response.reason else "(no reason provided)"
                await ctx.send(f"Couldn't import levels: status code {response.status} {failure_reason}")

                return

            players = body.get("players", [])
            if not players:
                break

            page += 1
            results.extend(map(ImportedLevel.parse_obj, players))
            await asyncio.sleep(5)

            # We only want to edit our progress message with every 10 pages of data processed.
            if page % 10:
                continue

            extra = f"So far, I've recorded the levels & XP of {page * 100:,} members"
            await progress.edit(content=f"{base_message}\n\n{extra}")

        async with self.db() as connection:
            async with connection.transaction():
                query = """
                    DELETE FROM tabby.levels
                    WHERE guild_id = $1
                """

                await connection.execute(query, ctx.guild.id)
                await connection.copy_records_to_table(
                    "levels",
                    records=((ctx.guild.id, result.id, result.xp) for result in results),
                    columns=("guild_id", "user_id", "total_xp"),
                    schema_name="tabby",
                )

        # The last page will have been empty, so we don't want to include it when calculating a total
        extra = f"All levels imported successfully! I recorded the levels of {page * 100:,} members in total"
        await progress.edit(content=f"{base_message}\n\n{extra}")

    @TabbyCog.listener()
    async def on_message(self, message: Message):
        if not message.guild or message.author.bot:
            return

        ctx = await self.bot.get_context(message)

        # We shouldn't grant XP on command invocations
        if ctx.command:
            return

        # We're rate-limited, so this user doesn't get any XP. Unlucky.
        if self.cooldowns.update_rate_limit(message):
            return

        query = """
            INSERT INTO tabby.levels(guild_id, user_id, total_xp)
            VALUES ($1, $2, $3)
            ON CONFLICT ON CONSTRAINT levels_pkey
            DO UPDATE SET total_xp = tabby.levels.total_xp + $3
            RETURNING total_xp AS current_xp
        """

        awarded_xp = random.randint(15, 25)

        LOGGER.info("awarding %d XP to %s in guild %s", awarded_xp, message.author.name, message.guild.id)

        async with self.db() as connection:
            new_xp = await connection.fetchval(query, message.guild.id, message.author.id, awarded_xp)

        assert new_xp is not None

        # We need to check if the member crossed a level boundary, and trigger an auto-role event if so.
        before = LEVELS.get(new_xp - awarded_xp)
        after = LEVELS.get(new_xp)

        if after.level > before.level:
            assert isinstance(message.author, Member)

            self.bot.dispatch("level", message.author, after.level)


register_handlers()
