import asyncio
import dataclasses
import logging
import random
from datetime import datetime, timedelta
from io import BytesIO

import discord.utils
from discord import File, Member, Message, User
from discord.ext import commands
from discord.ext.commands import BucketType, Context, CooldownMapping, Cooldown
from selenium.webdriver import Firefox, FirefoxOptions
from selenium.webdriver.common.by import By
from yarl import URL

from . import register_handlers
from ..bot import Tabby, TabbyCog
from ..extract import Extractable
from ..level import LEVELS
from ..util import DriverPool


LOGGER = logging.getLogger(__name__)


@dataclasses.dataclass
class ImportedLevel(Extractable):
    guild_id: int
    id: int
    xp: int


class Levels(TabbyCog):
    cooldowns: CooldownMapping
    drivers: DriverPool

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)

        self.drivers = DriverPool()
        self.cooldowns = CooldownMapping(
            Cooldown(
                rate=bot.config.level.xp_awards_before_cooldown,
                per=bot.config.level.xp_gain_cooldown,
            ),
            BucketType.member,
        )

    async def cog_load(self) -> None:
        async def _build_drivers():
            options = FirefoxOptions()
            options.add_argument("-headless")

            LOGGER.info("spawning %d drivers concurrently", self.config.limits.webdrivers)

            await self.drivers.setup(
                driver_count=self.config.limits.webdrivers,
                options=options,
            )

            LOGGER.info("all drivers spawned successfully")

        asyncio.create_task(_build_drivers())

    @commands.guild_only()
    @commands.command()
    async def rank(self, ctx: Context, who: Member | None = None):
        """Display a member's rank and level

        who:
            The person to display a rank for. If not provided, defaults to the message author.
        """

        assert ctx.guild is not None

        if who is None:
            assert isinstance(ctx.author, Member)
            who = ctx.author

        url = self.local_api.url_for("profiles").with_query(
            guild_id=ctx.guild.id,
            member_id=who.id,
            username=who.name,
            tag=who.discriminator,
            avatar=who.display_avatar.with_format("webp").url,
        )

        async with self.drivers.get() as driver:
            loop = asyncio.get_running_loop()
            image = await loop.run_in_executor(None, lambda: _render_rank_card(driver, url))

        await ctx.send(file=File(image, filename="rank.png"))

    @commands.has_guild_permissions(manage_guild=True)
    @commands.command(name="import")
    async def import_levels(self, ctx: Context, guild_id: int):
        """Import levels and XP from Mee6

        You must have the "manage guild" permission to use this command.
        When importing levels from Mee6, the existing level and XP information in this guild will be overwritten by the
        Mee6 data.

        guild_id:
            The ID of the guild that XP and levels should be imported from.
        """

        assert ctx.guild is not None

        base_url = URL(f"https://mee6.xyz/api/plugins/levels/leaderboard/{guild_id}")
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
            results.extend(map(ImportedLevel.extract, players))
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
                    records=((result.guild_id, result.id, result.xp) for result in results),
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

            self.bot.dispatch("on_level", message.author, after.level)


def _render_rank_card(driver: Firefox, url: URL) -> BytesIO:
    driver.get(str(url))

    buffer = BytesIO()
    element = driver.find_element(By.CLASS_NAME, value="container")

    buffer.write(element.screenshot_as_png)
    buffer.seek(0)

    return buffer


register_handlers()
