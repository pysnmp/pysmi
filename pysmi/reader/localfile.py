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
        # One entry per directory visited: its subdirectories, and its regular
        # files keyed by normcase(name) -> actual name. Built once per
        # directory and kept for the reader's lifetime, since get_data() would
        # otherwise re-list the whole tree on every single MIB lookup.
        self._dirCache: dict[str, tuple[list[str], dict[str, str]]] = {}

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def clear_cache(self) -> None:
        """Forget every directory listing cached so far.

        The next lookup re-lists the tree from scratch, seeing whatever is
        on disk right now rather than what was there when each directory was
        first visited.
        """
        self._dirCache.clear()

    def _list_dir(self, path: str, ignoreErrors: bool = True) -> tuple[list[str], dict[str, str]]:
        """List *path* once, caching the result for the reader's lifetime.

        A single :py:func:`os.scandir` pass gives both the subdirectories and
        the regular files, and each entry's type comes from the scan itself
        rather than a separate :py:func:`os.stat` per name.

        Args:
            path (str): directory to list

        Keyword Args:
            ignoreErrors: return an empty listing instead of raising when the
                directory cannot be read

        Returns:
            The subdirectory names, and the regular file names keyed by
            :py:func:`os.path.normcase` of the name, so a candidate can be
            looked up without touching the filesystem again.

            :py:func:`os.path.normcase` matches how the platform's own
            filesystem folds names on Windows (case-insensitive) and Linux
            (case-sensitive). On macOS it does not: the default filesystem
            folds case but ``normcase`` does not, so a file whose case
            differs from every name :py:meth:`~AbstractReader.get_mib_variants`
            generates -- the exact name, all upper, all lower, and the
            ``-mib`` fuzzy forms -- goes unmatched there, where it would
            previously have been found by chance. Reader options already name
            the cases pysmi looks for; this stops relying on the filesystem to
            supply others.

        Raises:
            PySmiError: the directory could not be listed and ``ignoreErrors``
                is not set.
        """
        if path in self._dirCache:
            return self._dirCache[path]

        subdirs: list[str] = []
        files: dict[str, str] = {}

        try:
            with os.scandir(path) as it:
                for entry in it:
                    try:
                        if entry.is_dir():
                            subdirs.append(entry.name)
                        elif entry.is_file():
                            files[os.path.normcase(entry.name)] = entry.name
                    except OSError:
                        # A symlink stat failing here is the entry's problem,
                        # not the directory's; skip it either way.
                        continue

        except OSError as exc:
            if not ignoreErrors:
                raise error.PySmiError(f"directory {path} access error: {exc}") from exc

        self._dirCache[path] = (subdirs, files)
        return subdirs, files

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

        subdirs, _files = self._list_dir(path, ignoreErrors)

        for d in subdirs:
            dirs.extend(self.get_subdirs(os.path.join(decode(path), decode(d)), recursive))

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
            _subdirs, files = self._list_dir(path, self._ignoreErrors)

            for mibalias, mibfile in self.get_mib_variants(mibname, **options):
                actualName = files.get(os.path.normcase(mibfile))

                if actualName is not None:
                    f = os.path.join(decode(path), decode(actualName))

                    logger.debug("trying MIB %s", f, extra={"mib": mibname, "path": f})

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

                        return MibInfo(path=f"file://{f}", file=actualName, name=mibalias, mtime=mtime), decode(mibData)

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
