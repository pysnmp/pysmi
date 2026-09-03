#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Storing transformed modules as files."""

import contextlib
import logging
import os
import tempfile
from collections.abc import Iterable

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode, encode
from pysmi.mibinfo import producer_of
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)


@deprecated_camel_case
class FileWriter(AbstractWriter):
    """Stores transformed MIB modules in files at specified location.

    User is expected to pass *FileReader* class instance to
    *MibCompiler* on instantiation. The rest is internal to *MibCompiler*.
    """

    suffix = ""

    def __init__(self, path: str) -> None:
        """Creates an instance of *FileReader* class.

        Args:
            path: writable directory to store created files
        """
        self._path = decode(os.path.normpath(path))

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def get_data(self, filename: str, dryRun: bool = False) -> str:
        """Read back a file this writer stored, empty when it is not there."""
        path = os.path.join(self._path, decode(filename)) + self.suffix

        try:
            with open(path) as f:
                data = f.read()
            return data

        except (OSError, UnicodeEncodeError):
            return ""

    def put_data(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
        """Write the generated MIB into the destination directory.

        The file is written under a temporary name and moved into place, so a
        failure part-way leaves no half-written MIB behind.

        Raises:
            PySmiWriterError: the destination could not be created or written.
        """
        if dryRun:
            logger.debug("dry run mode", extra={"mib": mibname})
            return

        if not os.path.exists(self._path):
            try:
                os.makedirs(self._path)

            except OSError as exc:
                raise error.PySmiWriterError(
                    f"failure creating destination directory {self._path}: {exc}", writer=self
                ) from exc

        if comments:
            data = "#\n" + "".join([f"# {x}\n" for x in comments]) + "#\n" + data

        filename = os.path.join(self._path, decode(mibname)) + self.suffix

        tfile = None

        try:
            fd, tfile = tempfile.mkstemp(dir=self._path)
            os.write(fd, encode(data))
            os.close(fd)
            os.rename(tfile, filename)

        except (OSError, UnicodeEncodeError) as exc:
            if tfile:
                with contextlib.suppress(OSError):
                    os.unlink(tfile)

            raise error.PySmiWriterError(f"failure writing file {filename}: {exc}", file=filename, writer=self) from exc

        logger.debug("%s stored in %s", mibname, filename, extra={"mib": mibname, "path": filename})

    def list_data(self) -> Iterable[str]:
        """List the MIB modules stored in the destination directory.

        Only files carrying this package's own "Produced by" marker are
        reported -- a file this writer did not itself create is not this
        writer's to enumerate for pruning.
        """
        try:
            entries = os.listdir(self._path)
        except OSError:
            return ()

        names = []

        for entry in entries:
            if self.suffix and not entry.endswith(self.suffix):
                continue

            mibname = entry[: len(entry) - len(self.suffix)] if self.suffix else entry
            path = os.path.join(self._path, entry)

            if not os.path.isfile(path):
                continue

            try:
                with open(path, "rb") as fp:
                    text = decode(fp.read())

            except (OSError, UnicodeDecodeError):
                continue

            if producer_of(text) is not None:
                names.append(mibname)

        return names

    def del_data(self, mibname: str, dryRun: bool = False) -> None:
        """Remove a previously written file from the destination directory."""
        filename = os.path.join(self._path, decode(mibname)) + self.suffix

        if dryRun:
            logger.debug("dry run mode, not removing %s", filename, extra={"mib": mibname, "path": filename})
            return

        try:
            os.unlink(filename)

        except FileNotFoundError:
            return

        except OSError as exc:
            raise error.PySmiWriterError(
                f"failure removing file {filename}: {exc}", file=filename, writer=self
            ) from exc

        logger.debug("%s removed", filename, extra={"mib": mibname, "path": filename})
