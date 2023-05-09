# The re-exports are very silly, but they're necessary for things to behave as expected in launch.py

from . import (
    web as web,
    bot as bot,
    config as config,
    ext as ext,
    level as level,
    resources as resources,
    routing as routing,
    util as util,
)
