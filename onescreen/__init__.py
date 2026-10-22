"""1ScreenHGSS - play Pokémon HeartGold/SoulSilver on a single screen."""

# The single source of truth for the version. The CLI, the GUI title and the
# README all take it from here.
__version__ = "0.3"

from .rom import identify, patch  # noqa: F401
