#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""scripts/update_bundled_mibs.py stages every fetch and the compile-verify
of the refreshed set before touching pysmi/mibs/asn1/ -- a network failure
partway through a fetch, or an upstream MIB that no longer compiles, must
leave the existing bundle exactly as it was rather than a mix of old and
new files. See the review discussion on pysnmp/pysmi#123.
"""

import pathlib
import tempfile
import unittest
from unittest import mock

from scripts import update_bundled_mibs

VALID_MIB = "TEST-MIB DEFINITIONS ::= BEGIN\nEND\n"
UNCOMPILABLE_MIB = "this is not valid ASN.1\n"


class UpdateBundledMibsAtomicityTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dest = pathlib.Path(self._tmp.name) / "asn1"
        self.dest.mkdir()

        self.bundled = ("ALPHA-MIB", "BETA-MIB")

        for mibname in self.bundled:
            (self.dest / mibname).write_bytes(VALID_MIB.encode())

        self._destPatch = mock.patch.object(update_bundled_mibs, "DEST", self.dest)
        self._bundledPatch = mock.patch.object(update_bundled_mibs, "BUNDLED", self.bundled)
        self._destPatch.start()
        self._bundledPatch.start()

    def tearDown(self):
        self._destPatch.stop()
        self._bundledPatch.stop()
        self._tmp.cleanup()

    def _existingBundleContents(self):
        return {mibname: (self.dest / mibname).read_bytes() for mibname in self.bundled}

    def testASuccessfulUpdateReplacesEveryFile(self):
        fresh = {mibname: f"-- fresh {mibname}\n{VALID_MIB}".encode() for mibname in self.bundled}

        with mock.patch.object(update_bundled_mibs, "fetch", side_effect=lambda name: fresh[name]):
            code = update_bundled_mibs.update()

        self.assertEqual(0, code)
        self.assertEqual(fresh, self._existingBundleContents())

    def testAFetchFailurePartwayLeavesTheExistingBundleUntouched(self):
        before = self._existingBundleContents()

        def flakyFetch(mibname):
            if mibname == self.bundled[-1]:
                raise TimeoutError("network unreachable")
            return f"-- fresh {mibname}\n{VALID_MIB}".encode()

        with (
            mock.patch.object(update_bundled_mibs, "fetch", side_effect=flakyFetch),
            self.assertRaises(TimeoutError),
        ):
            update_bundled_mibs.update()

        self.assertEqual(before, self._existingBundleContents())

    def testAnUncompilableRefreshLeavesTheExistingBundleUntouched(self):
        before = self._existingBundleContents()

        broken = {
            self.bundled[0]: UNCOMPILABLE_MIB.encode(),
            self.bundled[1]: VALID_MIB.encode(),
        }

        with mock.patch.object(update_bundled_mibs, "fetch", side_effect=lambda name: broken[name]):
            code = update_bundled_mibs.update()

        self.assertEqual(1, code)
        self.assertEqual(before, self._existingBundleContents())

    def testVerifyDefaultsToCheckingDestInPlace(self):
        self.assertEqual(0, update_bundled_mibs.verify())

    def testVerifyChecksTheGivenDirectoryNotDest(self):
        staging = pathlib.Path(self._tmp.name) / "staging"
        staging.mkdir()
        (staging / self.bundled[0]).write_bytes(UNCOMPILABLE_MIB.encode())
        (staging / self.bundled[1]).write_bytes(VALID_MIB.encode())

        self.assertEqual(1, update_bundled_mibs.verify(staging))
        # DEST's own (valid) copies are untouched by checking a different directory.
        self.assertEqual(0, update_bundled_mibs.verify())


if __name__ == "__main__":
    unittest.main()
