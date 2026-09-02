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
    def __init__(self, startSym: str = "mibFile", tempdir: str = "") -> None:
        # Intentionally empty: NullParser performs no initialization.
        pass

    def reset(self) -> None:
        # Intentionally empty: NullParser holds no state to reset.
        pass

    def parse(self, data: str, **kwargs: Any) -> list[Any]:
        return []
