#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The bundled-MIB mibdump flags -- ``--no-bundled-mibs``, wired to
MibCompiler's ``useBundledMibs`` (pysnmp/pysmi#113), and
``--prefer-mib-source``, wired to ``preferConfiguredSources`` -- and what
mibdump reports when a configured source is passed over (pysnmp/pysmi#155).
"""

import importlib.resources
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

BUNDLED_PACKAGE = "pysmi.mibs.asn1"

#: A bundled module that is compiled rather than stubbed out, and carries a
#: MODULE-IDENTITY for the newest-wins rule to compare.
DATED = "SNMPv2-MIB"

#: The same, but with no MODULE-IDENTITY at all -- the case that can only be
#: settled by source order, and the one 13 of the 27 bundled modules are in.
UNDATED = "IPV6-TC"


def bundledText(mibname):
    return (importlib.resources.files(BUNDLED_PACKAGE) / mibname).read_text()


TARGET_MIB = """TINY-TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, Integer32, enterprises
        FROM SNMPv2-SMI;

tinyModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION "test"
    ::= { enterprises 99999 }

tinyScalar OBJECT-TYPE
    SYNTAX Integer32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "a scalar"
    ::= { tinyModule 1 }
END
"""


def runMibdump(*args):
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


class MibDumpBundledMibsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        (self.src / "TINY-TEST-MIB").write_text(TARGET_MIB)

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        return runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--destination-format=json",
            *extra,
            "TINY-TEST-MIB",
        )

    def testDefaultFallsBackToTheBundledBaseMibs(self):
        """A --mib-source with only the target MIB still resolves SNMPv2-SMI."""
        code, output = self._run()
        self.assertEqual(0, code, output)
        self.assertIn("TINY-TEST-MIB", output.split("Created/updated MIBs:")[1])
        self.assertTrue((self.dst / "TINY-TEST-MIB.json").is_file())

    def testNoBundledMibsFailsWithoutTheBaseMibs(self):
        code, output = self._run("--no-bundled-mibs")
        self.assertNotEqual(0, code, output)
        self.assertIn("TINY-TEST-MIB", output.split("Failed MIBs:")[1])


class MibDumpShadowedSourceReportTestCase(unittest.TestCase):
    """What mibdump says when a --mib-source copy is passed over.

    pysnmp/pysmi#155: the outcome was one line in a long summary and the rule
    behind it was nowhere, so a curated corpus compiling from pysmi's own copy
    looked like a defect rather than the documented precedence at work.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, mibname, *extra):
        return runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--destination-format=json",
            *extra,
            mibname,
        )

    def testAnOlderConfiguredCopyIsReportedWithTheRuleThatPassedItOver(self):
        older = re.sub(
            r'LAST-UPDATED\s+"\d+Z"',
            'LAST-UPDATED "199001010000Z"',
            bundledText(DATED),
            count=1,
        )
        (self.src / DATED).write_text(older)

        code, output = self._run(DATED)

        self.assertEqual(0, code, output)
        self.assertIn(f"WARNING: {DATED} resolved to pysmi's bundled copy", output)
        self.assertIn("decided by  newest MODULE-IDENTITY revision", output)
        self.assertIn("give your copy a newer MODULE-IDENTITY revision", output)

    def testAnUndatedModuleSaysThereWasNoRevisionToCompare(self):
        (self.src / UNDATED).write_text(bundledText(UNDATED) + "\n-- a local edit\n")

        code, output = self._run(UNDATED)

        self.assertEqual(0, code, output)
        self.assertIn(
            "decided by  source order; no MODULE-IDENTITY revision to compare", output
        )
        # Telling someone to ship a newer revision is no use for a module that
        # has none to carry; the flags are the only way out.
        self.assertIn(
            "to change   pass --prefer-mib-source, or --no-bundled-mibs", output
        )

    def testPreferMibSourceGivesAnUndatedModuleToTheConfiguredSource(self):
        (self.src / UNDATED).write_text(bundledText(UNDATED) + "\n-- a local edit\n")

        code, output = self._run(UNDATED, "--prefer-mib-source")

        self.assertEqual(0, code, output)
        self.assertIn(f"NOTE: {UNDATED} was found in more than one source", output)
        # os.path.join, not "/": the reader reports the path as the platform
        # spells it, which is a backslash on Windows.
        self.assertIn(f"used        file://{os.path.join(self.src, UNDATED)}", output)
        self.assertIn(f"passed over package://{BUNDLED_PACKAGE}/{UNDATED}", output)

    def testPreferMibSourceLeavesTheNewestRevisionRuleAlone(self):
        older = re.sub(
            r'LAST-UPDATED\s+"\d+Z"',
            'LAST-UPDATED "199001010000Z"',
            bundledText(DATED),
            count=1,
        )
        (self.src / DATED).write_text(older)

        code, output = self._run(DATED, "--prefer-mib-source")

        self.assertEqual(0, code, output)
        self.assertIn(f"WARNING: {DATED} resolved to pysmi's bundled copy", output)

    def testASecondRunStillSaysWhichCopyTheModuleResolvesTo(self):
        # The status of an up-to-date module is not the one that carries a
        # compile's metadata, so an incremental build used to report nothing
        # at all -- the run where a quiet override is least likely to be
        # noticed. See pysnmp/pysmi#155.
        (self.src / UNDATED).write_text(bundledText(UNDATED) + "\n-- a local edit\n")

        first, firstOutput = self._run(UNDATED)
        self.assertEqual(0, first, firstOutput)

        code, output = self._run(UNDATED)

        self.assertEqual(0, code, output)
        self.assertIn(f"Up to date MIBs: {UNDATED}", output)
        self.assertIn(f"WARNING: {UNDATED} resolved to pysmi's bundled copy", output)
        self.assertIn(
            "decided by  source order; no MODULE-IDENTITY revision to compare", output
        )

    def testTheCopyThatParsesIsTheCopyReportedAsUsed(self):
        # The first candidate is not always the one used: one that fails to
        # parse falls through to the next, and it is that one the report has
        # to name. --prefer-mib-source puts the broken copy first.
        (self.src / UNDATED).write_text("IPV6-TC DEFINITIONS ::= BEGIN\nnot asn.1\n")

        code, output = self._run(UNDATED, "--prefer-mib-source")

        self.assertEqual(0, code, output)
        self.assertIn(f"WARNING: {UNDATED} resolved to pysmi's bundled copy", output)
        self.assertIn(f"used        package://{BUNDLED_PACKAGE}/{UNDATED}", output)
        self.assertIn(f"passed over file://{os.path.join(self.src, UNDATED)}", output)
        # The whole fallback has to complete, not just be reported: the
        # module compiles from the copy that parsed, and the failure the
        # broken copy raised does not survive as its status.
        self.assertIn(f"Created/updated MIBs: {UNDATED}", output)
        self.assertNotIn(f"Failed MIBs: {UNDATED}", output)

    def testOneSourceOnlyReportsNothing(self):
        (self.src / "TINY-TEST-MIB").write_text(TARGET_MIB)

        code, output = self._run("TINY-TEST-MIB")

        self.assertEqual(0, code, output)
        self.assertNotIn("WARNING:", output)
        self.assertNotIn("NOTE:", output)


if __name__ == "__main__":
    unittest.main()
