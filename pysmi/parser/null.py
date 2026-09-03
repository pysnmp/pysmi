#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""A parser that parses nothing."""

from typing import Any

from pysmi.parser.base import AbstractParser


class NullParser(AbstractParser):
    """A parser that reads nothing.

    Stands in where :py:class:`~pysmi.compiler.MibCompiler` needs a parser but
    no MIB is to be parsed, as when copying MIBs rather than compiling them.
    """

    def __init__(self, startSym: str = "mibFile", tempdir: str = "") -> None:
        """Accept and ignore the arguments a real parser would need.

        The signature matches :py:class:`~pysmi.parser.smi.SmiV2Parser` so this
        class can stand in for it, but nothing is built and nothing is cached.
        """
        # Intentionally empty: NullParser performs no initialization.
        pass

    def reset(self) -> None:
        """Do nothing; this parser holds no state."""
        # Intentionally empty: NullParser holds no state to reset.
        pass

    def parse(self, data: str, **kwargs: Any) -> list[Any]:
        """Ignore the text and report no modules."""
        return []
