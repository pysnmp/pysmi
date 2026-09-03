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

A compiled module is likewise stale once a *different* MIB source is on
offer, even one that satisfies the mtime check: a MIB compiled once from
the bundled fallback (pysnmp/pysmi#113), then later given a primary
source of its own, would otherwise keep the fallback's output forever if
the primary source's mtime happens to be no newer -- the primary source
is read from disk, but its mtime, not its content, is what decides
reuse. See pysnmp/pysmi#123 (review discussion).
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

    def testMatchingDigestIsReportedAsUnmodified(self):
        self._write(f"# Source digest sha256:abc\n# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100, digest="sha256:abc")

    def testADifferentSourceForcesARebuildDespiteAFreshMtime(self):
        # The bug this guards against: a MIB compiled once from a fallback
        # source, then given a primary source of its own whose mtime is no
        # newer than the fallback compile's -- easily true, since the
        # fallback's timestamp is "whenever it was last compiled" and a
        # primary source's is whatever a checkout or a vendor left it at.
        # Without a digest check, only the mtime is compared, and the new
        # source is silently ignored forever.
        self._write(f"# Source digest sha256:abc\n# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotFoundError):
            searcher.file_exists("IF-MIB", time.time() - 100, digest="sha256:different")

    def testNoDigestPassedSkipsTheCheck(self):
        # A caller with nothing to compare against -- the borrowed-MIB path
        # in the compiler, which never sets a digest -- gets the old,
        # mtime-only behaviour, not a forced rebuild.
        self._write(f"# Source digest sha256:abc\n# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100)

    def testNoStoredDigestIsNotTreatedAsAMismatch(self):
        # A file predating this marker, same leniency as the version check.
        self._write(f"# Produced by {packageName}-{packageVersion}\n")

        searcher = PyFileSearcher(self.dst)
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100, digest="sha256:abc")


class AnyFileSearcherVersionTestCase(unittest.TestCase):
    """The JSON-carrying searcher gets the same treatment, reading the
    marker out of meta.comments instead of a "#" line."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.jsonfile = os.path.join(self.dst, "IF-MIB.json")

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, producer, digest=None):
        comments = [f"Produced by {producer}"] if producer else []
        if digest:
            comments.insert(0, f"Source digest {digest}")
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

    def testADifferentSourceForcesARebuildDespiteAFreshMtime(self):
        self._write(f"{packageName}-{packageVersion}", digest="sha256:abc")

        searcher = AnyFileSearcher(self.dst).set_options(exts=[".json"])
        with self.assertRaises(error.PySmiFileNotFoundError):
            searcher.file_exists("IF-MIB", time.time() - 100, digest="sha256:different")

    def testMatchingDigestIsReportedAsUnmodified(self):
        self._write(f"{packageName}-{packageVersion}", digest="sha256:abc")

        searcher = AnyFileSearcher(self.dst).set_options(exts=[".json"])
        with self.assertRaises(error.PySmiFileNotModifiedError):
            searcher.file_exists("IF-MIB", time.time() - 100, digest="sha256:abc")


if __name__ == "__main__":
    unittest.main()
