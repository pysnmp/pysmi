#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""PackageReader fetches ASN.1 text bundled as package data, through
importlib.resources -- unlike FileReader, this works from inside a zipped
wheel, not just a real directory. See pysnmp/pysmi#113.
"""

import unittest

from pysmi import error
from pysmi.reader.package import PackageReader
from scripts.update_bundled_mibs import BUNDLED


class PackageReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.reader = PackageReader("pysmi.mibs.asn1")

    def testExactNameIsFound(self):
        info, data = self.reader.get_data("SNMPv2-SMI")
        self.assertEqual("SNMPv2-SMI", info.name)
        self.assertIn("SNMPv2-SMI DEFINITIONS", data)

    def testPathReportsThePackageAndFile(self):
        info, _data = self.reader.get_data("SNMPv2-SMI")
        self.assertEqual("package://pysmi.mibs.asn1/SNMPv2-SMI", info.path)
        self.assertEqual("SNMPv2-SMI", info.file)

    def testMtimeDefaultsToZero(self):
        # Bundled data has no meaningful mtime -- 0 makes every already
        # compiled output look at least as fresh, so a searcher's own
        # producer-marker check is what actually gates reuse.
        info, _data = self.reader.get_data("SNMPv2-SMI")
        self.assertEqual(0, info.mtime)

    def testMissingMibRaisesNotFound(self):
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            self.reader.get_data("NO-SUCH-MIB")

    def testNonexistentPackageRaisesNotFoundRatherThanCrashing(self):
        reader = PackageReader("no.such.package")
        with self.assertRaises(error.PySmiReaderFileNotFoundError):
            reader.get_data("SNMPv2-SMI")

    def testClearCacheIsAHarmlessNoOp(self):
        self.reader.clear_cache()
        info, _data = self.reader.get_data("SNMPv2-SMI")
        self.assertEqual("SNMPv2-SMI", info.name)

    def testEveryBundledMibIsReachableByItsOwnName(self):
        for mibname in BUNDLED:
            with self.subTest(mib=mibname):
                info, data = self.reader.get_data(mibname)
                self.assertEqual(mibname, info.name)
                self.assertIn(f"{mibname} DEFINITIONS", data)


if __name__ == "__main__":
    unittest.main()
