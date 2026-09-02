#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for reading the MIB index file a source directory may carry."""

import os
import shutil
import sys
import tempfile
import unittest

from pysmi.reader.localfile import FileReader


class LoadIndexTestCase(unittest.TestCase):
    """The index maps MIB module names onto the files that hold them.

    It is an optimisation, not a source of truth, so anything unreadable in it
    is skipped rather than failing the whole read.
    """

    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self._tmpdir, ignore_errors=True)

    def _writeIndex(self, text):
        path = os.path.join(self._tmpdir, "index.csv")
        with open(path, "w") as f:
            f.write(text)
        return path

    def testWellFormedIndex(self):
        path = self._writeIndex("IF-MIB if-mib.txt\nIP-MIB ip-mib.txt\n")

        self.assertEqual(
            FileReader.loadIndex(path),
            {"IF-MIB": "if-mib.txt", "IP-MIB": "ip-mib.txt"},
        )

    def testTrailingBlankLineIsSkipped(self):
        """A blank final line is ordinary in a text file and must not fail."""
        path = self._writeIndex("IF-MIB if-mib.txt\n\n")

        self.assertEqual(FileReader.loadIndex(path), {"IF-MIB": "if-mib.txt"})

    def testShortLineIsSkipped(self):
        path = self._writeIndex("IF-MIB if-mib.txt\nSTRAY-TOKEN\nIP-MIB ip-mib.txt\n")

        self.assertEqual(
            FileReader.loadIndex(path),
            {"IF-MIB": "if-mib.txt", "IP-MIB": "ip-mib.txt"},
        )

    def testTrailingFieldsAreIgnored(self):
        path = self._writeIndex("IF-MIB if-mib.txt extra junk\n")

        self.assertEqual(FileReader.loadIndex(path), {"IF-MIB": "if-mib.txt"})

    def testMissingIndexIsEmpty(self):
        missing = os.path.join(self._tmpdir, "absent.csv")

        self.assertEqual(FileReader.loadIndex(missing), {})


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
