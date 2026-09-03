#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Looking for an already-compiled PySNMP module inside a Python package."""

import importlib.machinery
import importlib.util
import logging
import os
import struct
import time
from typing import Any, Final, Protocol, cast

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.searcher.base import AbstractSearcher
from pysmi.searcher.pyfile import PyFileSearcher

logger = logging.getLogger(__name__)


class _EggLoader(Protocol):
    """The slice of the zipimporter interface this searcher uses.

    ``_files`` is private to zipimport, but it is how MIBs packaged in an egg
    are found; the loader is only used after ``hasattr(loader, "_files")``
    confirms it is really a zipimporter.
    """

    _files: dict[str, tuple[Any, ...]]

    def get_data(self, pathname: str) -> bytes:
        """Return the bytes of a file inside the package."""
        ...


PY_MAGIC_NUMBER: Final = importlib.util.MAGIC_NUMBER
SOURCE_SUFFIXES: Final = importlib.machinery.SOURCE_SUFFIXES
BYTECODE_SUFFIXES: Final = importlib.machinery.BYTECODE_SUFFIXES


@deprecated_camel_case
class PyPackageSearcher(AbstractSearcher):
    """Figures out if given Python module (source or bytecode) exists in given
    Python package.

    Python package must be importable.
    """

    def __init__(self, package: str) -> None:
        """Create an instance of *PyPackageSearcher* bound to specific Python
        package.

        Args:
            package (str): name of the Python package to look up Python
                           modules at.
        """
        self._package = package
        self.__loader: _EggLoader | None = None

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._package}"}}'

    @staticmethod
    def _parseDosTime(dosdate: int, dostime: int) -> float:
        """Convert a packed MS-DOS date and time to a POSIX timestamp.

        ZIP archives, and so importable eggs, store timestamps this way.
        """
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

    def file_exists(self, mibname: str, mtime: float, rebuild: bool = False, digest: str | None = None) -> None:
        """Look for a compiled MIB inside an importable Python package.

        Handles both packages on the filesystem and packages inside a zipped
        egg, where timestamps come from the archive directory. ``digest`` is
        forwarded to :py:class:`~pysmi.searcher.pyfile.PyFileSearcher` when a
        package turns out to be a plain directory; a zipped egg's directory
        entry carries no source text to check it against, the same
        limitation as its "Produced by" marker check.
        """
        if rebuild:
            logger.debug("pretend %s is very old", mibname, extra={"mib": mibname})
            return

        mibname = decode(mibname)
        loader: _EggLoader | None = None

        try:
            p = __import__(self._package, globals(), locals(), ["__init__"])

            # A namespace package has a __file__ attribute set to None, so ask
            # for the value rather than for the attribute.
            packageFile = getattr(p, "__file__", None)

            if hasattr(p, "__loader__") and hasattr(p.__loader__, "_files"):
                loader = self.__loader = cast("_EggLoader", p.__loader__)
                self._package = self._package.replace(".", os.sep)
                packageDir = os.path.split(packageFile)[0] if packageFile else ""
                logger.debug(
                    "%s is an importable egg at %s",
                    self._package,
                    packageDir,
                    extra={"mib": mibname, "package": self._package, "path": packageDir},
                )

            elif packageFile is not None:
                logger.debug(
                    "%s is not an egg, trying it as a package directory",
                    self._package,
                    extra={"mib": mibname, "package": self._package},
                )
                return PyFileSearcher(os.path.split(packageFile)[0]).file_exists(
                    mibname, mtime, rebuild=rebuild, digest=digest
                )

            else:
                raise error.PySmiFileNotFoundError(f"{self._package} is neither importable nor a file", searcher=self)

        except ImportError as exc:
            raise error.PySmiFileNotFoundError(
                f"{self._package} is not importable, trying as a path", searcher=self
            ) from exc

        if loader is None:
            raise error.PySmiFileNotFoundError(f"{self._package} is not an egg", searcher=self)

        for pySfx in BYTECODE_SUFFIXES:
            f = os.path.join(self._package, mibname.upper()) + pySfx

            if f not in loader._files:
                logger.debug(
                    "%s is not in %s", f, self._package, extra={"mib": mibname, "path": f, "package": self._package}
                )
                continue

            pyData = loader.get_data(f)
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

            if f not in loader._files:
                logger.debug(
                    "%s is not in %s", f, self._package, extra={"mib": mibname, "path": f, "package": self._package}
                )
                continue

            pyTime = self._parseDosTime(loader._files[f][6], loader._files[f][5])

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
