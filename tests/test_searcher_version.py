#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A compiled module is stale once a different pysmi produced it, even if
its mtime says otherwise -- compile only ever consults the source's mtime,
so a pysmi bugfix landing with no change to the MIB text would otherwise
never take effect on output already on disk. See pysnmp/pysmi#63.
"""

import json
import os
import tempfile
import time
import unittest

from pysmi import __name__ as packageName
from pysmi import __version__ as packageVersion
from pysmi import error
from pysmi.searcher.anyfile import AnyFileSearcher
from pysmi.searcher.pyfile import PyFileSearcher


def touch_newer_than(path, mtime):
    """Set *path*'s mtime comfortably after *mtime*, matching what a fresh
    compile would leave behind."""
    newer = mtime + 10
    os.utime(path, (newer, newer))


class PyFileSearcherVersionTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.pyfile = os.path.join(self.dst, "IF-MIB.py")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, producerLine):
        with open(self.pyfile, "w") as fp:
            fp.write(f"#\n# ASN.1 source IF-MIB\n{producerLine}#\nout = 1\n")
        touch_newer_than(self.pyfile, time.time())

    def testSameVersionIsReportedAsUnmodified(self):
        self._write(f"# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testOlderPysmiVersionForcesARebuild(self):
        self._write(f"# Produced by {packageName}-0.0.1\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotFoundError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testAPreReleaseVersionIsAlsoComparedCorrectly(self):
        # Regression case for the marker's own hyphen: a naive parse of
        # "pysmi-2.0.0-rc.11" would read the version as "0.0-rc.11" or
        # similar and never match, forcing a rebuild every time.
        self._write(f"# Produced by {packageName}-{packageVersion}\n")

        with open(self.pyfile) as fp:
            recorded = fp.read()
        self.assertIn(f"{packageName}-{packageVersion}", recorded)

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testNoMarkerAtAllIsNotTreatedAsAMismatch(self):
        # A file with no marker is not proof it came from a different
        # pysmi -- only an explicit mismatch forces a rebuild.
        with open(self.pyfile, "w") as fp:
            fp.write("out = 1\n")
        touch_newer_than(self.pyfile, time.time())

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testAnOlderSourceStillRebuildsRegardlessOfVersion(self):
        self._write(f"# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotFoundError):
            searcher.file_exists("IF-MIB", time.time() + 1000)


class AnyFileSearcherVersionTestCase(unittest.TestCase):
    """The JSON-carrying searcher gets the same treatment, reading the
    marker out of meta.comments instead of a "#" line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.jsonfile = os.path.join(self.dst, "IF-MIB.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, producer):
        comments = [f"Produced by {producer}"] if producer else []
        with open(self.jsonfile, "w") as fp:
            json.dump({"meta": {"comments": comments}}, fp)
        touch_newer_than(self.jsonfile, time.time())

    def testSameVersionIsReportedAsUnmodified(self):
        self._write(f"{packageName}-{packageVersion}")

        searcher = AnyFileSearcher(self.dst).set_options(exts=[".json"])
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testOlderPysmiVersionForcesARebuild(self):
        self._write(f"{packageName}-0.0.1")

        searcher = AnyFileSearcher(self.dst).set_options(exts=[".json"])
        with self.assertRaises(error.PySmiFileNotFoundError):
            searcher.file_exists("IF-MIB", time.time() - 100)


if __name__ == "__main__":
    unittest.main()
