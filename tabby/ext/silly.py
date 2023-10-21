import itertools
import logging
import random
from typing import TYPE_CHECKING

from discord import Enum, Guild, Member, User
from discord.ext import commands
from discord.ext.commands import Context

from ..util import TTLCache

from . import register_handlers
from ..bot import Tabby, TabbyCog


if TYPE_CHECKING:
    from discord.abc import MessageableChannel


LOGGER = logging.getLogger(__name__)


class Silly(TabbyCog):
    _ongoing: TTLCache["Guild | MessageableChannel", "Roulette"]

    def __init__(self, bot: Tabby) -> None:
        super().__init__(bot)
        self._ongoing = TTLCache(expiry=60 ** 2)

    def _roulette_for(self, ctx: Context) -> "Roulette":
        key = ctx.guild or ctx.channel

        return self._ongoing.setdefault(key, Roulette(6))

    @commands.group(invoke_without_command=True)
    async def roulette(self, ctx: Context):
        """Play a game of Russian Roulette in the current server.

        This command simulates a revolving cylinder, so your odds get worse the longer you go on. Once the cylinder is
        empty, you can reload it with the "reload" subcommand, or swap to a cylinder of a different size using the
        "swap" subcommand.

        The state of the cylinder is shared between the entire server, so you can duel with your friends, if you're
        feeling suitably impulsive. Try not to lose your head!
        """

        revolver = self._roulette_for(ctx)
        result = revolver.fire()

        if result is Chamber.empty:
            plural = "s" * (revolver.remaining != 1)
            return await ctx.send(f"*Click*. {revolver.remaining} chamber{plural} left.")

        await ctx.send("**Bang**! The cylinder is now empty.")

    @roulette.command()
    async def reload(self, ctx: Context):
        """Reload the cylinder, and play again."""

        revolver = self._roulette_for(ctx)
        revolver.reload()

        await ctx.send(f"Reloaded the cylinder. {revolver.capacity} chambers left.")

    @roulette.command()
    async def swap(self, ctx: Context, chambers: int):
        """Swap to a cylinder of a different size, and play again."""

        key = ctx.guild or ctx.channel
        self._ongoing[key] = Roulette(chambers)

        await ctx.send(f"Swapped to a cylinder with {chambers} chambers.")


class Chamber(Enum):
    empty = False
    bullet = True


class Roulette:
    _chambers: list[Chamber]
    _capacity: int

    def __init__(self, capacity: int) -> None:
        if capacity <= 1:
            plural = "s" * (capacity != 1)

            raise RouletteError(f"Nobody sane has manufactured a revolver with {capacity} chamber{plural}.")

        self._capacity = capacity
        self.reload()

    @property
    def capacity(self) -> int:
        return self._capacity

    @property
    def remaining(self) -> int:
        return len(self._chambers)

    def reload(self) -> None:
        self._chambers = [Chamber.bullet, *itertools.repeat(Chamber.empty, self._capacity - 1)]
        random.shuffle(self._chambers)

    def fire(self) -> Chamber:
        if not self._chambers:
            raise RouletteError("The cylinder is empty.")

        result = self._chambers.pop()

        if result is Chamber.bullet:
            self._chambers = []

        return result


class RouletteError(Exception):
    pass


register_handlers()
