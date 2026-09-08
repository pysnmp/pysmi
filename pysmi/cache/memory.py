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
    -- and lets the single-use vendor ones fall out.

    The bound has to exceed what one pass over a source set touches, or the
    cache returns nothing at all. A pass reads its modules once in order, so
    when the bound is smaller than that set, the entry a second pass asks for
    first is the one evicted first, and every miss evicts what the next lookup
    wanted: least-recently-used is the worst policy for a scan longer than the
    cache, and the hit rate is zero rather than reduced. Measured over
    ``pysnmp/mibs``, the largest namespace touches 1672 modules and holds
    198 MiB of trees; a mid-sized one, 322 modules and 33 MiB. The default is
    set above the largest of those. Nothing is preallocated -- a caller
    compiling ten modules holds ten trees -- so the bound costs only what a
    run actually reaches.

    Args:
        maxEntries: how many trees to hold. A value of 0 or less means
            unbounded, for a caller that would rather run out of memory than
            re-parse.
    """

    def __init__(self, maxEntries: int = 2048) -> None:
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
