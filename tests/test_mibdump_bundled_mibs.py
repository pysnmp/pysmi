#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The ``--no-bundled-mibs`` mibdump flag, wired to MibCompiler's
``useBundledMibs`` constructor argument. See pysnmp/pysmi#113.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

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
        code, output = self._run()
        self.assertEqual(0, code, output)
        self.assertIn("Created/updated MIBs: TINY-TEST-MIB", output)

    def testNoBundledMibsFailsWithoutTheBaseMibs(self):
        code, output = self._run("--no-bundled-mibs")
        self.assertNotEqual(0, code, output)
        self.assertIn("TINY-TEST-MIB", output.split("Failed MIBs:")[1])


if __name__ == "__main__":
    unittest.main()
