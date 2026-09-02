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

from pysmi import error
from pysmi.compat import decode, encode
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)


class FileWriter(AbstractWriter):
    """Stores transformed MIB modules in files at specified location.

    User is expected to pass *FileReader* class instance to
    *MibCompiler* on instantiation. The rest is internal to *MibCompiler*.
    """

    suffix = ""

    def __init__(self, path):
        """Creates an instance of *FileReader* class.

        Args:
            path: writable directory to store created files
        """
        self._path = decode(os.path.normpath(path))

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def getData(self, mibname, dryRun=False):
        filename = os.path.join(self._path, decode(mibname)) + self.suffix

        try:
            with open(filename) as f:
                data = f.read()
            return data

        except (OSError, UnicodeEncodeError):
            return ""

    def putData(self, mibname, data, comments=(), dryRun=False):
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
