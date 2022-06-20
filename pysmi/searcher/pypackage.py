#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import os
import time
import struct
try:
    import importlib

    try:
        PY_MAGIC_NUMBER = importlib.util.MAGIC_NUMBER
        SOURCE_SUFFIXES = importlib.machinery.SOURCE_SUFFIXES
        BYTECODE_SUFFIXES = importlib.machinery.BYTECODE_SUFFIXES

    except Exception:
        raise ImportError()

except ImportError:
    import imp

    PY_MAGIC_NUMBER = imp.get_magic()
    SOURCE_SUFFIXES = [s[0] for s in imp.get_suffixes()
                       if s[2] == imp.PY_SOURCE]
    BYTECODE_SUFFIXES = [s[0] for s in imp.get_suffixes()
                         if s[2] == imp.PY_COMPILED]

from pysmi.searcher.base import AbstractSearcher
from pysmi.searcher.pyfile import PyFileSearcher
from pysmi.compat import decode
from pysmi import debug
from pysmi import error


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
        t = (((dosdate >> 9) & 0x7f) + 1980,  # year
             ((dosdate >> 5) & 0x0f),  # month
             dosdate & 0x1f,  # mday
             (dostime >> 11) & 0x1f,  # hour
             (dostime >> 5) & 0x3f,  # min
             (dostime & 0x1f) * 2,  # sec
             -1,  # wday
             -1,  # yday
             -1)  # dst
        return time.mktime(t)

    def fileExists(self, mibname, mtime, rebuild=False):
        if rebuild:
            debug.logger & debug.flagSearcher and debug.logger('pretend %s is very old' % mibname)
            return

        mibname = decode(mibname)

        try:
            p = __import__(self._package, globals(), locals(), ['__init__'])

            if hasattr(p, '__loader__') and hasattr(p.__loader__, '_files'):
                self.__loader = p.__loader__
                self._package = self._package.replace('.', os.sep)
                debug.logger & debug.flagSearcher and debug.logger(
                    f'{self._package} is an importable egg at {os.path.split(p.__file__)[0]}')

            elif hasattr(p, '__file__'):
                debug.logger & debug.flagSearcher and debug.logger(
                    '%s is not an egg, trying it as a package directory' % self._package)
                return PyFileSearcher(os.path.split(p.__file__)[0]).fileExists(mibname, mtime, rebuild=rebuild)

            else:
                raise error.PySmiFileNotFoundError('%s is neither importable nor a file' % self._package, searcher=self)

        except ImportError:
            raise error.PySmiFileNotFoundError('%s is not importable, trying as a path' % self._package, searcher=self)

        for pySfx in BYTECODE_SUFFIXES:
            f = os.path.join(self._package, mibname.upper()) + pySfx

            if f not in self.__loader._files:
                debug.logger & debug.flagSearcher and debug.logger(f'{f} is not in {self._package}')
                continue

            pyData = self.__loader.get_data(f)
            if pyData[:4] == PY_MAGIC_NUMBER:
                pyData = pyData[4:]
                pyTime = struct.unpack('<L', pyData[:4])[0]
                debug.logger & debug.flagSearcher and debug.logger(
                    'found {}, mtime {}'.format(f, time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(pyTime))))
                if pyTime >= mtime:
                    raise error.PySmiFileNotModifiedError()
                else:
                    raise error.PySmiFileNotFoundError('older file %s exists' % mibname, searcher=self)

            else:
                debug.logger & debug.flagSearcher and debug.logger('bad magic in %s' % f)
                continue

        for pySfx in SOURCE_SUFFIXES:

            f = os.path.join(self._package, mibname.upper()) + pySfx

            if f not in self.__loader._files:
                debug.logger & debug.flagSearcher and debug.logger(f'{f} is not in {self._package}')
                continue

            pyTime = self._parseDosTime(
                self.__loader._files[f][6],
                self.__loader._files[f][5]
            )

            debug.logger & debug.flagSearcher and debug.logger(
                'found {}, mtime {}'.format(f, time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(pyTime))))
            if pyTime >= mtime:
                raise error.PySmiFileNotModifiedError()
            else:
                raise error.PySmiFileNotFoundError('older file %s exists' % mibname, searcher=self)

        raise error.PySmiFileNotFoundError('no file %s found' % mibname, searcher=self)
