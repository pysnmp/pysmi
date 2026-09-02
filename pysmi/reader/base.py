#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the readers, and the MIB file name guessing they share."""

import os
from collections.abc import Iterable
from typing import Any

from pysmi.mibinfo import MibInfo


class AbstractReader:
    maxMibSize = 10000000  # MIBs can't be that large
    fuzzyMatching = True  # try different file names while searching for MIB
    originalMatching = uppercaseMatching = lowcaseMatching = True
    exts: list[str] = ["", os.path.extsep + "txt", os.path.extsep + "mib", os.path.extsep + "my"]  # noqa: RUF012
    exts.extend([x.upper() for x in exts if x])

    def setOptions(self, **kwargs: Any) -> "AbstractReader":
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def getMibVariants(self, mibname: str, **options: Any) -> Iterable[tuple[str, str]]:
        filenames = []

        if self.originalMatching:
            filenames.append(mibname)

        if self.uppercaseMatching:
            filenames.append(mibname.upper())

        if self.lowcaseMatching:
            filenames.append(mibname.lower())

        if self.fuzzyMatching:
            part = filenames[-1].find("-mib")
            if part != -1:
                filenames.extend([x[:part] for x in filenames])
            else:
                suffixed = mibname + "-mib"
                filenames.append(suffixed.upper())
                filenames.append(suffixed.lower())

        return ((x, x + y) for x in filenames for y in options.get("exts", self.exts))

    def getData(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        raise NotImplementedError()
