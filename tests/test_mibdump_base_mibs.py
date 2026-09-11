#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A JSON destination directory has to resolve its own imports.

Nothing supplies a JSON SNMPv2-TC the way pysnmp supplies a Python one, so
stubbing the base MIBs out of the output left every JSON tree pysmi has ever
produced referring to a DisplayString that was not in it. mibdump now compiles
them from the bundled copies instead, and ``--no-base-mibs`` puts the stubs
back. See pysnmp/pysmi#161.
"""

import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

TARGET_MIB = """SELF-CONTAINED-TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, enterprises
        FROM SNMPv2-SMI
    DisplayString
        FROM SNMPv2-TC
    ifIndex
        FROM IF-MIB;

selfContainedModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION "test"
    ::= { enterprises 99999 }

selfContainedScalar OBJECT-TYPE
    SYNTAX DisplayString
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "a scalar"
    ::= { selfContainedModule 1 }
END
"""

#: Modules an emitted document may import without a file of their own. The
#: ASN1 pseudo-modules name built-in types every code generator supplies.
BUILT_IN = frozenset({"ASN1", "ASN1-ENUMERATION", "ASN1-REFINEMENT"})


def runMibdump(*args):
    """Run mibdump in-process and hand back its exit code and whole report."""
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["mibdump", *args]

    try:
        with redirect_stdout(out), redirect_stderr(err):
            mibdump.start()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    finally:
        sys.argv = argv

    return code, out.getvalue() + err.getvalue()


class MibDumpBaseMibsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        (self.src / "SELF-CONTAINED-TEST-MIB").write_text(TARGET_MIB)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra, fmt="json"):
        """Compile the test MIB, asserting the run succeeded, and return the report."""
        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            f"--destination-format={fmt}",
            *extra,
            "SELF-CONTAINED-TEST-MIB",
        )
        self.assertEqual(0, code, output)
        return output

    def testJsonOutputCarriesTheBaseMibsItImports(self):
        """The modules the compiled MIB imports are written, not stubbed."""
        self._run()

        for mibname in ("SNMPv2-SMI", "SNMPv2-TC"):
            with self.subTest(mib=mibname):
                self.assertTrue((self.dst / f"{mibname}.json").is_file())

    def testEveryImportOfAnEmittedJsonDocumentResolvesInTheSameDirectory(self):
        """The whole point: the destination directory needs nothing else."""
        self._run()

        emitted = {path.stem for path in self.dst.glob("*.json")}

        for path in sorted(self.dst.glob("*.json")):
            imports = json.loads(path.read_text()).get("imports", {})

            for imported in imports:
                if imported == "class" or imported in BUILT_IN:
                    continue

                with self.subTest(mib=path.stem, imports=imported):
                    self.assertIn(imported, emitted)

    def testTheReportNamesTheBaseMibsItMayWriteOut(self):
        """A run says which base MIBs are in play, rather than leaving it to be found.

        The line is the eligible set, not the subset this run reaches: it is
        printed with the rest of the configuration, before anything is
        compiled. Which of them were written is on the created/updated line.
        """
        output = self._run()

        line = output.split("Base MIBs eligible to be written out from the bundle:")[
            1
        ].splitlines()[0]

        created = output.split("Created/updated MIBs:")[1].splitlines()[0]

        # SNMPv2-TC is eligible and this run reaches it; RFC1213-MIB is
        # eligible and this run does not.
        self.assertIn("SNMPv2-TC", line)
        self.assertIn("SNMPv2-TC", created)

        self.assertIn("RFC1213-MIB", line)
        self.assertNotIn("RFC1213-MIB", created)
        self.assertFalse((self.dst / "RFC1213-MIB.json").exists())

    def testNoBaseMibsLeavesThemStubbedOut(self):
        """--no-base-mibs restores the behaviour of releases before 2.2."""
        output = self._run("--no-base-mibs")

        self.assertIn(
            "Base MIBs eligible to be written out from the bundle: none", output
        )
        self.assertFalse((self.dst / "SNMPv2-TC.json").exists())
        self.assertTrue((self.dst / "SELF-CONTAINED-TEST-MIB.json").is_file())

    def testAnExplicitMibStubIsStillHonoured(self):
        """--mib-stub replaces the default list, base MIBs and all."""
        output = self._run("--mib-stub=SNMPv2-TC")

        self.assertIn(
            "Base MIBs eligible to be written out from the bundle: none", output
        )
        self.assertFalse((self.dst / "SNMPv2-TC.json").exists())

    def testPysnmpOutputNeverCarriesTheBaseMibs(self):
        """pysnmp implements these; a generated copy would shadow it."""
        output = self._run("--no-python-compile", fmt="pysnmp")

        self.assertIn(
            "Base MIBs eligible to be written out from the bundle: none", output
        )
        self.assertFalse((self.dst / "SNMPv2-TC.py").exists())
        self.assertTrue((self.dst / "SELF-CONTAINED-TEST-MIB.py").is_file())

    def testACustomMibStubLetsAPysnmpBaseMibThrough(self):
        """The default stub list is what holds them back, not the pysnmp target.

        --mib-stub replaces that list rather than adding to it, so a base MIB
        the replacement omits is compiled and written like any other module --
        on the pysnmp target too, where the result can shadow the
        implementation pysnmp loads. Documented rather than prevented: the
        caller asked for exactly this list.
        """
        self._run("--no-python-compile", "--mib-stub=NOTHING-AT-ALL", fmt="pysnmp")

        self.assertTrue((self.dst / "SNMPv2-CONF.py").is_file())

    def testNoBundledMibsStillBitesAlongsideACustomMibStub(self):
        """The two flags are separate levers, and --mib-stub disarms only one.

        --no-base-mibs is read only where the default stub list is built, so
        --mib-stub makes it moot. --no-bundled-mibs is not: it decides whether
        the bundle is a source at all, so a base MIB the replacement list
        leaves unstubbed has nowhere offline to come from.
        """
        _, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--destination-format=json",
            "--mib-stub=NOTHING-AT-ALL",
            "--no-bundled-mibs",
            "--ignore-errors",
            "SELF-CONTAINED-TEST-MIB",
        )

        self.assertIn("SNMPv2-SMI", output.split("Missing source MIBs:")[1])
        self.assertFalse((self.dst / "SNMPv2-SMI.json").exists())

    def testDroppingTheBundleDropsTheBaseMibsWithIt(self):
        """They are written out from the bundled copies or not at all.

        Without the bundle there is nowhere offline to compile them from, so
        this run does not get as far as an output directory -- the report
        still has to say the base MIBs are not coming.
        """
        _, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--destination-format=json",
            "--no-bundled-mibs",
            "--ignore-errors",
            "SELF-CONTAINED-TEST-MIB",
        )

        self.assertIn(
            "Base MIBs eligible to be written out from the bundle: none", output
        )
        self.assertFalse((self.dst / "SNMPv2-TC.json").exists())


if __name__ == "__main__":
    unittest.main()
