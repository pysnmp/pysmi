#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the parsers."""

from typing import Any


class AbstractParser:
    def reset(self) -> None:
        raise NotImplementedError()

    def parse(self, data: str, **kwargs: Any) -> list[Any]:
        raise NotImplementedError()
