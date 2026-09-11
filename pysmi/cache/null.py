#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A cache that holds nothing, for turning caching off."""

from typing import Any

from pysmi.cache.base import AbstractParseCache


class NullParseCache(AbstractParseCache):
    """Stores nothing and always misses.

    Every module is parsed each time it is presented, which is the behaviour
    of every pysmi release before the cache existed. Use it to take the cache
    out of the picture when measuring, or where holding trees is not wanted.
    """

    def __repr__(self) -> str:
        """Name the class."""
        return f"{self.__class__.__name__}()"

    def get(self, key: str) -> list[Any] | None:
        """Always a miss."""
        return None

    def set(self, key: str, trees: list[Any]) -> None:
        """Discards *trees*."""

    def clear(self) -> None:
        """Nothing to discard."""
