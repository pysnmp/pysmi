#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import os
import time
import struct
import importlib.machinery
import importlib.util

SOURCE_SUFFIXES = importlib.machinery.SOURCE_SUFFIXES
BYTECODE_SUFFIXES = importlib.machinery.BYTECODE_SUFFIXES

from pysmi.searcher.base import AbstractSearcher
from pysmi.compat import decode
from pysmi import debug
from pysmi import error


class PyFileSearcher(AbstractSearcher):
    """Figures out if given Python file (source or bytecode) exists at given
       location.
    """
    def __init__(self, path):
        """Create an instance of *PyFileSearcher* bound to specific directory.

           Args:
             path (str): path to local directory
        """
        self._path = os.path.normpath(decode(path))

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def fileExists(self, mibname, mtime, rebuild=False):
        if rebuild:
            debug.logger & debug.flagSearcher and debug.logger('pretend %s is very old' % mibname)
            return

        mibname = decode(mibname)
        pyfile = os.path.join(self._path, mibname)

        for pySfx in BYTECODE_SUFFIXES:
            f = pyfile + pySfx

            if not os.path.exists(f) or not os.path.isfile(f):
                debug.logger & debug.flagSearcher and debug.logger('%s not present or not a file' % f)
                continue

            try:
                with open(f, 'rb') as fp:
                    pyData = fp.read(8)

            except OSError as exc:
                raise error.PySmiSearcherError(f'failure opening compiled file {f}: {exc}',
                                               searcher=self)
            if pyData[:4] == importlib.util.MAGIC_NUMBER:
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
            f = pyfile + pySfx

            if not os.path.exists(f) or not os.path.isfile(f):
                debug.logger & debug.flagSearcher and debug.logger('%s not present or not a file' % f)
                continue

            try:
                pyTime = os.stat(f).st_mtime

            except OSError as exc:
                raise error.PySmiSearcherError(f'failure opening compiled file {f}: {exc}',
                                               searcher=self)

            debug.logger & debug.flagSearcher and debug.logger(
                'found {}, mtime {}'.format(f, time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(pyTime))))

            if pyTime >= mtime:
                raise error.PySmiFileNotModifiedError()

        raise error.PySmiFileNotFoundError('no compiled file %s found' % mibname, searcher=self)
