#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import importlib.machinery
import importlib.util
import logging
import os
import struct
import time

from pysmi import error
from pysmi.compat import decode
from pysmi.searcher.base import AbstractSearcher
from pysmi.searcher.pyfile import PyFileSearcher

logger = logging.getLogger(__name__)

PY_MAGIC_NUMBER = importlib.util.MAGIC_NUMBER
SOURCE_SUFFIXES = importlib.machinery.SOURCE_SUFFIXES
BYTECODE_SUFFIXES = importlib.machinery.BYTECODE_SUFFIXES


class PyPackageSearcher(AbstractSearcher):
    """Figures out if given Python module (source or bytecode) exists in given
    Python package.

    Python package must be importable.
    """

    def __init__(self, package):
        """Create an instance of *PyPackageSearcher* bound to specific Python
        package.

        Args:
            package (str): name of the Python package to look up Python
                           modules at.
        """
        self._package = package
        self.__loader = None

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._package}"}}'

    @staticmethod
    def _parseDosTime(dosdate, dostime):
        t = (
            ((dosdate >> 9) & 0x7F) + 1980,  # year
            ((dosdate >> 5) & 0x0F),  # month
            dosdate & 0x1F,  # mday
            (dostime >> 11) & 0x1F,  # hour
            (dostime >> 5) & 0x3F,  # min
            (dostime & 0x1F) * 2,  # sec
            -1,  # wday
            -1,  # yday
            -1,
        )  # dst
        return time.mktime(t)

    def fileExists(self, mibname, mtime, rebuild=False):
        if rebuild:
            logger.debug("pretend %s is very old", mibname, extra={"mib": mibname})
            return

        mibname = decode(mibname)

        try:
            p = __import__(self._package, globals(), locals(), ["__init__"])

            if hasattr(p, "__loader__") and hasattr(p.__loader__, "_files"):
                self.__loader = p.__loader__
                self._package = self._package.replace(".", os.sep)
                logger.debug(
                    "%s is an importable egg at %s",
                    self._package,
                    os.path.split(p.__file__)[0],
                    extra={"mib": mibname, "package": self._package, "path": os.path.split(p.__file__)[0]},
                )

            elif hasattr(p, "__file__"):
                logger.debug(
                    "%s is not an egg, trying it as a package directory",
                    self._package,
                    extra={"mib": mibname, "package": self._package},
                )
                return PyFileSearcher(os.path.split(p.__file__)[0]).fileExists(mibname, mtime, rebuild=rebuild)

            else:
                raise error.PySmiFileNotFoundError(f"{self._package} is neither importable nor a file", searcher=self)

        except ImportError as exc:
            raise error.PySmiFileNotFoundError(
                f"{self._package} is not importable, trying as a path", searcher=self
            ) from exc

        for pySfx in BYTECODE_SUFFIXES:
            f = os.path.join(self._package, mibname.upper()) + pySfx

            if f not in self.__loader._files:
                logger.debug(
                    "%s is not in %s", f, self._package, extra={"mib": mibname, "path": f, "package": self._package}
                )
                continue

            pyData = self.__loader.get_data(f)
            if pyData[:4] == PY_MAGIC_NUMBER:
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
            f = os.path.join(self._package, mibname.upper()) + pySfx

            if f not in self.__loader._files:
                logger.debug(
                    "%s is not in %s", f, self._package, extra={"mib": mibname, "path": f, "package": self._package}
                )
                continue

            pyTime = self._parseDosTime(self.__loader._files[f][6], self.__loader._files[f][5])

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

        raise error.PySmiFileNotFoundError(f"no file {mibname} found", searcher=self)
