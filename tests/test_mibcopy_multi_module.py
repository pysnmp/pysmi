#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""One MIB file may define several modules, which vendor archives often do.

mibcopy names each destination file after the module it holds, because that is
how a reader finds a module later. A file defining several therefore has to be
copied under each of their names, and the revision of the module being replaced
has to be the one compared against.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibcopy

def module(name, oid, updated):
    """Return the text of a module carrying a LAST-UPDATED date."""
    return f"""{name} DEFINITIONS ::= BEGIN
IMPORTS MODULE-IDENTITY FROM SNMPv2-SMI;

{name.lower().replace("-", "")}Id MODULE-IDENTITY
    LAST-UPDATED "{updated}"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION "test"
    REVISION "{updated}"
    DESCRIPTION "test"
    ::= {{ 1 3 6 1 4 1 {oid} }}

END
"""


FIRST = module("FIRST-MIB", 99990, "202601010000Z")
SECOND = module("SECOND-MIB", 99991, "202601020000Z")


def runMibcopy(*args):
    """Run the mibcopy entry point, returning its exit code and output."""
    out, err = io.StringIO(), io.StringIO()
    argv = sys.argv
    sys.argv = ["mibcopy", *args]

    try:
        with redirect_stdout(out), redirect_stderr(err):
            mibcopy.start()
    except SystemExit as exc:
        code = exc.code
    else:
        code = 0
    finally:
        sys.argv = argv

    return code, out.getvalue() + err.getvalue()


class MibCopyMultiModuleTestCase(unittest.TestCase):
    """Every module in a source file reaches the destination."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        self.dst.mkdir()

    def copy(self):
        """Run mibcopy over the fixture directories."""
        return runMibcopy(str(self.src), str(self.dst))

    def testBothModulesOfOneFileAreCopied(self):
        """A file defining two modules lands under both names."""
        (self.src / "BOTH.mib").write_text(FIRST + "\n" + SECOND)

        code, output = self.copy()

        self.assertEqual(0, code)
        self.assertTrue((self.dst / "FIRST-MIB").exists())
        self.assertTrue((self.dst / "SECOND-MIB").exists(), "the second module was dropped")
        self.assertIn("(FIRST-MIB)", output)
        self.assertIn("(SECOND-MIB)", output)

    def testEachCopyHoldsTheWholeFile(self):
        """Both destinations are the source file, modules and all."""
        source = FIRST + "\n" + SECOND
        (self.src / "BOTH.mib").write_text(source)

        self.copy()

        for name in ("FIRST-MIB", "SECOND-MIB"):
            with self.subTest(name):
                self.assertEqual(source, (self.dst / name).read_text())

    def testReportCountsEveryModule(self):
        """The summary counts copies, so a two-module file counts twice."""
        (self.src / "BOTH.mib").write_text(FIRST + "\n" + SECOND)

        _, output = self.copy()

        self.assertIn("copied: 2", output)
        self.assertIn("failed: 0", output)

    def testSecondRunCopiesNothing(self):
        """Once both modules are in place, neither is replaced.

        This exercises the destination lookup: the file called SECOND-MIB holds
        FIRST-MIB first, so reading whichever module comes first would compare
        the wrong revision and copy again on every run.
        """
        (self.src / "BOTH.mib").write_text(FIRST + "\n" + SECOND)

        self.copy()
        _, output = self.copy()

        self.assertIn("copied: 0", output)
        self.assertIn("NOT COPIED", output)

    def testNewerRevisionOfOneModuleIsCopied(self):
        """A newer revision replaces the destination it belongs to."""
        (self.src / "BOTH.mib").write_text(FIRST + "\n" + SECOND)
        self.copy()

        newer = module("SECOND-MIB", 99991, "202606010000Z")
        (self.src / "BOTH.mib").write_text(FIRST + "\n" + newer)

        _, output = self.copy()

        self.assertIn("(SECOND-MIB)", output)
        self.assertIn("copied: 1", output)
        self.assertIn("202606", (self.dst / "SECOND-MIB").read_text())

    def testSingleModuleFileStillWorks(self):
        """The ordinary one-module case is unchanged."""
        (self.src / "ONLY.mib").write_text(FIRST)

        code, output = self.copy()

        self.assertEqual(0, code)
        self.assertTrue((self.dst / "FIRST-MIB").exists())
        self.assertIn("copied: 1", output)

    def testUnparsableFileIsReportedAndSkipped(self):
        """A file that holds no MIB fails on its own, without stopping the run."""
        (self.src / "BROKEN.mib").write_text("this is not a MIB at all\n")
        (self.src / "ONLY.mib").write_text(FIRST)

        code, output = self.copy()

        self.assertEqual(0, code)
        self.assertIn("FAILED", output)
        self.assertTrue((self.dst / "FIRST-MIB").exists())


if __name__ == "__main__":
    unittest.main()
