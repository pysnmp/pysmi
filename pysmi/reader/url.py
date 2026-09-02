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
                readers.append(FileReader(url2pathname(mibSource.path)).setOptions(**options))
            else:
                readers.append(ZipReader(url2pathname(mibSource.path)).setOptions(**options))

        elif mibSource.scheme in ("http", "https"):
            readers.append(HttpReader(sourceUrl).setOptions(**options))

        else:
            raise error.PySmiError(f"Unsupported URL scheme {sourceUrl}")

    return readers
