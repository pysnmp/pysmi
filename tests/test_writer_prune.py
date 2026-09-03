#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""FileWriter and PyFileWriter can list and remove what they themselves
wrote, the primitives MibCompiler.prune (pysnmp/pysmi#61) is built on.

Both only ever report or remove a file carrying this package's own
"Produced by" marker -- a file the destination directory holds that pysmi
did not write is not theirs to touch.
"""

import os
import tempfile
import unittest

from pysmi.writer import FileWriter, PyFileWriter


class FileWriterPruneTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.writer = FileWriter(self.dst).set_options(suffix=".json")

    def tearDown(self):
        self._tmp.cleanup()

    def testListDataReportsWhatWasWritten(self):
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.0"]}}')
        self.assertEqual(["IF-MIB"], list(self.writer.list_data()))

    def testListDataIgnoresAFileItDidNotWrite(self):
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.0"]}}')

        with open(os.path.join(self.dst, "HAND-WRITTEN.json"), "w") as fp:
            fp.write('{"hand": "written"}')

        self.assertEqual(["IF-MIB"], list(self.writer.list_data()))

    def testListDataOnAnEmptyDirectory(self):
        self.assertEqual([], list(self.writer.list_data()))

    def testListDataOnAMissingDirectory(self):
        writer = FileWriter(os.path.join(self.dst, "does-not-exist")).set_options(suffix=".json")
        self.assertEqual([], list(writer.list_data()))

    def testDelDataRemovesTheFile(self):
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.0"]}}')
        self.writer.del_data("IF-MIB")
        self.assertEqual([], os.listdir(self.dst))

    def testDelDataDryRunLeavesTheFileInPlace(self):
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.0"]}}')
        self.writer.del_data("IF-MIB", dryRun=True)
        self.assertEqual(["IF-MIB.json"], os.listdir(self.dst))

    def testDelDataOnAMissingFileDoesNotRaise(self):
        self.writer.del_data("NO-SUCH-MIB")


class PyFileWriterPruneTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.writer = PyFileWriter(self.dst)
        self.writer.pyCompile = False

    def tearDown(self):
        self._tmp.cleanup()

    def testListDataReportsWhatWasWritten(self):
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])
        self.assertEqual(["IF-MIB"], list(self.writer.list_data()))

    def testListDataIgnoresAFileItDidNotWrite(self):
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])

        with open(os.path.join(self.dst, "HAND-WRITTEN.py"), "w") as fp:
            fp.write("# not from pysmi\n")

        self.assertEqual(["IF-MIB"], list(self.writer.list_data()))

    def testDelDataRemovesTheFile(self):
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])
        self.writer.del_data("IF-MIB")
        self.assertEqual([], os.listdir(self.dst))

    def testDelDataDryRunLeavesTheFileInPlace(self):
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])
        self.writer.del_data("IF-MIB", dryRun=True)
        self.assertEqual(["IF-MIB.py"], os.listdir(self.dst))

    def testDelDataRemovesCachedBytecodeToo(self):
        self.writer.pyCompile = True
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])

        cacheDir = os.path.join(self.dst, "__pycache__")
        self.assertTrue(os.path.isdir(cacheDir), "py_compile should have populated __pycache__")
        self.assertTrue(os.listdir(cacheDir))

        self.writer.del_data("IF-MIB")

        self.assertFalse(os.path.exists(os.path.join(self.dst, "IF-MIB.py")))
        self.assertEqual([], os.listdir(cacheDir))


if __name__ == "__main__":
    unittest.main()
