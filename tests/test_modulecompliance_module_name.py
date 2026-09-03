#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""RFC 2580 section 5.4 lets a MODULE clause carry the module's OID.

    Each MIB module is named by its module name, and optionally, by its
    associated OBJECT IDENTIFIER as well.

The OID form was a hard parse failure until this landed. It appears in none of
the 5924 MIBs in pysnmp/mibs, which is why it went unnoticed for so long.

See pysnmp/pysmi#98.
"""

import sys
import unittest

from tests.harness import render_json

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    MODULE-COMPLIANCE, OBJECT-GROUP
        FROM SNMPv2-CONF;

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { 1 3 1 }

testGroup OBJECT-GROUP
    OBJECTS     { testObject }
    STATUS      current
    DESCRIPTION "A group."
    ::= { 1 3 2 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "A compliance statement."
    MODULE      TEST-MIB%s
        MANDATORY-GROUPS { testGroup }
    ::= { 1 3 3 }

END
"""


class ComplianceModuleNameTestCase(unittest.TestCase):
    def testTheNameOnlyFormParses(self):
        doc = render_json(MIB % "")
        self.assertEqual(doc["testCompliance"]["modulecompliance"], [{"module": "TEST-MIB", "object": "testGroup"}])

    def testTheNameAndOidFormParses(self):
        doc = render_json(MIB % " { 1 3 6 1 2 1 1 }")
        self.assertEqual(doc["testCompliance"]["modulecompliance"], [{"module": "TEST-MIB", "object": "testGroup"}])

    def testBothFormsProduceTheSameDocument(self):
        # The name identifies the module; the OID adds nothing the compiler
        # uses, so it must not change what is emitted.
        self.assertEqual(render_json(MIB % ""), render_json(MIB % " { 1 3 6 1 2 1 1 }"))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
