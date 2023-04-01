from __future__ import annotations

import bisect
import itertools
import logging
import operator
from typing import NamedTuple


# Initialized later - see the bottom of this file!
LEVELS: LevelBounds
LOGGER = logging.getLogger(__name__)


def required_xp(current_level: int) -> int:
    """Return the amount of XP required to advance to advance from `current_level`.

    Note that this number is **not** cumulative; the XP required to reach level 3 is the sum of `required_xp(0)`,
    `required_xp(1)` and `required_xp(2)`.
    """

    base = 5 * (current_level ** 2)
    multiplier = 50 * current_level

    return base + multiplier + 100


class LevelInfo:
    """Progress within an individual level"""

    _levels: "LevelBounds"

    level: int
    """The user's current level"""

    xp: int
    """The total amount of XP that belongs to the user"""

    def __init__(self, bounds: LevelBounds, xp: int) -> None:
        if xp < 0:
            raise ValueError("xp cannot be negative")


        self._levels = bounds
        self.xp = xp
        self.level = bisect.bisect_left(bounds._boundaries, xp) - 1
        LOGGER.info("%d XP -> level %d", self.xp, self.level)

    @property
    def level_floor(self) -> int:
        """The total amount of XP required to reach the current level"""

        return self._levels._boundaries[self.level]

    @property
    def level_ceiling(self) -> int | None:
        """The total amount of XP required to reach the next level.

        If the current level is the maximum level allowed by the underlying `LevelBounds`, this value will always be
        `None`.
        """

        next_level = self.level + 1

        if next_level >= len(self._levels._boundaries):
            return

        return self._levels._boundaries[next_level]

    @property
    def gained_xp(self) -> int:
        """The amount of XP gained within the bounds of this level"""

        return self.xp - self.level_floor

    @property
    def remaining_xp(self) -> int:
        """The amount of XP required to reach the next level. This is **not** a cumulative amount, and is relative to
        the user's current XP."""

        return 0 if self.level_ceiling is None else self.level_ceiling - self.xp

    @property
    def progress(self) -> float:
        """The user's progress towards the next level, represented as a decimal number between 0 and 1.

        If the current level is the maximum level allowed by the underlying `LevelBounds`, this value will always be
        `1.0`.
        """

        if self.level_ceiling is None:
            return 1.0

        required = self.level_ceiling - self.level_floor

        return self.gained_xp / required


class LevelBounds:
    _boundaries: list[int]

    def __init__(self, *, max_level: int) -> None:
        if max_level < 1:
            raise ValueError("max_level cannot be 0 or negative")

        xp_requirements = map(required_xp, range(max_level + 1))
        self._boundaries = [*itertools.accumulate(xp_requirements, operator.add, initial=0)]

    def get(self, xp: int) -> LevelInfo:
        return LevelInfo(self, xp)


LEVELS = LevelBounds(max_level=1_000)
