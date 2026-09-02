#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import contextlib
import importlib.machinery
import os
import py_compile
import tempfile

from pysmi import debug, error
from pysmi.compat import decode, encode
from pysmi.writer.base import AbstractWriter

SOURCE_SUFFIXES = importlib.machinery.SOURCE_SUFFIXES


class PyFileWriter(AbstractWriter):
    """Stores transformed MIB modules as Python files at specified location.

    User is expected to pass *PyFileWriter* class instance to
    *MibCompiler* on instantiation. The rest is internal to *MibCompiler*.
    """

    pyCompile = True
    pyOptimizationLevel = -1

    def __init__(self, path):
        """Creates an instance of *PyFileWriter* class.

        Args:
            path: writable directory to store Python modules
        """
        self._path = decode(os.path.normpath(path))

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def putData(self, mibname, data, comments=(), dryRun=False):
        if dryRun:
            debug.logger & debug.flagWriter and debug.logger("dry run mode")
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

        debug.logger & debug.flagWriter and debug.logger(f"created file {pyfile}")

        if self.pyCompile:
            try:
                py_compile.compile(pyfile, doraise=True, optimize=self.pyOptimizationLevel)

            except (SyntaxError, py_compile.PyCompileError):
                pass  # XXX

            except Exception as exc:
                with contextlib.suppress(Exception):
                    os.unlink(pyfile)

                raise error.PySmiWriterError(f"failure compiling {pyfile}: {exc}", file=mibname, writer=self) from exc

        debug.logger & debug.flagWriter and debug.logger(f"{mibname} stored")

    def getData(self, filename):
        return ""
