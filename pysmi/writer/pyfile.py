#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Storing transformed modules as Python files, optionally byte-compiled."""

import contextlib
import importlib.machinery
import logging
import os
import py_compile
import tempfile
from typing import Final

from pysmi import error
from pysmi.compat import decode, encode
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES: Final = importlib.machinery.SOURCE_SUFFIXES


class PyFileWriter(AbstractWriter):
    """Stores transformed MIB modules as Python files at specified location.

    User is expected to pass *PyFileWriter* class instance to
    *MibCompiler* on instantiation. The rest is internal to *MibCompiler*.
    """

    pyCompile = True
    pyOptimizationLevel = -1

    def __init__(self, path: str) -> None:
        """Creates an instance of *PyFileWriter* class.

        Args:
            path: writable directory to store Python modules
        """
        self._path = decode(os.path.normpath(path))

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def putData(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
        """Write the generated MIB as a Python module.

        Comments are rendered as a module docstring. The module is also
        byte-compiled when ``pyCompile`` is set, which it is by default; a
        module that fails to compile is removed rather than left behind.

        Raises:
            PySmiWriterError: the module could not be written or compiled.
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

        pyfile = os.path.join(self._path, decode(mibname))
        pyfile += SOURCE_SUFFIXES[0]

        tfile = None

        try:
            fd, tfile = tempfile.mkstemp(dir=self._path)
            os.write(fd, encode(data))
            os.close(fd)
            os.rename(tfile, pyfile)

        except (OSError, UnicodeEncodeError) as exc:
            if tfile:
                with contextlib.suppress(OSError):
                    os.unlink(tfile)

            raise error.PySmiWriterError(f"failure writing file {pyfile}: {exc}", file=pyfile, writer=self) from exc

        logger.debug("created file %s", pyfile, extra={"mib": mibname, "path": pyfile})

        if self.pyCompile:
            try:
                py_compile.compile(pyfile, doraise=True, optimize=self.pyOptimizationLevel)

            except (SyntaxError, py_compile.PyCompileError):
                pass  # XXX

            # Whatever py_compile failed with, the half-written file has to go.
            except Exception as exc:
                with contextlib.suppress(OSError):
                    os.unlink(pyfile)

                raise error.PySmiWriterError(f"failure compiling {pyfile}: {exc}", file=mibname, writer=self) from exc

        logger.debug("%s stored", mibname, extra={"mib": mibname})

    def getData(self, filename: str) -> str:
        """Return an empty string; compiled modules are not read back."""
        return ""
