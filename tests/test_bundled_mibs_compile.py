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

The manifest is asserted against the files on disk here too, since it is what
``--check`` refreshes from: an entry with no file, or a file no entry names,
would leave part of the bundle unverified against any publisher at all.
"""

import re
import sys
import unittest
from importlib import resources

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
from scripts.update_bundled_mibs import PATCHES, manifest

BUNDLED = sorted(manifest())

#: The LAST-UPDATED a few load-bearing modules should carry, per the RFC the
#: manifest pins them to.
PINNED_REVISIONS = {
    "ENTITY-MIB": (6933, "201304050000Z"),
    "RMON2-MIB": (4502, "200605020000Z"),
    "SNMP-TARGET-MIB": (3413, "200210140000Z"),
    "IF-MIB": (2863, "200006140000Z"),
}


class BundledMibsCompileTestCase(unittest.TestCase):
    def setUp(self):
        self.compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *a: None),
            useBundledMibs=False,
        )
        self.compiler.add_sources(PackageReader("pysmi.mibs.asn1"))
        # A malformed OID in one module can send the code generator round a
        # cycle; the default limit turns that into a bare RecursionError far
        # from the MIB that caused it. Restored in tearDown.
        self._recursionLimit = sys.getrecursionlimit()
        sys.setrecursionlimit(20000)

    def tearDown(self):
        sys.setrecursionlimit(self._recursionLimit)

    def testEveryBundledMibCompilesAgainstTheBundleAlone(self):
        processed = self.compiler.compile(*BUNDLED, ignoreErrors=True)

        # Every name the compile touched, not only the ones asked for. A
        # bundled module importing something the bundle does not carry leaves
        # that name "missing" while the module importing it still reports
        # "compiled", so asserting only over BUNDLED would pass a bundle with a
        # dangling import in it -- which is how GBOND-MIB came to be bundled
        # needing an IANA-GBOND-TC-MIB nothing provided.
        for mibname, status in sorted(processed.items()):
            with self.subTest(mib=mibname):
                self.assertEqual("compiled", status)

    def testTheBundleIsImportClosed(self):
        """No bundled module may import one the bundle does not carry.

        The compile above catches this too, but only once something fails to
        resolve at code-generation time. Reading the IMPORTS clauses through
        pysmi's own parser says it directly, and names the importer -- which is
        what someone adding a module to the manifest needs to see.
        """
        parser = SmiV1CompatParser()
        outside = {}

        for mibname in BUNDLED:
            text = (
                resources.files("pysmi.mibs.asn1")
                .joinpath(mibname)
                .read_text(errors="replace")
            )
            _info, symtable = SymtableCodeGen().gen_code(parser.parse(text)[0], {})

            for imported in symtable.get("imports", {}):
                if imported not in set(BUNDLED):
                    outside.setdefault(imported, []).append(mibname)

        self.assertEqual(
            {},
            outside,
            "bundled modules import these, which the bundle does not carry",
        )

    def testTheManifestAndThePackageHoldTheSameModules(self):
        onDisk = {
            entry.name
            for entry in resources.files("pysmi.mibs.asn1").iterdir()
            if entry.is_file() and not entry.name.startswith("__")
        }

        self.assertEqual(set(BUNDLED), onDisk)

    def testEveryManifestEntryNamesASourceItCanBeRefetchedFrom(self):
        for mibname, entry in sorted(manifest().items()):
            with self.subTest(mib=mibname):
                if entry["source"] == "rfc":
                    self.assertIsInstance(entry["rfc"], int)
                elif entry["source"] == "local":
                    # Nothing to re-fetch, so the manifest owes an explanation.
                    self.assertTrue(entry.get("reason"))
                elif entry["source"] == "ieee802.1":
                    # No URL: the source is whatever the IEEE directory
                    # currently publishes, and this records what we took.
                    self.assertRegex(entry["revision"], r"^\d{12}$")
                else:
                    self.assertTrue(entry["url"].startswith("https://"))

    def testEveryPatchedEntryHasAPatchFileAndAStatedReason(self):
        """A patch is a deviation from the publisher's text, so it is spelled out.

        The bundle's whole claim is that its bytes come from a publisher. Where
        that is not quite true the manifest has to say so and the patch has to
        be readable, or the claim quietly stops being checkable.
        """
        patched = {
            name: entry for name, entry in manifest().items() if "patch" in entry
        }

        self.assertTrue(patched, "the patch machinery has nothing exercising it")

        for mibname, entry in sorted(patched.items()):
            with self.subTest(mib=mibname):
                self.assertTrue(entry.get("reason"))
                self.assertTrue((PATCHES / entry["patch"]).is_file())

        onDisk = {path.name for path in PATCHES.iterdir() if path.suffix == ".patch"}
        self.assertEqual({entry["patch"] for entry in patched.values()}, onDisk)

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

    def testLoadBearingMibsAreTheRevisionTheirRfcPinsThemTo(self):
        """A pinned MIB carries the LAST-UPDATED of the RFC it came from.

        Mirrors serve older revisions of all four of these -- an ENTITY-MIB
        eight years superseded, an RMON2-MIB predating RFC 4502. Refreshing the
        bundle from one by mistake would put that older text back, still
        compiling and still passing every other test here. The revision stamp
        is what tells the two apart, so it is asserted rather than assumed.
        """
        modules = manifest()

        for mibname, (rfc, lastUpdated) in PINNED_REVISIONS.items():
            with self.subTest(mib=mibname):
                self.assertEqual("rfc", modules[mibname]["source"])
                self.assertEqual(rfc, modules[mibname]["rfc"])

                text = (
                    resources.files("pysmi.mibs.asn1")
                    .joinpath(mibname)
                    .read_text(errors="replace")
                )
                found = re.search(r'LAST-UPDATED\s+"([0-9]+Z)"', text)

                self.assertIsNotNone(found, f"{mibname} has no LAST-UPDATED")
                self.assertEqual(lastUpdated, found.group(1))


if __name__ == "__main__":
    unittest.main()
