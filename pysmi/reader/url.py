#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Building readers from source URLs."""

from typing import Any
from urllib import parse as urlparse
from urllib.request import url2pathname

from pysmi import error
from pysmi.reader.base import AbstractReader
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.zipreader import ZipReader


def getReadersFromUrls(*sourceUrls: str, **options: Any) -> list[AbstractReader]:
    """Build readers from MIB source URLs.

    The scheme picks the reader: ``http`` and ``https`` give an
    :py:class:`~pysmi.reader.httpclient.HttpReader`, ``zip`` or a path ending
    in ``.zip`` a :py:class:`~pysmi.reader.zipreader.ZipReader`, and ``file``
    or a bare path a :py:class:`~pysmi.reader.localfile.FileReader`.

    Args:
        sourceUrls (str): URLs to build readers for

    Keyword Args:
        options: passed to :py:meth:`~pysmi.reader.base.AbstractReader.set_options`
            on every reader built

    Returns:
        Readers, in the order their URLs were given.

    Raises:
        PySmiError: a URL uses a scheme no reader handles.
    """
    readers: list[AbstractReader] = []
    for sourceUrl in sourceUrls:
        mibSource = urlparse.urlparse(sourceUrl)

        if mibSource.scheme in ("", "file", "zip"):
            scheme = mibSource.scheme
            if scheme != "file" and (mibSource.path.endswith(".zip") or mibSource.path.endswith(".ZIP")):
                scheme = "zip"

            else:
                scheme = "file"

            if scheme == "file":
                readers.append(FileReader(url2pathname(mibSource.path)).set_options(**options))
            else:
                readers.append(ZipReader(url2pathname(mibSource.path)).set_options(**options))

        elif mibSource.scheme in ("http", "https"):
            readers.append(HttpReader(sourceUrl).set_options(**options))

        else:
            raise error.PySmiError(f"Unsupported URL scheme {sourceUrl}")

    return readers
