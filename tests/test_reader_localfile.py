#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""FileReader caches each directory it visits for its own lifetime.

Every lookup used to walk the whole search tree from scratch: a fresh
``os.listdir`` per directory, plus an ``os.path.exists``/``os.path.isfile``
pair per candidate file name -- as many as the seven name variants
:py:meth:`~pysmi.reader.base.AbstractReader.get_mib_variants` produces, times
the extensions it tries. A second MIB resolved through the same reader paid
that cost again for directories the first lookup had already read.

These assert the caching does not change what is found, and that it actually
stops hitting the filesystem on a second lookup. See pysnmp/pysmi#62.
"""

import os
import sys
import unittest
from unittest import mock

from pysmi import error
from pysmi.reader.localfile import FileReader


def tree(root):
    """Build a small MIB tree under *root* and return its path.

    ::

        root/
            ROOT-MIB.txt
            sub/
                nested/
                    NESTED-MIB.txt
    """
    os.makedirs(os.path.join(root, "sub", "nested"))

    with open(os.path.join(root, "ROOT-MIB.txt"), "w") as f:
        f.write("ROOT-MIB DEFINITIONS ::= BEGIN END\n")

    with open(os.path.join(root, "sub", "nested", "NESTED-MIB.txt"), "w") as f:
        f.write("NESTED-MIB DEFINITIONS ::= BEGIN END\n")

    return root


class FileReaderCachingTestCase(unittest.TestCase):
    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self.root = tree(self._tmp.name)
        self.reader = FileReader(self.root, recursive=True)

    def tearDown(self):
        self._tmp.cleanup()

    def testTopLevelMibIsFound(self):
        info, data = self.reader.get_data("ROOT-MIB")
        self.assertEqual(info.name, "ROOT-MIB")
        self.assertEqual(info.file, "ROOT-MIB.txt")
        self.assertIn("ROOT-MIB DEFINITIONS", data)

    def testNestedMibIsFound(self):
        info, data = self.reader.get_data("NESTED-MIB")
        self.assertEqual(info.name, "NESTED-MIB")
        self.assertIn("NESTED-MIB DEFINITIONS", data)

    def testSecondLookupTouchesNoFilesystemCalls(self):
        self.reader.get_data("ROOT-MIB")

        with mock.patch("os.scandir") as scandir:
            info, data = self.reader.get_data("NESTED-MIB")

        scandir.assert_not_called()
        self.assertEqual(info.name, "NESTED-MIB")
        self.assertIn("NESTED-MIB DEFINITIONS", data)

    def testFirstLookupListsEachDirectoryOnlyOnce(self):
        real_scandir = os.scandir
        seen = []

        def counting(path="."):
            seen.append(path)
            return real_scandir(path)

        with mock.patch("os.scandir", side_effect=counting):
            self.reader.get_data("NESTED-MIB")

        self.assertEqual(len(seen), len(set(seen)), "a directory was scanned more than once")

    def testMibNotFoundStillRaises(self):
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            self.reader.get_data("NO-SUCH-MIB")

    def testASecondReaderInstanceIsNotAffectedByTheFirstsCache(self):
        self.reader.get_data("ROOT-MIB")

        other = FileReader(self.root, recursive=True)
        info, _data = other.get_data("ROOT-MIB")
        self.assertEqual(info.name, "ROOT-MIB")

    def testClearCacheForgetsWhatWasListed(self):
        # A MIB removed after the first lookup stays invisible until the
        # cache is cleared -- exactly what MibCompiler.prune relies on to
        # see the current filesystem rather than a stale listing left behind
        # by an earlier compile in the same run. See pysnmp/pysmi#61.
        self.reader.get_data("NESTED-MIB")
        os.unlink(os.path.join(self.root, "sub", "nested", "NESTED-MIB.txt"))

        with self.assertRaises(error.PySmiReaderFileNotModifiedError):
            self.reader.get_data("NESTED-MIB")

        self.reader.clear_cache()

        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            self.reader.get_data("NESTED-MIB")


class FileReaderMissingRootTestCase(unittest.TestCase):
    """The cache must not paper over a root directory that cannot be read."""

    def setUp(self):
        self.missing = "/pysmi-test-path-that-does-not-exist"

    def testIgnoreErrorsReportsNotFoundRatherThanRaising(self):
        reader = FileReader(self.missing, recursive=True, ignoreErrors=True)
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            reader.get_data("ANY-MIB")

    def testWithoutIgnoreErrorsTheAccessFailureIsRaised(self):
        reader = FileReader(self.missing, recursive=True, ignoreErrors=False)
        with self.assertRaises(error.PySmiError):
            reader.get_data("ANY-MIB")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
