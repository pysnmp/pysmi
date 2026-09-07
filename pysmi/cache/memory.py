#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Parse trees kept in this process, bounded and least-recently-used evicted."""

from collections import OrderedDict
from typing import Any

from pysmi.cache.base import AbstractParseCache


class InMemoryParseCache(AbstractParseCache):
    """Holds parse trees in memory for the lifetime of the cache object.

    The default, and the right answer whenever the whole build runs in one
    process. Nothing is serialized, so there is no trust boundary and no
    reconstruction cost.

    Bounded, evicting least-recently-used, so a build over many namespaces
    keeps the shared standard modules -- which are asked for in every namespace
    -- and lets the single-use vendor ones fall out. A parse tree runs to tens
    of kilobytes, so the default bound costs single-digit megabytes.

    Args:
        maxEntries: how many trees to hold. A value of 0 or less means
            unbounded, which is only appropriate when the module set is known
            to be small.
    """

    def __init__(self, maxEntries: int = 256) -> None:
        """Create a cache bounded to *maxEntries* trees."""
        self._entries: OrderedDict[str, list[Any]] = OrderedDict()
        self._maxEntries = maxEntries

    def __repr__(self) -> str:
        """Name the class and its bound."""
        return f"{self.__class__.__name__}(maxEntries={self._maxEntries})"

    def get(self, key: str) -> list[Any] | None:
        """The trees stored under *key*, marking the entry recently used."""
        trees = self._entries.get(key)

        if trees is not None:
            self._entries.move_to_end(key)

        return trees

    def set(self, key: str, trees: list[Any]) -> None:
        """Store *trees*, evicting the least recently used to stay in bounds."""
        self._entries[key] = trees
        self._entries.move_to_end(key)

        if self._maxEntries > 0:
            while len(self._entries) > self._maxEntries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        """Discard every held tree."""
        self._entries.clear()
