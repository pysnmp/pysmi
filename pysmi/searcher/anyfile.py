#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import os
import time

from pysmi import debug, error
from pysmi.compat import decode
from pysmi.searcher.base import AbstractSearcher


class AnyFileSearcher(AbstractSearcher):
    """Figures out if given file exists at given location."""

    exts = []

    def __init__(self, path):
        """Create an instance of *AnyFileSearcher* bound to specific directory.

        Args:
          path (str): path to local directory
        """
        self._path = os.path.normpath(decode(path))

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def fileExists(self, mibname, mtime, rebuild=False):
        if rebuild:
            debug.logger & debug.flagSearcher and debug.logger(f"pretend {mibname} is very old")
            return

        mibname = decode(mibname)
        basename = os.path.join(self._path, mibname)

        for sfx in self.exts:
            f = basename + sfx
            if not os.path.exists(f) or not os.path.isfile(f):
                debug.logger & debug.flagSearcher and debug.logger(f"{f} not present or not a file")
                continue

            try:
                fileTime = os.stat(f).st_mtime

            except OSError as exc:
                raise error.PySmiSearcherError(f"failure opening compiled file {f}: {exc}", searcher=self) from exc

            debug.logger & debug.flagSearcher and debug.logger(
                "found {}, mtime {}".format(f, time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(fileTime)))
            )

            if fileTime >= mtime:
                raise error.PySmiFileNotModifiedError()

        raise error.PySmiFileNotFoundError(f"no compiled file {mibname} found", searcher=self)
