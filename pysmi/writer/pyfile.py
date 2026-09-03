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
from collections.abc import Iterable
from typing import Final

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode, encode
from pysmi.mibinfo import producer_of
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)

SOURCE_SUFFIXES: Final = importlib.machinery.SOURCE_SUFFIXES


@deprecated_camel_case
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

    def put_data(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
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
            os.replace(tfile, pyfile)

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

    def get_data(self, filename: str) -> str:
        """Return an empty string; compiled modules are not read back."""
        return ""

    def list_data(self) -> Iterable[str]:
        """List the MIB modules stored in the destination directory.

        Only files carrying this package's own "Produced by" marker are
        reported -- a file this writer did not itself create is not this
        writer's to enumerate for pruning.
        """
        suffix = SOURCE_SUFFIXES[0]

        try:
            entries = os.listdir(self._path)
        except OSError:
            return ()

        names = []

        for entry in entries:
            if not entry.endswith(suffix):
                continue

            path = os.path.join(self._path, entry)

            if not os.path.isfile(path):
                continue

            try:
                with open(path, "rb") as fp:
                    text = decode(fp.read())

            except (OSError, UnicodeDecodeError):
                continue

            if producer_of(text) is not None:
                names.append(entry[: -len(suffix)])

        return names

    def del_data(self, mibname: str, dryRun: bool = False) -> None:
        """Remove a previously written module, and its cached bytecode."""
        pyfile = os.path.join(self._path, decode(mibname)) + SOURCE_SUFFIXES[0]

        if dryRun:
            logger.debug("dry run mode, not removing %s", pyfile, extra={"mib": mibname, "path": pyfile})
            return

        try:
            os.unlink(pyfile)

        except FileNotFoundError:
            return

        except OSError as exc:
            raise error.PySmiWriterError(f"failure removing file {pyfile}: {exc}", file=pyfile, writer=self) from exc

        cacheDir = os.path.join(self._path, "__pycache__")

        if os.path.isdir(cacheDir):
            prefix = decode(mibname) + "."

            for entry in os.listdir(cacheDir):
                if entry.startswith(prefix) and entry.endswith(".pyc"):
                    with contextlib.suppress(OSError):
                        os.unlink(os.path.join(cacheDir, entry))

        logger.debug("%s removed", pyfile, extra={"mib": mibname, "path": pyfile})
