#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Repairing a MIB that uses an SMIv2 base symbol it never imported.

RFC 2578 Section 3.2 requires a module to name in IMPORTS every symbol it
refers to and does not define. Plenty of vendor MIBs do not, and for a symbol
one of the SMIv2 base modules exports the import that was meant is not in
doubt -- there is exactly one module it can have come from.

Repair is opt-in, so the strict reading stays the default: without
``repairImports`` every module here fails to compile, which is what these
tests assert first. See pysnmp/pysmi#61.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from pysmi import error
from pysmi.codegen.base import SMI_BASE_EXPORTS
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.scripts import mibdump
from tests import mibs
from tests.harness import parse, render_json, render_source, symbol_table

DEPS = (mibs.SNMPV2_SMI, mibs.SNMPV2_TC)


def module(name, imports, syntax, oid):
    """A one-object MIB, so that what it omits from IMPORTS is the only variable."""
    return f"""{name} DEFINITIONS ::= BEGIN

IMPORTS
    {imports}
        FROM SNMPv2-SMI;

brokenObject OBJECT-TYPE
    SYNTAX      {syntax}
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION
        "An object relying on a symbol the module never imports."
    ::= {{ {oid} }}

END
"""


#: One module per kind of omission, with the symbol each one leaves out.
#:
#: The three cover the two ways an unresolved symbol surfaces in the symbol
#: table: as the unknown parent of a symbol (the syntax cases), and as the
#: unknown parent of an OID (the registration case).
BROKEN = {
    "Opaque": module("REPAIR-SMI-TYPE-MIB", "OBJECT-TYPE", "Opaque", "1 3 1"),
    "TruthValue": module("REPAIR-TC-MIB", "OBJECT-TYPE", "TruthValue", "1 3 2"),
    "enterprises": module("REPAIR-OID-MIB", "OBJECT-TYPE", "Integer32", "enterprises 99999 1"),
}

#: A module with no IMPORTS clause at all -- the parse tree carries None there
#: rather than an empty mapping, so the repair has nothing to append to.
NO_IMPORTS_CLAUSE = """REPAIR-NO-IMPORTS-MIB DEFINITIONS ::= BEGIN

brokenObject OBJECT-TYPE
    SYNTAX      PhysAddress
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION
        "An object in a module that names no IMPORTS clause whatsoever."
    ::= { enterprises 99999 2 }

END
"""


class StrictByDefaultTestCase(unittest.TestCase):
    """Nothing is repaired unless the caller asks for it."""

    def testEveryBrokenModuleFailsToCompile(self):
        for symbol, source in BROKEN.items():
            with self.subTest(symbol=symbol), self.assertRaises(error.PySmiSemanticError):
                symbol_table(source, deps=DEPS)

    def testTheModuleWithNoImportsClauseFailsToCompile(self):
        with self.assertRaises(error.PySmiSemanticError):
            symbol_table(NO_IMPORTS_CLAUSE, deps=DEPS)


class RepairTestCase(unittest.TestCase):
    """With repair on, the canonical import is supplied and reported."""

    def testTheSymbolIsImportedFromTheModuleThatExportsIt(self):
        for symbol, source in BROKEN.items():
            with self.subTest(symbol=symbol):
                _, name, table = symbol_table(source, deps=DEPS, repairImports=True)
                self.assertEqual(table[name]["_symtable_repaired"], {symbol: SMI_BASE_EXPORTS[symbol]})

    def testAModuleThatImportsEverythingItUsesIsNotTouched(self):
        source = module("REPAIR-CLEAN-MIB", "OBJECT-TYPE, Opaque", "Opaque", "1 3 3")
        _, name, table = symbol_table(source, deps=DEPS, repairImports=True)
        self.assertEqual(table[name]["_symtable_repaired"], {})

    def testAMissingImportsClauseIsRepairedToo(self):
        _, name, table = symbol_table(NO_IMPORTS_CLAUSE, deps=DEPS, repairImports=True)
        self.assertEqual(
            table[name]["_symtable_repaired"],
            {"PhysAddress": "SNMPv2-TC", "enterprises": "SNMPv2-SMI"},
        )

    def testTheRepairedModuleIsListedAsImported(self):
        # The compiler queues for compilation whatever a module imports, so a
        # repair that reaches into a module the MIB never named has to say so
        # here or the dependency is never fetched.
        _, _, table = symbol_table(NO_IMPORTS_CLAUSE, deps=DEPS, repairImports=True)
        mibInfo, _ = SymtableCodeGen().gen_code(parse(NO_IMPORTS_CLAUSE), table, repairImports=True)
        self.assertEqual(mibInfo.imported, ("SNMPv2-CONF", "SNMPv2-SMI", "SNMPv2-TC"))


class RepairedSourceTestCase(unittest.TestCase):
    """The repair reaches the rendered module, not just the symbol table."""

    def testThePySnmpBackendImportsTheRepairedSymbol(self):
        source = render_source(BROKEN["Opaque"], deps=DEPS, repairImports=True)
        imported = next(line for line in source.splitlines() if '"SNMPv2-SMI"' in line)
        self.assertIn('"Opaque"', imported)
        self.assertIn("brokenObject = MibScalar((1, 3, 1), Opaque())", source)

    def testThePySnmpBackendResolvesARepairedOid(self):
        source = render_source(BROKEN["enterprises"], deps=DEPS, repairImports=True)
        self.assertIn("brokenObject = MibScalar((1, 3, 6, 1, 4, 1, 99999, 1)", source)

    def testTheJsonBackendResolvesTheRepairedSyntax(self):
        doc = render_json(BROKEN["TruthValue"], deps=DEPS, repairImports=True)
        self.assertEqual(doc["brokenObject"]["syntax"]["type"], "TruthValue")


class SmiBaseExportsTestCase(unittest.TestCase):
    """What the table is allowed to claim.

    A wrong entry here silently rewrites a MIB's meaning, so the table is
    pinned to the three modules RFC 2578, RFC 2579 and RFC 2580 define, and to
    symbols those modules actually export.
    """

    def testEverySymbolComesFromAnSmiV2BaseModule(self):
        self.assertEqual(
            set(SMI_BASE_EXPORTS.values()),
            {"SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF"},
        )

    def testTheConformanceMacrosAreAllThereIsInSnmpV2Conf(self):
        # RFC 2580 defines exactly these four macros and nothing else.
        self.assertEqual(
            {sym for sym, mod in SMI_BASE_EXPORTS.items() if mod == "SNMPv2-CONF"},
            {"OBJECT-GROUP", "NOTIFICATION-GROUP", "MODULE-COMPLIANCE", "AGENT-CAPABILITIES"},
        )

    def testEveryTextualConventionRfc2579DefinesIsThere(self):
        self.assertEqual(
            {sym for sym, mod in SMI_BASE_EXPORTS.items() if mod == "SNMPv2-TC"},
            {
                "TEXTUAL-CONVENTION",
                "DisplayString",
                "PhysAddress",
                "MacAddress",
                "TruthValue",
                "TestAndIncr",
                "AutonomousType",
                "InstancePointer",
                "VariablePointer",
                "RowPointer",
                "RowStatus",
                "TimeStamp",
                "TimeInterval",
                "DateAndTime",
                "StorageType",
                "TDomain",
                "TAddress",
            },
        )

    def testNoSymbolComesFromACompiledModule(self):
        # SNMPv2-MIB exports sysUpTime and snmpTrapOID, which vendor MIBs omit
        # from IMPORTS at least as often as they omit a base type. Repairing
        # those would add a compilation dependency the module never declared,
        # so the table deliberately stops at the base modules.
        for symbol in ("sysUpTime", "snmpTrapOID", "ifIndex"):
            with self.subTest(symbol=symbol):
                self.assertNotIn(symbol, SMI_BASE_EXPORTS)


class MibDumpRepairTestCase(unittest.TestCase):
    """The flag reaches the compiler, and what it repaired reaches the report."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = Path(self._tmp.name) / "src"
        self.dst = Path(self._tmp.name) / "dst"
        self.src.mkdir()
        (self.src / "REPAIR-TC-MIB").write_text(BROKEN["TruthValue"])
        (self.src / "SNMPv2-SMI").write_text(mibs.SNMPV2_SMI)
        (self.src / "SNMPv2-TC").write_text(mibs.SNMPV2_TC)
        (self.src / "SNMPv2-CONF").write_text("SNMPv2-CONF DEFINITIONS ::= BEGIN\nEND\n")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        argv = sys.argv
        sys.argv = [
            "mibdump",
            f"--mib-source={self.src}",
            f"--destination-directory={self.dst}",
            "--no-python-compile",
            "--rebuild",
            *extra,
            "REPAIR-TC-MIB",
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

    def testWithoutTheFlagTheBrokenMibFails(self):
        code, output = self._run()

        self.assertNotEqual(0, code, output)
        self.assertIn("Failed MIBs: REPAIR-TC-MIB", output)

    def testTheFlagCompilesItAndTheReportSaysWhatWasSupplied(self):
        code, output = self._run("--repair-imports")

        self.assertEqual(0, code, output)
        self.assertIn("Created/updated MIBs: REPAIR-TC-MIB", output)
        self.assertIn("Repaired MIBs: REPAIR-TC-MIB (TruthValue from SNMPv2-TC)", output)

    def testAnUnrepairedMibIsNotNamedOnTheRepairedLine(self):
        (self.src / "REPAIR-CLEAN-MIB").write_text(module("REPAIR-CLEAN-MIB", "OBJECT-TYPE, Opaque", "Opaque", "1 3 3"))
        code, output = self._run("--repair-imports")

        self.assertEqual(0, code, output)

        repaired = next(line for line in output.splitlines() if line.startswith("Repaired MIBs:"))

        self.assertNotIn("REPAIR-CLEAN-MIB", repaired)

    def testTheUsageMessageDocumentsTheFlag(self):
        out, err = io.StringIO(), io.StringIO()
        argv = sys.argv
        sys.argv = ["mibdump", "--help"]

        try:
            with redirect_stdout(out), redirect_stderr(err):
                mibdump.start()
        except SystemExit:
            pass
        finally:
            sys.argv = argv

        self.assertIn("[--repair-imports]", out.getvalue() + err.getvalue())


if __name__ == "__main__":
    unittest.main()
