#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for picking a reader out of a MIB source URL."""

import sys
import unittest

from pysmi import error
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.url import getReadersFromUrls
from pysmi.reader.zipreader import ZipReader


class GetReadersFromUrlsTestCase(unittest.TestCase):
    """A source URL selects the reader its scheme calls for."""

    def testWindowsPathIsNotAUrlScheme(self):
        """A drive letter is a path, not a scheme urlparse should honour."""
        (reader,) = getReadersFromUrls(r"C:\Users\me\mibs")

        self.assertIsInstance(reader, FileReader)
        self.assertIn(r"C:\Users\me\mibs", str(reader))

    def testWindowsPathWithForwardSlashes(self):
        """The same holds when the path is spelled with forward slashes."""
        (reader,) = getReadersFromUrls("C:/Users/me/mibs")

        self.assertIsInstance(reader, FileReader)
        self.assertIn("C:/Users/me/mibs", str(reader))

    def testWindowsZipPath(self):
        """A drive-lettered path ending in .zip still selects the zip reader."""
        (reader,) = getReadersFromUrls(r"C:\Users\me\mibs.zip")

        self.assertIsInstance(reader, ZipReader)

    def testWindowsPathKeepsPercentSign(self):
        """A path is taken as it stands, so %XX in a directory name survives."""
        (reader,) = getReadersFromUrls(r"C:\mibs%20dir")

        self.assertIn("%20", str(reader))

    def testPosixAbsolutePath(self):
        """An absolute POSIX path selects the file reader."""
        (reader,) = getReadersFromUrls("/home/me/mibs")

        self.assertIsInstance(reader, FileReader)
        self.assertIn("/home/me/mibs", str(reader))

    def testRelativePath(self):
        """A relative path selects the file reader."""
        (reader,) = getReadersFromUrls("mibs")

        self.assertIsInstance(reader, FileReader)

    def testFileUrl(self):
        """An explicit file:// URL selects the file reader."""
        (reader,) = getReadersFromUrls("file:///home/me/mibs")

        self.assertIsInstance(reader, FileReader)

    def testFileUrlEndingInZipStaysAFileReader(self):
        """file:// names a directory to read, even one called *.zip."""
        (reader,) = getReadersFromUrls("file:///home/me/mibs.zip")

        self.assertIsInstance(reader, FileReader)

    def testZipPath(self):
        """A bare path ending in .zip selects the zip reader."""
        (reader,) = getReadersFromUrls("mibs.zip")

        self.assertIsInstance(reader, ZipReader)

    def testUppercaseZipPath(self):
        """The .ZIP spelling selects the zip reader too."""
        (reader,) = getReadersFromUrls("mibs.ZIP")

        self.assertIsInstance(reader, ZipReader)

    def testHttpUrls(self):
        """http and https select the HTTP reader."""
        readers = getReadersFromUrls("http://example.com/@mib@", "https://example.com/@mib@")

        for reader in readers:
            self.assertIsInstance(reader, HttpReader)

    def testUnsupportedSchemeIsRejected(self):
        """A scheme no reader handles is still an error."""
        self.assertRaises(error.PySmiError, getReadersFromUrls, "ftp://example.com/mibs")

    def testReadersComeBackInOrder(self):
        """Readers are returned in the order their URLs were given."""
        readers = getReadersFromUrls("mibs", "mibs.zip", "http://example.com/@mib@")

        self.assertIsInstance(readers[0], FileReader)
        self.assertIsInstance(readers[1], ZipReader)
        self.assertIsInstance(readers[2], HttpReader)

    def testOptionsReachEveryReader(self):
        """Keyword options are applied to each reader built."""
        (reader,) = getReadersFromUrls("mibs", fuzzyMatching=False)

        self.assertFalse(reader.fuzzyMatching)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
