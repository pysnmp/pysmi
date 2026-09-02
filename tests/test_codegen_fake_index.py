#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for the fake index column SMIv1 tables need."""

import json
import sys
import unittest

from pysmi import error
from pysmi.codegen.jsondoc import JsonCodeGen
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import CallbackReader
from pysmi.writer import CallbackWriter

# One INDEX entry naming a base type rather than a column, which is what SMIv1
# permits and what makes a backend synthesise a column to stand in for it.
SMIV1_BARE_TYPE_INDEX = [[(0, "INTEGER")]]

# A table whose INDEX names a base type rather than one of its columns.
SMIV1_MIB = """FAKE-IDX-MIB DEFINITIONS ::= BEGIN

testTable OBJECT-TYPE
    SYNTAX  SEQUENCE OF TestEntry
    ACCESS  not-accessible
    STATUS  mandatory
    DESCRIPTION "a table"
    ::= { 1 3 6 1 4 1 99999 1 }

testEntry OBJECT-TYPE
    SYNTAX  TestEntry
    ACCESS  not-accessible
    STATUS  mandatory
    DESCRIPTION "a row"
    INDEX   { INTEGER }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE { testValue INTEGER }

testValue OBJECT-TYPE
    SYNTAX  INTEGER
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "a column"
    ::= { testEntry 1 }

END
"""


def compileSmiV1Mib(codegen):
    """Compile the sample MIB with *codegen*, returning its status and output."""
    written = {}

    def read(mibname, context):
        if mibname != "FAKE-IDX-MIB":
            raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=None)
        return SMIV1_MIB

    compiler = MibCompiler(
        SmiV1CompatParser(),
        codegen,
        CallbackWriter(lambda mibname, data, ctx: written.update({mibname: data})),
    )
    compiler.add_sources(CallbackReader(read))

    # The base MIBs cannot be reached from here, and their absence would
    # otherwise roll back the one MIB that did compile.
    results = compiler.compile("FAKE-IDX-MIB", ignoreErrors=True)

    return results["FAKE-IDX-MIB"], written.get("FAKE-IDX-MIB")


class FakeIndexSymbolTestCase(unittest.TestCase):
    """Both backends synthesise the stand-in column the same way.

    Each returns the generated entry paired with the symbol name, which the
    caller unpacks. Returning anything else silently yields a symbol name that
    is not a name at all.
    """

    def testJsonBackendReturnsEntryAndName(self):
        codegen = JsonCodeGen()
        codegen.moduleName = ["TEST-MIB"]

        _indexes, fakeStrlist, fakeSyms = codegen.gen_table_index(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(fakeSyms, ["pysmiFakeCol1000"])

        column = fakeStrlist[0]

        self.assertEqual(column["name"], "pysmiFakeCol1000")
        self.assertEqual(column["nodetype"], "column")
        self.assertEqual(column["class"], "objecttype")
        # The JSON backend keeps the SMI type name; only the pysnmp backend
        # maps it onto an implementation class.
        self.assertEqual(column["syntax"], {"type": "INTEGER", "class": "type"})
        # The row's OID is not known yet, so it is left as a template.
        self.assertEqual(column["oid"] % "1.3.6.1", "1.3.6.1.1000")

    def testPySnmpBackendReturnsCodeAndName(self):
        codegen = PySnmpCodeGen()
        codegen.moduleName = ["TEST-MIB"]

        _indexStr, fakeStrlist, fakeSyms = codegen.gen_table_index(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(fakeSyms, ["pysmiFakeCol1000"])
        self.assertIn("MibTableColumn", fakeStrlist[0])

    def testBackendsAgreeOnFakeSymbolName(self):
        jsonGen = JsonCodeGen()
        jsonGen.moduleName = ["TEST-MIB"]

        pysnmpGen = PySnmpCodeGen()
        pysnmpGen.moduleName = ["TEST-MIB"]

        _a, _b, jsonSyms = jsonGen.gen_table_index(SMIV1_BARE_TYPE_INDEX)
        _c, _d, pysnmpSyms = pysnmpGen.gen_table_index(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(jsonSyms, pysnmpSyms)


class SmiV1BareTypeIndexCompileTestCase(unittest.TestCase):
    """A MIB whose INDEX names a base type must compile in both backends.

    The symbol table synthesises a column for such an index, so a backend that
    does not emit one leaves a symbol with no generated code behind it and the
    whole module fails.
    """

    def testJsonBackendCompiles(self):
        """The JSON backend compiles the module."""
        status, _output = compileSmiV1Mib(JsonCodeGen())

        self.assertEqual(status, "compiled", getattr(status, "error", None))

    def testPySnmpBackendCompiles(self):
        """The pysnmp backend compiles the module, as it always has."""
        status, _output = compileSmiV1Mib(PySnmpCodeGen())

        self.assertEqual(status, "compiled", getattr(status, "error", None))

    def testJsonBackendEmitsTheColumn(self):
        """The synthetic column reaches the JSON document."""
        _status, output = compileSmiV1Mib(JsonCodeGen())

        document = json.loads(output)

        self.assertIn("pysmiFakeCol1000", document)

        column = document["pysmiFakeCol1000"]

        self.assertEqual(column["nodetype"], "column")
        self.assertEqual(column["syntax"]["type"], "INTEGER")

    def testBackendsAgreeOnTheColumnOid(self):
        """Both backends hang the column off the row under the same OID.

        The pysnmp backend builds it as the row's OID plus the sub-identifier,
        so the JSON document has to arrive at the same place.
        """
        _jsonStatus, jsonOutput = compileSmiV1Mib(JsonCodeGen())
        _pysnmpStatus, pysnmpOutput = compileSmiV1Mib(PySnmpCodeGen())

        oid = json.loads(jsonOutput)["pysmiFakeCol1000"]["oid"]

        self.assertEqual(oid, "1.3.6.1.4.1.99999.1.1.1000")
        self.assertIn(
            "pysmiFakeCol1000 = MibTableColumn((1, 3, 6, 1, 4, 1, 99999, 1, 1) + (1000, )",
            pysnmpOutput,
        )

    def testRowIndexPointsAtTheColumn(self):
        """The row's index names the synthetic column, not the base type."""
        _status, output = compileSmiV1Mib(JsonCodeGen())

        indices = json.loads(output)["testEntry"]["indices"]

        self.assertEqual(len(indices), 1)
        self.assertEqual(indices[0]["object"], "pysmiFakeCol1000")
        self.assertEqual(indices[0]["module"], "FAKE-IDX-MIB")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
