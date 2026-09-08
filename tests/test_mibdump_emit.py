#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""``--emit``: every format a build wants, from one read of the sources.

A build that publishes pysnmp with texts, pysnmp without, and JSON ran
mibdump three times and parsed everything three times. Parsing is about
three quarters of a pass, so the formats are worth producing together.
These pin what the option accepts, that a second destination is not
contaminated by the first's defaults, and that the output is the same as
running the formats separately -- which is the only reason to prefer it.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi.scripts import mibdump

IMPLICIT_BASE_MIBS = ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF")

EMIT_MIB = """TEST-EMIT-MIB DEFINITIONS ::= BEGIN

testEmitScalar OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "a scalar with a description worth carrying"
    ::= { 1 3 6 1 4 1 99997 1 }

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


class EmitSpecTestCase(unittest.TestCase):
    """What ``--emit`` accepts, read without running a compile."""

    def testAFormatAndADirectory(self):
        destination = mibdump._parse_emit("json:/writes/here")

        self.assertEqual("json", destination.format)
        self.assertEqual("/writes/here", destination.directory)
        self.assertFalse(destination.genTexts)

    def testTheTextsModifier(self):
        destination = mibdump._parse_emit("pysnmp+texts:/writes/here")

        self.assertEqual("pysnmp", destination.format)
        self.assertTrue(destination.genTexts)

    def testADirectoryIsOptional(self):
        """``--emit=json`` means what ``--destination-format=json`` alone means."""
        destination = mibdump._parse_emit("json")

        self.assertEqual("json", destination.format)
        self.assertIsNone(destination.directory)

    def testAnUnknownModifierIsRefused(self):
        with self.assertRaises(Exception) as raised:
            mibdump._parse_emit("json+html:/writes/here")

        self.assertIn("+html", str(raised.exception))

    def testTheSpellingRoundTrips(self):
        """The label the reports carry has to name the destination it ran."""
        for spec in ("json:/writes/here", "pysnmp+texts:/writes/here"):
            with self.subTest(spec=spec):
                self.assertEqual(spec, str(mibdump._parse_emit(spec)))


class EmitCompileTestCase(unittest.TestCase):
    """One invocation, several formats, each in its own directory."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

        self.sources = Path(self._tmp.name) / "asn1"
        self.sources.mkdir()
        (self.sources / "TEST-EMIT-MIB").write_text(EMIT_MIB)

        for name in IMPLICIT_BASE_MIBS:
            (self.sources / name).write_text(f"{name} DEFINITIONS ::= BEGIN\nEND\n")

        self.out = Path(self._tmp.name) / "out"
        self.borrowers = Path(self._tmp.name) / "borrowers"
        self.borrowers.mkdir()

    def _run(self, *args):
        return runMibdump(
            "--quiet",
            f"--mib-source=file://{self.sources}",
            f"--mib-borrower={self.borrowers}",
            "--no-python-compile",
            *args,
            "TEST-EMIT-MIB",
        )

    def testEachDestinationIsWritten(self):
        code, _ = self._run(
            f"--emit=pysnmp:{self.out / 'notexts'}",
            f"--emit=pysnmp+texts:{self.out / 'texts'}",
            f"--emit=json:{self.out / 'json'}",
        )

        self.assertEqual(0, code)
        self.assertTrue((self.out / "notexts" / "TEST-EMIT-MIB.py").is_file())
        self.assertTrue((self.out / "texts" / "TEST-EMIT-MIB.py").is_file())
        self.assertTrue((self.out / "json" / "TEST-EMIT-MIB.json").is_file())

    def testTheTextsModifierIsPerDestination(self):
        """Not a whole-run flag: one destination carries texts, the other not."""
        self._run(
            f"--emit=pysnmp:{self.out / 'notexts'}",
            f"--emit=pysnmp+texts:{self.out / 'texts'}",
        )

        described = "a scalar with a description worth carrying"

        self.assertNotIn(
            described, (self.out / "notexts" / "TEST-EMIT-MIB.py").read_text()
        )
        self.assertIn(described, (self.out / "texts" / "TEST-EMIT-MIB.py").read_text())

    def testAnEmittedFormatMatchesRunningItAlone(self):
        """The only reason to emit together is that it changes nothing else."""
        self._run(f"--emit=json:{self.out / 'together'}")

        runMibdump(
            "--quiet",
            f"--mib-source=file://{self.sources}",
            f"--mib-borrower={self.borrowers}",
            "--no-python-compile",
            "--destination-format=json",
            f"--destination-directory={self.out / 'alone'}",
            "TEST-EMIT-MIB",
        )

        self.assertEqual(
            (self.out / "alone" / "TEST-EMIT-MIB.json").read_text(),
            (self.out / "together" / "TEST-EMIT-MIB.json").read_text(),
        )

    def testOneDestinationDoesNotInheritAnothersDefaults(self):
        """json must not be compiled against pysnmp's stub list.

        Each format fills in the lists the caller left empty. Filling them in
        place would hand the second destination whatever the first defaulted
        to, and a JSON run stubbing pysnmp's base MIBs writes nothing for
        them -- so the count of files is the assertion.
        """
        self._run(
            f"--emit=pysnmp:{self.out / 'first'}",
            f"--emit=json:{self.out / 'second'}",
        )

        alone = Path(self._tmp.name) / "json-alone"
        runMibdump(
            "--quiet",
            f"--mib-source=file://{self.sources}",
            f"--mib-borrower={self.borrowers}",
            "--no-python-compile",
            "--destination-format=json",
            f"--destination-directory={alone}",
            "TEST-EMIT-MIB",
        )

        self.assertEqual(
            sorted(p.name for p in alone.iterdir()),
            sorted(p.name for p in (self.out / "second").iterdir()),
        )


class EmitRefusalTestCase(unittest.TestCase):
    """Combinations that would quietly do the wrong thing are refused."""

    def testEmitAndDestinationFormatTogether(self):
        code, output = runMibdump(
            "--emit=json:/writes/here", "--destination-format=json", "IF-MIB"
        )

        self.assertEqual(64, code)
        self.assertIn("cannot be combined", output)

    def testEmitAndDestinationDirectoryTogether(self):
        code, output = runMibdump(
            "--emit=json:/writes/here", "--destination-directory=/writes/here", "IF-MIB"
        )

        self.assertEqual(64, code)
        self.assertIn("cannot be combined", output)

    def testTwoDestinationsWritingToOneDirectory(self):
        """One would overwrite the other, which is never what was meant."""
        code, output = runMibdump(
            "--emit=json:/writes/here", "--emit=pysnmp:/writes/here", "IF-MIB"
        )

        self.assertEqual(64, code)
        self.assertIn("same directory", output)


if __name__ == "__main__":
    unittest.main()
