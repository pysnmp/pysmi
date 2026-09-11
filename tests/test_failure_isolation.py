#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A module that fails takes down what imports it, and nothing else.

A corpus is compiled a namespace at a time, hundreds of modules per call, and
some of what vendors publish does not compile. What happens to the rest of the
call decides whether the corpus is usable: discarding a whole namespace because
one of its modules is defective loses hundreds of good modules that have no
relationship to the bad one.

So the unit of failure is the module, not the call. A module that fails is
omitted; a module that imports it is omitted too, transitively, because it
cannot be built without the symbols it names; everything else is written.

Whether a failure is *reported* as an error is a separate question from what
gets written, and is what ``ignoreErrors`` decides.
"""

import sys
import tempfile
import unittest
from pathlib import Path

from pysmi.codegen import PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader
from pysmi.searcher import StubSearcher
from pysmi.writer import CallbackWriter

#: Two OBJECT-TYPEs on the same descriptor. RFC 2578 section 3.1 requires a
#: descriptor to be unique within its module, so the symbol table refuses it.
BAD = """
BAD-MIB DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE, Integer32 FROM SNMPv2-SMI;
badObject OBJECT-TYPE
    SYNTAX Integer32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "First."
    ::= { 1 3 2 1 }
badObject OBJECT-TYPE
    SYNTAX Integer32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "Duplicate descriptor."
    ::= { 1 3 2 2 }
END
"""

#: Imports nothing but the SMI, so a failure elsewhere cannot reach it.
UNRELATED = """
UNRELATED-MIB DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE, Integer32 FROM SNMPv2-SMI;
unrelatedObject OBJECT-TYPE
    SYNTAX Integer32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "Nothing to do with the failure."
    ::= { 1 3 3 1 }
END
"""


def _importer(name, imported_from, symbol, arc):
    """A module importing *symbol* from *imported_from*."""
    return f"""
{name} DEFINITIONS ::= BEGIN
IMPORTS OBJECT-TYPE, Integer32 FROM SNMPv2-SMI
        {symbol} FROM {imported_from};
{name.split("-")[0].lower()}Object OBJECT-TYPE
    SYNTAX Integer32
    MAX-ACCESS read-only
    STATUS current
    DESCRIPTION "Depends on {imported_from}."
    ::= {{ 1 3 {arc} 1 }}
END
"""


class FailureIsolationTestCase(unittest.TestCase):
    """What one defective module costs the modules compiled alongside it."""

    def setUp(self):
        from tests import mibs

        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.src.mkdir()
        (self.src / "BAD-MIB").write_text(BAD)
        (self.src / "UNRELATED-MIB").write_text(UNRELATED)
        (self.src / "DIRECT-MIB").write_text(
            _importer("DIRECT-MIB", "BAD-MIB", "badObject", 4)
        )
        (self.src / "INDIRECT-MIB").write_text(
            _importer("INDIRECT-MIB", "DIRECT-MIB", "directObject", 5)
        )
        (self.src / "SNMPv2-SMI").write_text(mibs.SNMPV2_SMI)
        (self.src / "SNMPv2-TC").write_text(mibs.SNMPV2_TC)
        (self.src / "SNMPv2-CONF").write_text(
            "SNMPv2-CONF DEFINITIONS ::= BEGIN\nEND\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _compile(self, *names, **options):
        written = []
        compiler = MibCompiler(
            SmiStarParser(),
            PySnmpCodeGen(),
            CallbackWriter(lambda n, d, c: written.append(n)),
        )
        compiler.add_sources(FileReader(str(self.src)))
        compiler.add_searchers(StubSearcher(*PySnmpCodeGen.baseMibs))
        return compiler.compile(*names, **options), written

    def testTheDefectiveModuleFails(self):
        processed, _ = self._compile("BAD-MIB", "UNRELATED-MIB")
        self.assertEqual(processed["BAD-MIB"], "failed")

    def testAnUnrelatedModuleIsStillWritten(self):
        # The defect this file exists for: a namespace of several hundred good
        # modules was discarded because one of them was defective.
        processed, written = self._compile("BAD-MIB", "UNRELATED-MIB")
        self.assertEqual(processed["UNRELATED-MIB"], "compiled")
        self.assertIn("UNRELATED-MIB", written)

    def testAModuleImportingTheFailureIsOmitted(self):
        processed, written = self._compile("BAD-MIB", "DIRECT-MIB")
        self.assertNotEqual(processed["DIRECT-MIB"], "compiled")
        self.assertNotIn("DIRECT-MIB", written)

    def testTheOmissionIsTransitive(self):
        # INDIRECT-MIB does not name BAD-MIB; it names DIRECT-MIB, which does.
        processed, written = self._compile(
            "BAD-MIB", "DIRECT-MIB", "INDIRECT-MIB", "UNRELATED-MIB"
        )
        self.assertNotIn("INDIRECT-MIB", written)
        self.assertNotIn("DIRECT-MIB", written)
        self.assertIn("UNRELATED-MIB", written)

    def testIgnoreErrorsDoesNotChangeWhatIsWritten(self):
        # ignoreErrors says whether a failure is reported as an error, not
        # which modules survive it.
        strict, strictWritten = self._compile(
            "BAD-MIB", "DIRECT-MIB", "INDIRECT-MIB", "UNRELATED-MIB"
        )
        lax, laxWritten = self._compile(
            "BAD-MIB",
            "DIRECT-MIB",
            "INDIRECT-MIB",
            "UNRELATED-MIB",
            ignoreErrors=True,
        )
        self.assertEqual(sorted(strictWritten), sorted(laxWritten))
        self.assertEqual(strict["UNRELATED-MIB"], lax["UNRELATED-MIB"])

    def testACleanCallIsUnaffected(self):
        processed, written = self._compile("UNRELATED-MIB")
        self.assertEqual(processed["UNRELATED-MIB"], "compiled")
        self.assertIn("UNRELATED-MIB", written)


class MibDumpExitStatusTestCase(unittest.TestCase):
    """A defective MIB is an error unless the caller says otherwise.

    What gets written does not change between the two: the failed module and
    its dependents are omitted either way. What changes is whether the build
    reports success, which is the caller's decision when compiling MIBs it
    does not control.
    """

    def setUp(self):
        from tests import mibs

        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        (self.src / "BAD-MIB").write_text(BAD)
        (self.src / "UNRELATED-MIB").write_text(UNRELATED)
        (self.src / "SNMPv2-SMI").write_text(mibs.SNMPV2_SMI)
        (self.src / "SNMPv2-TC").write_text(mibs.SNMPV2_TC)
        (self.src / "SNMPv2-CONF").write_text(
            "SNMPv2-CONF DEFINITIONS ::= BEGIN\nEND\n"
        )

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        import io
        from contextlib import redirect_stderr, redirect_stdout

        from pysmi.scripts import mibdump

        out, err = io.StringIO(), io.StringIO()
        argv = sys.argv
        sys.argv = [
            "mibdump",
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "--rebuild",
            *extra,
            "BAD-MIB",
            "UNRELATED-MIB",
        ]
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

    def testADefectiveMibIsAnErrorByDefault(self):
        code, output = self._run()
        self.assertNotEqual(0, code, output)

    def testIgnoreErrorsReportsSuccess(self):
        code, output = self._run("--ignore-errors")
        self.assertEqual(0, code, output)

    def testTheGoodModuleIsWrittenEitherWay(self):
        for extra in ((), ("--ignore-errors",)):
            with self.subTest(extra=extra):
                for stale in self.dst.glob("*.py"):
                    stale.unlink()
                self._run(*extra)
                self.assertTrue((self.dst / "UNRELATED-MIB.py").exists())
                self.assertFalse((self.dst / "BAD-MIB.py").exists())


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
