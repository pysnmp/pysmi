#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the searchers."""

from typing import Any


class AbstractSearcher:
    def setOptions(self, **kwargs: Any) -> "AbstractSearcher":
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def fileExists(self, mibname: str, mtime: float, rebuild: bool = False) -> None:
        raise NotImplementedError()
