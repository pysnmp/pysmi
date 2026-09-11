#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Parse trees kept on disk, so they outlive the process that built them."""

import logging
import os
import pickle
import tempfile
from typing import Any

from pysmi.cache.base import AbstractParseCache

logger = logging.getLogger(__name__)


class FileParseCache(AbstractParseCache):
    """Holds parse trees as files in a directory.

    The provider for a build that is not one process. A corpus build driven as
    a shell loop starts a fresh interpreter per namespace, so an in-memory
    cache is empty every time; a directory survives, and the standard modules
    are parsed once for the whole build rather than once per namespace.

    Also useful for repeated builds of a mostly-unchanged corpus, since a
    module whose text has not changed keeps its key and so keeps its entry.

    .. warning::

       **Reading this cache reconstructs arbitrary Python objects.** A parse
       tree is not a data format with a schema; storing one means pickling it,
       and reading one back means unpickling, which executes whatever the file
       says to execute. Point this at a directory only your own build writes.
       Do not share one between trust domains, do not put one on a writable
       network share, and do not populate one from an artifact you did not
       produce.

       :py:class:`~pysmi.cache.memory.InMemoryParseCache` has no such
       boundary and is the default for that reason. Use this one when the
       build genuinely spans processes, and treat the directory with the same
       care as a directory of executables.

    Nothing here is required for correctness: every read is verified to
    round-trip and any failure -- unreadable file, truncated write, a pickle
    this Python cannot load -- is logged and treated as a miss, so a damaged
    cache costs time and never output.

    Args:
        path: directory to hold the entries. Created if it does not exist.
    """

    def __init__(self, path: str) -> None:
        """Create a cache backed by the directory at *path*."""
        self._path = path

        os.makedirs(path, exist_ok=True)

    def __repr__(self) -> str:
        """Name the class and the directory."""
        return f"{self.__class__.__name__}({self._path!r})"

    #: Prefixed onto every entry file. The directory may hold files this cache
    #: did not write -- a build's own metadata, another tool's state -- and
    #: :py:meth:`clear` must not remove them. Filtering on ``.pickle`` alone
    #: would; filtering on the key's shape would not work either, since a key
    #: is whatever the caller's compiler composed and need not look like a
    #: digest. An owned prefix answers both.
    ENTRY_PREFIX = "pysmi-parse-"

    #: Extension for entry files. Names them for what they are, and keeps the
    #: pickling visible to anyone looking at the directory.
    ENTRY_SUFFIX = ".pickle"

    def _entry(self, key: str) -> str:
        """The file an entry lives in.

        The key is composed by the compiler and hashed, so it is already a safe
        file name; ``basename`` confines it to the cache directory by
        construction rather than trusting it to stay there.
        """
        name = self.ENTRY_PREFIX + os.path.basename(key) + self.ENTRY_SUFFIX

        return os.path.join(self._path, name)

    def get(self, key: str) -> list[Any] | None:
        """The trees stored under *key*, or ``None`` on a miss or any failure."""
        entry = self._entry(key)

        try:
            with open(entry, "rb") as fd:
                # The directory is the trust boundary, and the class docstring
                # says so: an entry is only ever one this build wrote.
                trees = pickle.load(fd)  # noqa: S301

        except FileNotFoundError:
            return None

        # Unpickling raises whatever the stored graph raises -- UnpicklingError,
        # EOFError, AttributeError, ImportError, a module's own error. A cache
        # is an optimisation, so every one of them is a miss.
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "discarding unreadable cache entry %s: %s",
                entry,
                exc,
                extra={"entry": entry},
            )
            return None

        # Shape check, not a safety one -- by here the pickle has already run.
        # It catches an entry that is merely wrong: written by something else,
        # or by a version whose trees were a different shape. Malice is ruled
        # out by controlling the directory, not by this.
        if not isinstance(trees, list):
            logger.debug(
                "ignoring cache entry %s: expected a list, found %s",
                entry,
                type(trees).__name__,
                extra={"entry": entry},
            )
            return None

        return trees

    def set(self, key: str, trees: list[Any]) -> None:
        """Store *trees*, atomically, so a reader never sees a partial write."""
        entry = self._entry(key)

        try:
            fd, temporary = tempfile.mkstemp(dir=self._path, suffix=".partial")

            try:
                with os.fdopen(fd, "wb") as handle:
                    pickle.dump(trees, handle, protocol=pickle.HIGHEST_PROTOCOL)

                # Rename is atomic within a directory, so a concurrent build
                # reading this key sees either the previous entry or this one,
                # never a half-written file. Both are the same content, since
                # the key is derived from it.
                os.replace(temporary, entry)

            except BaseException:
                # Do not leave the partial behind for the next run to trip on.
                try:
                    os.unlink(temporary)

                except OSError:
                    pass

                raise

        # Failing to store is not a compilation failure: a full disk, a
        # read-only directory or an unpicklable tree all just mean no entry.
        except Exception as exc:  # noqa: BLE001
            logger.debug("could not cache %s: %s", entry, exc, extra={"entry": entry})

    def clear(self) -> None:
        """Remove every entry this cache wrote, and nothing else.

        Entries are recognised by :py:attr:`ENTRY_PREFIX`, so a file the
        directory holds for some other reason survives -- including one that
        happens to be a pickle.
        """
        try:
            names = os.listdir(self._path)

        except OSError:
            return

        for name in names:
            if not (
                name.startswith(self.ENTRY_PREFIX) and name.endswith(self.ENTRY_SUFFIX)
            ):
                continue

            try:
                os.unlink(os.path.join(self._path, name))

            except OSError:
                pass
