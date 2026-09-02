#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for running where the Unix-only ``pwd`` module is absent."""

import json
import os
import subprocess
import sys
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV2Parser
from pysmi.reader import CallbackReader
from pysmi.writer import CallbackWriter

# Self-contained, so compiling it needs nothing fetched from anywhere.
MIB_TEXT = "TEST-MIB DEFINITIONS ::= BEGIN\ntestMib OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 99999 }\nEND"

# Hide ``pwd`` and ``os.getuid`` the way Windows does, then run the body.
WINDOWS_LIKE_PRELUDE = '''
import sys


class Blocker:
    """Refuse to supply ``pwd``, as an import system without it would."""

    def find_spec(self, name, path=None, target=None):
        if name == "pwd":
            raise ImportError("No module named 'pwd'")
        return None


sys.meta_path.insert(0, Blocker())
sys.modules.pop("pwd", None)

import os

if hasattr(os, "getuid"):
    del os.getuid

__BODY__
'''


def runWithoutPwd(body: str) -> "subprocess.CompletedProcess[str]":
    """Run *body* in a subprocess where importing ``pwd`` fails."""
    return subprocess.run(
        [sys.executable, "-c", WINDOWS_LIKE_PRELUDE.replace("__BODY__", body)],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        check=False,
    )


def compileTestMib() -> dict:
    """Compile the sample MIB and return the JSON document produced."""
    written = {}

    def read(mibname, context):
        if mibname != "TEST-MIB":
            raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=None)
        return MIB_TEXT

    compiler = MibCompiler(
        SmiV2Parser(),
        JsonCodeGen(),
        CallbackWriter(lambda mibname, data, ctx: written.update({mibname: data})),
    )
    compiler.addSources(CallbackReader(read))

    # The base MIBs cannot be reached, and their absence would otherwise roll
    # back the one MIB that did compile.
    compiler.compile("TEST-MIB", ignoreErrors=True)

    return json.loads(written["TEST-MIB"])


class WindowsCompatTestCase(unittest.TestCase):
    """PySMI must be importable and usable without Unix-only modules."""

    def testCompilerImportsWithoutPwd(self):
        """Importing the compiler does not need ``pwd``."""
        result = runWithoutPwd("import pysmi.compiler")

        self.assertEqual(result.returncode, 0, f"import failed without pwd:\n{result.stderr}")

    def testScriptsImportWithoutPwd(self):
        """Both console scripts import without ``pwd``."""
        result = runWithoutPwd("import pysmi.scripts.mibdump, pysmi.scripts.mibcopy")

        self.assertEqual(result.returncode, 0, f"console scripts failed to import:\n{result.stderr}")

    def testMibdumpRunsWithoutPwd(self):
        """The mibdump entry point runs without ``pwd``."""
        result = runWithoutPwd(
            "import sys\n"
            "sys.argv = ['mibdump', '--help']\n"
            "from pysmi.scripts.mibdump import start\n"
            "try:\n"
            "    start()\n"
            "except SystemExit:\n"
            "    pass\n"
        )

        self.assertEqual(result.returncode, 0, f"mibdump failed without pwd:\n{result.stderr}")


class GeneratedHeaderTestCase(unittest.TestCase):
    """Generated MIBs must not be stamped with who or where built them.

    The host and user name were the only reason the compiler needed ``pwd``,
    and neither tells a reader of the generated MIB anything useful.
    """

    def testHeaderNamesNoHostOrUser(self):
        """No host, platform or user name appears in the header."""
        comments = " ".join(compileTestMib()["meta"]["comments"])

        self.assertNotIn("On host", comments)
        self.assertNotIn("by user", comments)

    def testHeaderLeaksNoIdentifyingValues(self):
        """The identifying values themselves do not appear either."""
        comments = " ".join(compileTestMib()["meta"]["comments"])

        if hasattr(os, "uname"):
            self.assertNotIn(os.uname()[1], comments)

        if hasattr(os, "getuid"):
            import pwd

            self.assertNotIn(pwd.getpwuid(os.getuid()).pw_name, comments)

    def testHeaderKeepsSourceAndVersion(self):
        """What is useful about the header survives."""
        comments = " ".join(compileTestMib()["meta"]["comments"])

        self.assertIn("ASN.1 source", comments)
        self.assertIn("Produced by pysmi", comments)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
