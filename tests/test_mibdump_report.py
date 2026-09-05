#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for the summary mibdump prints after a run.

The report lines are assembled from several joins over the status dictionary
and are the only place those branches are exercised, so they are pinned here
rather than left to manual inspection.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

# The compiler resolves these three whether or not a MIB names them, so the
# source directory has to hold something for each. Empty modules are enough:
# nothing here refers to a symbol out of them.
IMPLICIT_BASE_MIBS = ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF")

STANDALONE_MIB = """TEST-REPORT-MIB DEFINITIONS ::= BEGIN

testScalar OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "a scalar"
    ::= { 1 3 6 1 4 1 99998 1 }

END
"""


def runMibdump(*args):
    """Run the mibdump entry point, returning its exit code and output."""
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


class MibDumpReportTestCase(unittest.TestCase):
    """The report renders every branch of its status summary."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        (self.src / "TEST-REPORT-MIB").write_text(STANDALONE_MIB)

        for mib in IMPLICIT_BASE_MIBS:
            (self.src / mib).write_text(f"{mib} DEFINITIONS ::= BEGIN\nEND\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        return runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            *extra,
            "TEST-REPORT-MIB",
        )

    def testCompiledMibIsReported(self):
        """A MIB that compiles is named on the created/updated line."""
        code, output = self._run("--rebuild")

        self.assertEqual(0, code, output)
        self.assertIn("Created/updated MIBs: TEST-REPORT-MIB", output)

    def testDryRunReportsWhatWouldHappen(self):
        """--dry-run switches the created and borrowed lines to the future tense."""
        code, output = self._run("--dry-run")

        self.assertEqual(0, code, output)
        self.assertIn("Would be created/updated MIBs: TEST-REPORT-MIB", output)
        self.assertIn("Pre-compiled MIBs Would be borrowed:", output)

    def testUpToDateMibIsReportedSeparately(self):
        """Recompiling without --rebuild reports the MIB as untouched."""
        self._run("--rebuild")
        code, output = self._run()

        self.assertEqual(0, code, output)

        upToDate = next(line for line in output.splitlines() if line.startswith("Up to date MIBs:"))

        self.assertIn("TEST-REPORT-MIB", upToDate)
        self.assertNotIn("Created/updated MIBs: TEST-REPORT-MIB", output)

    def testMissingMibIsReported(self):
        """A MIB with no source is named on the missing line."""
        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "NO-SUCH-MIB",
        )

        self.assertNotEqual(0, code)
        self.assertIn("Missing source MIBs: NO-SUCH-MIB", output)

    def testVerboseHeaderNamesTheConfiguration(self):
        """The preamble echoes the source and destination that were used."""
        _code, output = self._run("--rebuild")

        self.assertIn(f"Source MIB repositories: {self.src}", output)
        self.assertIn(f"Compiled MIBs destination directory: {self.dst}", output)

    def testACopyInMoreThanOneSourceIsReported(self):
        """The shadowed line names the copy used and the one passed over."""
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        (other / "TEST-REPORT-MIB").write_text(STANDALONE_MIB.replace("a scalar", "the other copy"))

        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--mib-source={other}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "--rebuild",
            "TEST-REPORT-MIB",
        )

        self.assertEqual(0, code, output)
        self.assertIn("MIBs found in more than one source: TEST-REPORT-MIB", output)
        self.assertIn(str(other), output)

    def testStrictSourcesFailsOnSuchACopy(self):
        """--strict-sources turns that report line into a failure."""
        other = Path(self._tmp.name) / "other"
        other.mkdir()
        (other / "TEST-REPORT-MIB").write_text(STANDALONE_MIB.replace("a scalar", "the other copy"))

        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--mib-source={other}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "--rebuild",
            "--strict-sources",
            "TEST-REPORT-MIB",
        )

        self.assertNotEqual(0, code)
        self.assertIn("Failed MIBs: TEST-REPORT-MIB", output)

    def testUsageMessageRenders(self):
        """--help fills the usage template in, including the debug categories."""
        code, output = runMibdump("--help")

        self.assertEqual(0, code)
        self.assertIn("Usage: mibdump [--help]", output)
        self.assertIn("--debug=<", output)
        self.assertNotIn("{}", output)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
