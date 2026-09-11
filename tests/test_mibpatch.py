#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The *mibpatch* tool over a tree of MIBs.

The tool exists so that a repair pysmi would otherwise make in memory, on every
run, becomes a file somebody can read. These tests run it the way an operator
would -- scan, review, apply -- and finish by compiling the patched tree under
``mibdump --strict-imports``, which is the state the whole thing is for: the
MIBs are correct on disk and the compiler repairs nothing.

``--check`` gets its own attention because it has to be right in two different
trees. A tree holding published text with patches beside it is stale when a
patch is missing or wrong. A tree that ``--apply`` has been run over holds the
repaired text, and its patches are *already applied* rather than surplus -- the
distinction the ALREADY_APPLIED status exists to make.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump, mibpatch
from tests import mibs
from tests.test_repair_imports import BROKEN, NO_IMPORTS_CLAUSE

GARBAGE = "this is not a MIB at all {{{\n"

CLEAN_MIB = """CLEAN-MIB DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE, Integer32, enterprises
        FROM SNMPv2-SMI;

fineObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION
        "An object relying on nothing the module left out."
    ::= { enterprises 99999 1 }

END
"""


def run(script, *argv):
    """Run a console script with *argv*, giving back its exit code and output."""
    out, err = io.StringIO(), io.StringIO()
    saved = sys.argv
    sys.argv = [script.__name__.rsplit(".", 1)[-1], *argv]

    try:
        with redirect_stdout(out), redirect_stderr(err):
            script.start()

    except SystemExit as exc:
        code = exc.code if exc.code is not None else 0

    else:
        code = 0

    finally:
        sys.argv = saved

    return code, out.getvalue() + err.getvalue()


class PatchTreeTestCase(unittest.TestCase):
    """A source tree with one module of each kind in it."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self.src = root / "mibs"
        self.patches = root / "patches"
        self.dst = root / "out"
        self.src.mkdir()

        for text in BROKEN.values():
            (self.src / text.split()[0]).write_text(text)

        (self.src / "REPAIR-NO-IMPORTS-MIB").write_text(NO_IMPORTS_CLAUSE)
        (self.src / "CLEAN-MIB").write_text(CLEAN_MIB)
        (self.src / "GARBAGE-MIB").write_text(GARBAGE)
        (self.src / "SNMPv2-SMI").write_text(mibs.SNMPV2_SMI)
        (self.src / "SNMPv2-TC").write_text(mibs.SNMPV2_TC)
        (self.src / "SNMPv2-MIB").write_text(mibs.SNMPV2_MIB)
        (self.src / "SNMPv2-CONF").write_text(
            "SNMPv2-CONF DEFINITIONS ::= BEGIN\nEND\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def patch(self, *extra):
        return run(
            mibpatch,
            f"--source={self.src}",
            f"--output-directory={self.patches}",
            *extra,
        )

    def written(self):
        return sorted(path.name for path in self.patches.glob("*.patch"))


class GenerateTestCase(PatchTreeTestCase):
    """Scanning a tree and writing out what it needs."""

    def testEveryRepairableModuleGetsAPatch(self):
        code, output = self.patch("--quiet")

        self.assertEqual(mibpatch.EX_OK, code, output)
        self.assertEqual(
            [
                "REPAIR-NO-IMPORTS-MIB.patch",
                "REPAIR-OID-MIB.patch",
                "REPAIR-SMI-TYPE-MIB.patch",
                "REPAIR-SNMPV2-MIB-MIB.patch",
                "REPAIR-TC-MIB.patch",
            ],
            self.written(),
        )

    def testAModuleNeedingNothingGetsNoPatch(self):
        self.patch("--quiet")

        self.assertNotIn("CLEAN-MIB.patch", self.written())

    def testAModuleThatDoesNotParseGetsNoPatchAndIsNamed(self):
        """It needs a hand-written one, and saying so is the whole report."""
        _, output = self.patch()

        self.assertNotIn("GARBAGE-MIB.patch", self.written())
        self.assertIn("has to be written by hand", output)
        self.assertIn("GARBAGE-MIB", output)

    def testTheReportNamesWhatEachRepairSupplies(self):
        _, output = self.patch()

        self.assertIn("REPAIR-TC-MIB (TruthValue from SNMPv2-TC)", output)

    def testTheSourcesAreNotTouchedWithoutApply(self):
        before = (self.src / "REPAIR-TC-MIB").read_text()
        self.patch("--quiet")

        self.assertEqual(before, (self.src / "REPAIR-TC-MIB").read_text())

    def testRunningItTwiceWritesTheSameBytes(self):
        self.patch("--quiet")
        first = {path.name: path.read_text() for path in self.patches.glob("*.patch")}
        self.patch("--quiet")

        self.assertEqual(
            first,
            {path.name: path.read_text() for path in self.patches.glob("*.patch")},
        )


class CheckTestCase(PatchTreeTestCase):
    """The CI gate, in both of the trees it has to be right in."""

    def testAnUnpatchedTreeWithNoPatchesIsStale(self):
        code, output = self.patch("--check")

        self.assertEqual(mibpatch.EX_STALE, code)
        self.assertIn("needs a patch, and none is written", output)

    def testATreeWithItsPatchesWrittenPasses(self):
        self.patch("--quiet")

        self.assertEqual(mibpatch.EX_OK, self.patch("--check", "--quiet")[0])

    def testAPatchThatIsNotTheRepairNeededIsStale(self):
        self.patch("--quiet")
        (self.patches / "REPAIR-TC-MIB.patch").write_text(
            "--- a/REPAIR-TC-MIB\n+++ b/REPAIR-TC-MIB\n@@ -1,1 +1,1 @@\n-x\n+y\n"
        )
        code, output = self.patch("--check")

        self.assertEqual(mibpatch.EX_STALE, code)
        self.assertIn("REPAIR-TC-MIB: its patch is not the repair it needs", output)

    def testAModuleThatGrewADefectIsStale(self):
        self.patch("--quiet")
        (self.src / "CLEAN-MIB").write_text(
            CLEAN_MIB.replace("OBJECT-TYPE, Integer32, enterprises", "OBJECT-TYPE")
        )
        code, output = self.patch("--check")

        self.assertEqual(mibpatch.EX_STALE, code)
        self.assertIn("CLEAN-MIB: needs a patch, and none is written", output)

    def testAnAppliedTreeStillPassesRatherThanCallingItsPatchesSurplus(self):
        """The repaired text needs no repair, but its patches are not stale."""
        self.patch("--apply", "--quiet")
        code, output = self.patch("--check", "--quiet")

        self.assertEqual(mibpatch.EX_OK, code, output)

    def testAPatchForAModuleFixedUpstreamIsStale(self):
        """The module needs nothing and the patch no longer describes its text."""
        self.patch("--quiet")
        (self.patches / "CLEAN-MIB.patch").write_text(
            "--- a/CLEAN-MIB\n+++ b/CLEAN-MIB\n@@ -1,1 +1,1 @@\n-gone\n+away\n"
        )
        code, output = self.patch("--check")

        self.assertEqual(mibpatch.EX_STALE, code)
        self.assertIn("CLEAN-MIB: needs no patch, but one is written", output)

    def testCheckWritesNothing(self):
        self.patch("--check", "--quiet")

        self.assertFalse(self.patches.exists())

    def testCheckAndApplyTogetherIsRefused(self):
        code, output = self.patch("--check", "--apply", "--quiet")

        self.assertEqual(mibpatch.EX_USAGE, code)
        self.assertIn("cannot --apply", output)


class ApplyTestCase(PatchTreeTestCase):
    """Writing the repair into the tree, which is what makes it durable."""

    def testTheSourceGainsTheImport(self):
        self.patch("--apply", "--quiet")

        self.assertIn("FROM SNMPv2-TC", (self.src / "REPAIR-TC-MIB").read_text())

    def testTheModuleNeedingNothingIsLeftAlone(self):
        self.patch("--apply", "--quiet")

        self.assertEqual(CLEAN_MIB, (self.src / "CLEAN-MIB").read_text())

    def testTheUnparseableModuleIsLeftAlone(self):
        self.patch("--apply", "--quiet")

        self.assertEqual(GARBAGE, (self.src / "GARBAGE-MIB").read_text())

    def testApplyingTwiceLeavesTheSameText(self):
        self.patch("--apply", "--quiet")
        once = (self.src / "REPAIR-TC-MIB").read_text()
        self.patch("--apply", "--quiet")

        self.assertEqual(once, (self.src / "REPAIR-TC-MIB").read_text())

    def testAnAppliedTreeDerivesNothingFurther(self):
        self.patch("--apply", "--quiet")
        _, output = self.patch()

        self.assertNotIn("Repairs derived", output)

    def testCrlfSourcesKeepTheirLineEndings(self):
        crlf = BROKEN["Opaque"].replace("\n", "\r\n")

        with (self.src / "REPAIR-SMI-TYPE-MIB").open("w", newline="") as target:
            target.write(crlf)

        self.patch("--apply", "--quiet")

        with (self.src / "REPAIR-SMI-TYPE-MIB").open("rb") as source:
            written = source.read()

        self.assertIn(b"\r\n", written)
        self.assertEqual(written.count(b"\n"), written.count(b"\r\n"))


class UsageTestCase(PatchTreeTestCase):
    """The things a command line gets wrong."""

    def testNoSourceIsAUsageError(self):
        code, output = run(mibpatch, "--output-directory=/tmp/nowhere")

        self.assertEqual(mibpatch.EX_USAGE, code)
        self.assertIn("pass --source", output)

    def testAMissingSourceDirectoryIsReported(self):
        code, output = run(mibpatch, f"--source={self.src / 'nope'}")

        self.assertEqual(mibpatch.EX_SOFTWARE, code)
        self.assertIn("no such source directory", output)

    def testHelpDocumentsEveryFlag(self):
        code, output = run(mibpatch, "--help")

        self.assertEqual(mibpatch.EX_OK, code)

        for flag in ("--source", "--output-directory", "--check", "--apply"):
            self.assertIn(flag, output)


class ReplacesTheRuntimeRepairTestCase(PatchTreeTestCase):
    """What the tool is for: a tree that compiles with the repair turned off."""

    #: Every module in the fixture that mibdump should be able to compile once
    #: the tree is patched. GARBAGE-MIB is not one -- it needs a human.
    COMPILABLE = (
        "REPAIR-SMI-TYPE-MIB",
        "REPAIR-TC-MIB",
        "REPAIR-OID-MIB",
        "REPAIR-SNMPV2-MIB-MIB",
        "REPAIR-NO-IMPORTS-MIB",
        "CLEAN-MIB",
    )

    def compile(self, mibname, *extra):
        return run(
            mibdump,
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "--rebuild",
            *extra,
            mibname,
        )

    def testTheBrokenModulesFailStrictlyBeforeTheTreeIsPatched(self):
        for mibname in self.COMPILABLE:
            if mibname == "CLEAN-MIB":
                continue

            with self.subTest(mib=mibname):
                code, output = self.compile(mibname, "--strict-imports")

                self.assertNotEqual(0, code, output)

    def testEveryModuleCompilesStrictlyOnceTheTreeIsPatched(self):
        self.patch("--apply", "--quiet")

        for mibname in self.COMPILABLE:
            with self.subTest(mib=mibname):
                code, output = self.compile(mibname, "--strict-imports")

                self.assertEqual(0, code, output)

    def testNothingIsRepairedAtRuntimeOnceTheTreeIsPatched(self):
        """The report's Repaired MIBs line is what a runtime repair looks like."""
        self.patch("--apply", "--quiet")

        for mibname in self.COMPILABLE:
            with self.subTest(mib=mibname):
                _, output = self.compile(mibname)

                self.assertIn("Repaired MIBs: \n", output)


if __name__ == "__main__":
    unittest.main()
