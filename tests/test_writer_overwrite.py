#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""FileWriter and PyFileWriter must be able to overwrite an output file
from an earlier compile, not just create one fresh -- put_data stages the
new content under a temp name in the same directory, then moves it into
place. On Windows, os.rename refuses to replace an existing destination
(unlike POSIX, where it is an atomic replace), so a recompile of a MIB
already sitting in the destination directory would fail there specifically.
See the review discussion on pysnmp/pysmi#123.
"""

import os
import tempfile
import unittest

from pysmi.writer import FileWriter, PyFileWriter


class FileWriterOverwriteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.writer = FileWriter(self.dst).set_options(suffix=".json")

    def tearDown(self):
        self._tmp.cleanup()

    def testPutDataOverwritesAnExistingFile(self):
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.0"]}}')
        self.writer.put_data("IF-MIB", '{"meta": {"comments": ["Produced by pysmi-2.0.1"]}}')

        with open(os.path.join(self.dst, "IF-MIB.json")) as fp:
            self.assertIn("2.0.1", fp.read())

        self.assertEqual(["IF-MIB.json"], os.listdir(self.dst))


class PyFileWriterOverwriteTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dst = self._tmp.name
        self.writer = PyFileWriter(self.dst)
        self.writer.pyCompile = False

    def tearDown(self):
        self._tmp.cleanup()

    def testPutDataOverwritesAnExistingFile(self):
        self.writer.put_data("IF-MIB", "out = 1\n", comments=["Produced by pysmi-2.0.0"])
        self.writer.put_data("IF-MIB", "out = 2\n", comments=["Produced by pysmi-2.0.1"])

        with open(os.path.join(self.dst, "IF-MIB.py")) as fp:
            self.assertIn("out = 2", fp.read())

        self.assertEqual(["IF-MIB.py"], os.listdir(self.dst))


if __name__ == "__main__":
    unittest.main()
