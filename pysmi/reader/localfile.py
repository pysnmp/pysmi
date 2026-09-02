#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Reading MIB text from a local directory."""

import logging
import os
import time
from collections.abc import Iterable
from typing import Any

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.mibinfo import MibInfo
from pysmi.reader.base import AbstractReader

logger = logging.getLogger(__name__)


@deprecated_camel_case
class FileReader(AbstractReader):
    """Fetch ASN.1 MIB text by name from local file.

    *FileReader* class instance tries to locate ASN.1 MIB files
    by name, fetch and return their contents to caller.
    """

    useIndexFile = True  # optional .index file mapping MIB to file name
    indexFile = ".index"

    def __init__(self, path: str, recursive: bool = True, ignoreErrors: bool = True) -> None:
        """Create an instance of *FileReader* serving a directory.

        Args:
            path (str): directory to search MIB files

        Keyword Args:
            recursive (bool): whether to include subdirectories
            ignoreErrors (bool): ignore filesystem access errors
        """
        self._path = os.path.normpath(path)
        self._recursive = recursive
        self._ignoreErrors = ignoreErrors
        self._indexLoaded = False
        self._mibIndex: dict[str, str] | None = None

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def get_subdirs(self, path: str, recursive: bool = True, ignoreErrors: bool = True) -> list[str]:
        """List *path* and every directory beneath it.

        Args:
            path (str): directory to start from

        Keyword Args:
            recursive: descend into subdirectories
            ignoreErrors: skip directories that cannot be listed instead of
                raising

        Returns:
            Directories to search, *path* first.

        Raises:
            PySmiError: a directory could not be listed and ``ignoreErrors``
                is not set.
        """
        if not recursive:
            return [path]

        dirs = [path]

        try:
            subdirs = os.listdir(path)

        except OSError as exc:
            if ignoreErrors:
                return dirs

            else:
                raise error.PySmiError(f"directory {path} access error: {exc}") from exc

        for d in subdirs:
            d = os.path.join(decode(path), decode(d))
            if os.path.isdir(d):
                dirs.extend(self.get_subdirs(d, recursive))

        return dirs

    @staticmethod
    def load_index(indexFile: str) -> dict[str, str]:
        """Read a directory's MIB index, mapping module names to file names.

        The index lets a MIB be found without opening every file to see which
        module it defines. A missing or malformed index is not an error; the
        reader falls back to guessing file names.

        Args:
            indexFile (str): path to the index

        Returns:
            Module names mapped to file names, empty when there is no usable
            index.
        """
        mibIndex: dict[str, str] = {}
        if os.path.exists(indexFile):
            try:
                with open(indexFile) as f:
                    # Lines that are not a name/file pair, blank ones
                    # included, are skipped rather than failing the read.
                    mibIndex = {
                        fields[0]: fields[1] for fields in (x.split() for x in f.readlines()) if len(fields) >= 2
                    }
                logger.debug(
                    "loaded MIB index map from %s file, %d entries",
                    indexFile,
                    len(mibIndex),
                    extra={"path": indexFile, "entries": len(mibIndex)},
                )

            except OSError:
                pass

        return mibIndex

    def get_mib_variants(self, mibname: str, **options: Any) -> Iterable[tuple[str, str]]:
        """Consult the directory index before guessing file names.

        When the index names a file for this module, that file is tried first;
        otherwise this behaves as
        :py:meth:`~pysmi.reader.base.AbstractReader.get_mib_variants`.
        """
        if self.useIndexFile:
            if not self._indexLoaded:
                self._mibIndex = self.load_index(os.path.join(self._path, self.indexFile))
                self._indexLoaded = True

            mibIndex = self._mibIndex or {}

            if mibname in mibIndex:
                logger.debug(
                    "found %s in MIB index: %s",
                    mibname,
                    mibIndex[mibname],
                    extra={"mib": mibname, "indexed": mibIndex[mibname]},
                )
                return [(mibname, mibIndex[mibname])]

        return super().get_mib_variants(mibname, **options)

    def get_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Read a MIB from the local directory tree.

        Raises:
            PySmiReaderFileNotFoundError: no file in the tree holds the module.
            PySmiReaderFileNotModifiedError: the file is older than requested.
        """
        logger.debug(
            "%slooking for MIB %s",
            "recursively " if self._recursive else "",
            mibname,
            extra={"mib": mibname, "recursive": bool(self._recursive)},
        )

        for path in self.get_subdirs(self._path, self._recursive, self._ignoreErrors):
            for mibalias, mibfile in self.get_mib_variants(mibname, **options):
                f = os.path.join(decode(path), decode(mibfile))

                logger.debug("trying MIB %s", f, extra={"mib": mibname, "path": f})

                if os.path.exists(f) and os.path.isfile(f):
                    try:
                        mtime = os.stat(f).st_mtime

                        logger.debug(
                            "source MIB %s mtime is %s, fetching data...",
                            f,
                            time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
                            extra={"mib": mibname, "path": f, "mtime": mtime},
                        )

                        with open(f, mode="rb") as fp:
                            mibData = fp.read(self.maxMibSize)

                        if len(mibData) == self.maxMibSize:
                            raise OSError(f"MIB {f} too large")

                        return MibInfo(path=f"file://{f}", file=mibfile, name=mibalias, mtime=mtime), decode(mibData)

                    except OSError as exc:
                        logger.debug(
                            "source file %s open failure: %s",
                            f,
                            exc,
                            extra={"mib": mibname, "path": f, "error": str(exc)},
                        )

                        if not self._ignoreErrors:
                            raise error.PySmiError(f"file {f} access error: {exc}") from exc

                    raise error.PySmiReaderFileNotModifiedError(f"source MIB {f} is older than needed", reader=self)

        raise error.PySmiReaderFileNotFoundError(f"source MIB {mibname} not found", reader=self)
