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

from pysmi._aliases import deprecated_camel_case
from pysmi.mibinfo import MibInfo


@deprecated_camel_case
class AbstractReader:
    """Base class for MIB source readers.

    A reader fetches ASN.1 MIB text from one place -- a directory, a web
    server, a ZIP archive. The compiler tries its readers in the order they
    were added and takes the first that produces the module.

    Subclasses implement :py:meth:`get_data`. The file name guessing in
    :py:meth:`get_mib_variants` is shared by all of them, since a MIB module is
    named inside the file but a reader only has the file name to go on.
    """

    maxMibSize = 10000000  # MIBs can't be that large
    fuzzyMatching = True  # try different file names while searching for MIB
    originalMatching = uppercaseMatching = lowcaseMatching = True
    exts: list[str] = ["", os.path.extsep + "txt", os.path.extsep + "mib", os.path.extsep + "my"]  # noqa: RUF012
    exts.extend([x.upper() for x in exts if x])

    def set_options(self, **kwargs: Any) -> "AbstractReader":
        """Set reader options as attributes.

        Keyword Args:
            kwargs: option names and values, each assigned to the reader

        Returns:
            The reader, so calls can be chained.
        """
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def get_mib_variants(self, mibname: str, **options: Any) -> Iterable[tuple[str, str]]:
        """Guess the file names a MIB module might be stored under.

        A module is named inside the file, not by it, so the same MIB turns up
        as ``IF-MIB``, ``if-mib.txt``, ``IF-MIB.my`` and so on. This produces
        the spellings to try, honouring the ``originalMatching``,
        ``uppercaseMatching``, ``lowcaseMatching`` and ``fuzzyMatching``
        attributes, each combined with every extension in ``exts``.

        Args:
            mibname (str): MIB module name to look for

        Keyword Args:
            exts: extensions to try instead of the ``exts`` attribute

        Returns:
            Pairs of MIB alias and candidate file name.
        """
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

    def get_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Fetch the ASN.1 source of a MIB module.

        Args:
            mibname (str): MIB module name to fetch

        Keyword Args:
            options: passed through to :py:meth:`get_mib_variants`

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its ASN.1 text.

        Raises:
            PySmiReaderFileNotFoundError: this source does not have the MIB.
            PySmiReaderFileNotModifiedError: the source is older than requested.
        """
        raise NotImplementedError()
