#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The ``--prune`` mibdump flag, wired to MibCompiler.prune (pysnmp/pysmi#61).

Unlike every other mibdump operation, ``--prune`` has something to do with
zero MIB-NAME arguments -- it acts on what the destination directory already
holds, not on names given on the command line -- so the usual "MIB modules
names not specified" guard has to let it through.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

IMPLICIT_BASE_MIBS = ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF")


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


class MibDumpPruneTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()

        (self.src / "MIB-A").write_text("MIB-A DEFINITIONS ::= BEGIN END\n")
        (self.src / "MIB-B").write_text("MIB-B DEFINITIONS ::= BEGIN END\n")

        for mib in IMPLICIT_BASE_MIBS:
            (self.src / mib).write_text(f"{mib} DEFINITIONS ::= BEGIN\nEND\n")

        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "MIB-A",
            "MIB-B",
        )
        self.assertEqual(0, code, output)

    def tearDown(self):
        self._tmp.cleanup()

    def _prune(self, *extra):
        return runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--prune",
            *extra,
        )

    def testPruneWithoutMibNamesIsAcceptedRatherThanRejectedAsUsageError(self):
        code, output = self._prune()
        self.assertEqual(0, code, output)

    def testARemovedSourceIsPrunedFromTheDestination(self):
        os.unlink(self.src / "MIB-B")

        code, output = self._prune()

        self.assertEqual(0, code, output)
        self.assertIn("MIBs pruned: MIB-B", output)
        self.assertTrue((self.dst / "MIB-A.py").exists())
        self.assertFalse((self.dst / "MIB-B.py").exists())

    def testDryRunReportsWithoutRemoving(self):
        os.unlink(self.src / "MIB-B")

        code, output = self._prune("--dry-run")

        self.assertEqual(0, code, output)
        self.assertIn("MIBs Would be pruned: MIB-B", output)
        self.assertTrue((self.dst / "MIB-B.py").exists())

    def testNothingIsPrunedWhileEverySourceStillExists(self):
        code, output = self._prune()

        self.assertEqual(0, code, output)
        self.assertIn("MIBs pruned: \r\n", output)
        self.assertTrue((self.dst / "MIB-A.py").exists())
        self.assertTrue((self.dst / "MIB-B.py").exists())

    def testWithoutPruneOrMibNamesUsageIsStillRejected(self):
        code, output = runMibdump(
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
        )
        self.assertNotEqual(0, code)
        self.assertIn("MIB modules names not specified", output)


if __name__ == "__main__":
    unittest.main()
