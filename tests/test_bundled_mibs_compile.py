#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Every MIB bundled in pysmi/mibs/asn1/ must compile against the bundle
itself -- this is what makes it useful as a fallback source at all. Runs as
part of the normal test suite, so a broken or incomplete addition to the
bundle is caught by ``pytest`` like any other regression, not only by the
network-dependent ``scripts/update_bundled_mibs.py --check``. See
pysnmp/pysmi#113.
"""

import re
import unittest
from importlib import resources

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
from scripts.update_bundled_mibs import BUNDLED, RFC_SOURCES

#: The LAST-UPDATED each RFC_SOURCES module should carry, per its RFC.
RFC_REVISIONS = {
    "ENTITY-MIB": "201304050000Z",
    "RMON2-MIB": "200605020000Z",
    "SNMP-TARGET-MIB": "200210140000Z",
}


class BundledMibsCompileTestCase(unittest.TestCase):
    def setUp(self):
        self.compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None), useBundledMibs=False
        )
        self.compiler.add_sources(PackageReader("pysmi.mibs.asn1"))

    def testEveryBundledMibCompilesAgainstTheBundleAlone(self):
        processed = self.compiler.compile(*BUNDLED, ignoreErrors=True)

        for mibname in BUNDLED:
            with self.subTest(mib=mibname):
                self.assertEqual("compiled", processed[mibname])

    def testTheBundleManifestHasNoDuplicates(self):
        self.assertEqual(len(BUNDLED), len(set(BUNDLED)))

    def testEveryModuleACodeGeneratorCallsABaseMibIsBundled(self):
        """The bundle is what makes a base MIB resolvable without a network.

        ``baseMibs`` is where pysmi says which modules are foundational, so a
        module named there but missing from the bundle is a compile that fails
        on an unreachable source for a MIB pysmi already knew it would need.
        PYSNMP-USM-MIB is the exception: it is pysnmp's own rather than an RFC,
        and pysnmp ships it.
        """
        for mibname in set(PySnmpCodeGen.baseMibs) | set(JsonCodeGen.baseMibs):
            if mibname in PySnmpCodeGen.fakeMibs or mibname == "PYSNMP-USM-MIB":
                continue

            with self.subTest(mib=mibname):
                self.assertIn(mibname, BUNDLED)

    def testEveryRfcPinnedMibIsTheRevisionItIsPinnedTo(self):
        """A pinned MIB carries the LAST-UPDATED of the RFC it came from.

        These three are in RFC_SOURCES because the pysnmp mirror serves an
        older revision of each; refreshing the bundle from the mirror by
        mistake would put that older text back, still compiling and still
        passing every other test here. The revision stamp is what tells the
        two apart, so it is asserted rather than assumed.
        """
        for mibname, lastUpdated in RFC_REVISIONS.items():
            with self.subTest(mib=mibname):
                self.assertIn(mibname, RFC_SOURCES)

                text = resources.files("pysmi.mibs.asn1").joinpath(mibname).read_text(errors="replace")
                found = re.search(r'LAST-UPDATED\s+"([0-9]+Z)"', text)

                self.assertIsNotNone(found, f"{mibname} has no LAST-UPDATED")
                self.assertEqual(lastUpdated, found.group(1))


if __name__ == "__main__":
    unittest.main()
