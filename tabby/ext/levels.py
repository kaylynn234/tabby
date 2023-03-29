import random
from discord import Message, User
from discord.ext.commands import BucketType, CooldownMapping, Cooldown

from ..bot import Tabby, TabbyCog
from ..level import LEVELS


class Levels(TabbyCog):
    cooldowns: CooldownMapping

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)

        self.cooldowns = CooldownMapping(
            Cooldown(bot.config.xp_per, bot.config.xp_rate),
            BucketType.member,
        )

    @TabbyCog.listener()
    async def on_message(self, message: Message):
        if not message.guild:
            return

        # Will never actually be `None`
        bucket: Cooldown = self.cooldowns.get_bucket(message)  # type: ignore

        # We're rate-limited, so this user doesn't get any XP. Unlucky.
        if bucket.update_rate_limit():
            return

        query = """
            UPDATE tabby.levels
            SET total_xp = total_xp + $3
            WHERE guild_id = $1 AND user_id = $2
            RETURNING total_xp
        """

        awarded_xp = random.randint(15, 25)

        async with self.db() as connection:
            new_xp: int = await connection.fetchval(query, message.guild.id, message.author.id, awarded_xp)

        # We need to check if the member crossed a level boundary, and trigger an auto-role event if so.
        before = LEVELS.get(new_xp - awarded_xp)
        after = LEVELS.get(new_xp)

        if after.level > before.level:
            # I have no idea if this will ever actually *happen*, but I'd rather be safe than sorry.
            if isinstance(message.author, User):
                victim = await message.guild.fetch_member(message.author.id)
            else:
                victim = message.author

            self.bot.dispatch("on_level", victim, after.level)
