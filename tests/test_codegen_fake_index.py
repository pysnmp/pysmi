#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for the fake index column SMIv1 tables need."""

import sys
import unittest

from pysmi.codegen.jsondoc import JsonCodeGen
from pysmi.codegen.pysnmp import PySnmpCodeGen

# One INDEX entry naming a base type rather than a column, which is what SMIv1
# permits and what makes a backend synthesise a column to stand in for it.
SMIV1_BARE_TYPE_INDEX = [[(0, "INTEGER")]]


class FakeIndexSymbolTestCase(unittest.TestCase):
    """Both backends synthesise the stand-in column the same way.

    Each returns the generated entry paired with the symbol name, which the
    caller unpacks. Returning anything else silently yields a symbol name that
    is not a name at all.
    """

    def testJsonBackendReturnsEntryAndName(self):
        codegen = JsonCodeGen()
        codegen.moduleName = ["TEST-MIB"]

        _indexes, fakeStrlist, fakeSyms = codegen.genTableIndex(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(fakeSyms, ["pysmiFakeCol1000"])
        # The JSON backend keeps the SMI type name; only the pysnmp backend
        # maps it onto an implementation class.
        self.assertEqual(fakeStrlist[0], {"module": "TEST-MIB", "object": "INTEGER"})

    def testPySnmpBackendReturnsCodeAndName(self):
        codegen = PySnmpCodeGen()
        codegen.moduleName = ["TEST-MIB"]

        _indexStr, fakeStrlist, fakeSyms = codegen.genTableIndex(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(fakeSyms, ["pysmiFakeCol1000"])
        self.assertIn("MibTableColumn", fakeStrlist[0])

    def testBackendsAgreeOnFakeSymbolName(self):
        jsonGen = JsonCodeGen()
        jsonGen.moduleName = ["TEST-MIB"]

        pysnmpGen = PySnmpCodeGen()
        pysnmpGen.moduleName = ["TEST-MIB"]

        _a, _b, jsonSyms = jsonGen.genTableIndex(SMIV1_BARE_TYPE_INDEX)
        _c, _d, pysnmpSyms = pysnmpGen.genTableIndex(SMIV1_BARE_TYPE_INDEX)

        self.assertEqual(jsonSyms, pysnmpSyms)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
