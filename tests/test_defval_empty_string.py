#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import json
import unittest

from pysnmp.smi.builder import MibBuilder

from pysmi.codegen.jsondoc import JsonCodeGen
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
  OBJECT-TYPE
    FROM SNMPv2-SMI;

testEmptyString OBJECT-TYPE
    SYNTAX          OCTET STRING
    MAX-ACCESS      read-write
    STATUS          current
    DESCRIPTION     "An empty default is meaningful for OCTET STRING"
    DEFVAL          { "" }
 ::= { 1 3 }

testEmptyInteger OBJECT-TYPE
    SYNTAX          Integer32
    MAX-ACCESS      read-write
    STATUS          current
    DESCRIPTION     "An empty default is meaningless here and is dropped"
    DEFVAL          { "" }
 ::= { 1 4 }

END
"""


class DefValEmptyStringTestCase(unittest.TestCase):
    """An empty DEFVAL is kept for OCTET STRING and dropped for other types.

    ``gen_def_val`` used to compare the tuple returned by ``get_base_type`` against
    the string ``"OctetString"``. That comparison could never hold, so the
    guard meant to discard bogus empty defaults discarded every one of them.
    """

    def setUp(self):
        ast = parserFactory()().parse(MIB)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {})
        self.symtable = {mibInfo.name: symtable}
        self.ast = ast

    def testPySnmpKeepsEmptyOctetStringDefault(self):
        _, pycode = PySnmpCodeGen().gen_code(self.ast, self.symtable)

        mibBuilder = MibBuilder()
        ctx = {"mibBuilder": mibBuilder}
        exec(compile(pycode, "test", "exec"), ctx, ctx)

        self.assertEqual(
            ctx["testEmptyString"].getSyntax(),
            b"",
            "empty DEFVAL dropped for OCTET STRING",
        )

    def testPySnmpDropsEmptyDefaultForOtherTypes(self):
        _, pycode = PySnmpCodeGen().gen_code(self.ast, self.symtable)

        self.assertNotIn(
            "testEmptyInteger = MibScalar((1, 3), Integer32().clone",
            pycode,
            "empty DEFVAL kept for Integer32",
        )

    def testJsonKeepsEmptyOctetStringDefault(self):
        _, jsoncode = JsonCodeGen().gen_code(self.ast, self.symtable)
        doc = json.loads(jsoncode)

        self.assertEqual(
            doc["testEmptyString"]["default"]["default"],
            {"value": "", "format": "string"},
            "empty DEFVAL dropped for OCTET STRING",
        )

    def testJsonDropsEmptyDefaultForOtherTypes(self):
        _, jsoncode = JsonCodeGen().gen_code(self.ast, self.symtable)
        doc = json.loads(jsoncode)

        self.assertNotIn("default", doc["testEmptyInteger"], "empty DEFVAL kept for Integer32")


if __name__ == "__main__":
    unittest.main()
