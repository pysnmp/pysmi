#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Fetching ASN.1 MIB text from wherever it lives."""

from pysmi.reader.callback import CallbackReader
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.package import PackageReader
from pysmi.reader.url import getReadersFromUrls
from pysmi.reader.zipreader import ZipReader

#: The remote ASN.1 sources `mibdump` and `mibcopy` read when no ``--mib-source``
#: is given, in the order they are tried.
#:
#: Both entries are written by the same build of the pysnmp MIB distribution and
#: carry the same modules, so the second is an availability fallback rather than
#: a wider corpus. A module absent from the first is absent from both, and costs
#: one extra request to establish that.
#:
#: ``data.mibsdepot.com`` is object storage addressed by exact key, with no
#: listing: a reader has to know the module name, which is what ``@mib@``
#: supplies. To read a module rather than fetch one, the same corpus is rendered
#: as pages at https://mibsdepot.com/browse/.
DEFAULT_MIB_SOURCES = [
    "https://data.mibsdepot.com/asn1/@mib@",
    "https://pysnmp.github.io/mibs/asn1/@mib@",
]

__all__ = [
    "DEFAULT_MIB_SOURCES",
    "CallbackReader",
    "FileReader",
    "HttpReader",
    "PackageReader",
    "ZipReader",
    "getReadersFromUrls",
]
