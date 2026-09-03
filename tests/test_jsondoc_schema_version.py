#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The JSON document declares which schema it is written to.

The shape used to be implicit: a consumer had to infer it, and would only find
out that it had changed by breaking. Both the module document and the index now
declare their schema, and a consumer that understands one version can ask for it
and be told when this pysmi cannot emit it.
"""

import json
import sys
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen
from tests.harness import render_json, symbol_table

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { 1 3 1 }

END
"""


class ModuleDocumentTestCase(unittest.TestCase):
    """Every module document declares its schema, comments or not."""

    def testTheSchemaIsDeclared(self):
        self.assertEqual(render_json(MIB)["meta"]["schema"], JsonCodeGen.SCHEMA_VERSION)

    def testTheSchemaIsDeclaredAlongsideComments(self):
        ast, _, table = symbol_table(MIB)
        _, doc = JsonCodeGen().gen_code(ast, table, genTexts=True, comments=["Produced by pysmi"])
        meta = json.loads(doc)["meta"]

        self.assertEqual(meta["schema"], JsonCodeGen.SCHEMA_VERSION)
        self.assertEqual(meta["comments"], ["Produced by pysmi"])
        self.assertEqual(meta["module"], "TEST-MIB")

    def testTheCurrentSchemaMayBeAskedForByNumber(self):
        ast, _, table = symbol_table(MIB)
        _, doc = JsonCodeGen().gen_code(ast, table, schemaVersion=1)

        self.assertEqual(json.loads(doc)["meta"]["schema"], 1)

    def testAnUnknownSchemaIsRefused(self):
        ast, _, table = symbol_table(MIB)

        with self.assertRaises(error.PySmiCodegenError) as raised:
            JsonCodeGen().gen_code(ast, table, schemaVersion=99)

        self.assertIn("99", str(raised.exception))
        self.assertIn("1", str(raised.exception))


class IndexDocumentTestCase(unittest.TestCase):
    """The index declares its schema too, and its own rather than an old one."""

    def index(self, **kwargs):
        return json.loads(JsonCodeGen().gen_index({}, **kwargs))

    def testTheSchemaIsDeclared(self):
        self.assertEqual(self.index()["meta"]["schema"], JsonCodeGen.SCHEMA_VERSION)

    def testAMergedIndexDeclaresThisRunsSchema(self):
        stale = json.dumps({"meta": {"schema": 0}, "identity": {}, "enterprise": {}, "compliance": {}, "oids": {}})

        self.assertEqual(self.index(old_index_data=stale)["meta"]["schema"], JsonCodeGen.SCHEMA_VERSION)

    def testAnUnknownSchemaIsRefused(self):
        with self.assertRaises(error.PySmiCodegenError):
            JsonCodeGen().gen_index({}, schemaVersion=99)


class SupportedVersionsTestCase(unittest.TestCase):
    """What the generator says it can emit."""

    def testTheDefaultIsTheNewest(self):
        self.assertEqual(JsonCodeGen.SCHEMA_VERSION, JsonCodeGen.SCHEMA_VERSIONS[-1])

    def testEveryAdvertisedVersionCanBeEmitted(self):
        ast, _, table = symbol_table(MIB)

        for version in JsonCodeGen.SCHEMA_VERSIONS:
            with self.subTest(schema=version):
                _, doc = JsonCodeGen().gen_code(ast, table, schemaVersion=version)
                self.assertEqual(json.loads(doc)["meta"]["schema"], version)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
