#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the writers."""

from typing import Any


class AbstractWriter:
    def setOptions(self, **kwargs: Any) -> "AbstractWriter":
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def putData(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
        raise NotImplementedError()

    def getData(self, filename: str) -> str:
        raise NotImplementedError()
