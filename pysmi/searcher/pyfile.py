#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Looking for an already-compiled PySNMP module on disk."""

import importlib.machinery
import importlib.util
import logging
import os
import struct
import time
from typing import Final

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.searcher.base import AbstractSearcher

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES: Final = importlib.machinery.SOURCE_SUFFIXES
BYTECODE_SUFFIXES: Final = importlib.machinery.BYTECODE_SUFFIXES


@deprecated_camel_case
class PyFileSearcher(AbstractSearcher):
    """Figures out if given Python file (source or bytecode) exists at given
    location.
    """

    def __init__(self, path: str) -> None:
        """Create an instance of *PyFileSearcher* bound to specific directory.

        Args:
          path (str): path to local directory
        """
        self._path = os.path.normpath(decode(path))

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def file_exists(self, mibname: str, mtime: float, rebuild: bool = False) -> None:
        """Compare a compiled Python module's timestamp against the MIB source.

        The timestamp is read out of the bytecode header rather than from the
        filesystem, so touching the file does not make it look current.
        """
        if rebuild:
            logger.debug("pretend %s is very old", mibname, extra={"mib": mibname})
            return

        mibname = decode(mibname)
        pyfile = os.path.join(self._path, mibname)

        for pySfx in BYTECODE_SUFFIXES:
            f = pyfile + pySfx

            if not os.path.exists(f) or not os.path.isfile(f):
                logger.debug("%s not present or not a file", f, extra={"mib": mibname, "path": f})
                continue

            try:
                with open(f, "rb") as fp:
                    pyData = fp.read(8)

            except OSError as exc:
                raise error.PySmiSearcherError(f"failure opening compiled file {f}: {exc}", searcher=self) from exc
            if pyData[:4] == importlib.util.MAGIC_NUMBER:
                pyData = pyData[4:]
                pyTime = struct.unpack("<L", pyData[:4])[0]
                logger.debug(
                    "found %s, mtime %s",
                    f,
                    time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(pyTime)),
                    extra={"mib": mibname, "path": f, "mtime": pyTime},
                )
                if pyTime >= mtime:
                    raise error.PySmiFileNotModifiedError()

                else:
                    raise error.PySmiFileNotFoundError(f"older file {mibname} exists", searcher=self)

            else:
                logger.debug("bad magic in %s", f, extra={"mib": mibname, "path": f})
                continue

        for pySfx in SOURCE_SUFFIXES:
            f = pyfile + pySfx

            if not os.path.exists(f) or not os.path.isfile(f):
                logger.debug("%s not present or not a file", f, extra={"mib": mibname, "path": f})
                continue

            try:
                pyTime = os.stat(f).st_mtime

            except OSError as exc:
                raise error.PySmiSearcherError(f"failure opening compiled file {f}: {exc}", searcher=self) from exc

            logger.debug(
                "found %s, mtime %s",
                f,
                time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(pyTime)),
                extra={"mib": mibname, "path": f, "mtime": pyTime},
            )

            if pyTime >= mtime:
                raise error.PySmiFileNotModifiedError()

        raise error.PySmiFileNotFoundError(f"no compiled file {mibname} found", searcher=self)
