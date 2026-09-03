#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import sys
import unittest

from pysnmp.smi.builder import MibBuilder

from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory
from tests.harness import render


class AgentCapabilitiesTestCase(unittest.TestCase):
    """
    TEST-MIB DEFINITIONS ::= BEGIN
    IMPORTS
        MODULE-IDENTITY
            FROM SNMPv2-SMI
        AGENT-CAPABILITIES
            FROM SNMPv2-CONF;

    testCapability AGENT-CAPABILITIES
        PRODUCT-RELEASE "Test produce"
        STATUS          current
        DESCRIPTION
            "test capabilities"

        SUPPORTS        TEST-MIB
        INCLUDES        {
                            testSystemGroup,
                            testNotificationObjectGroup,
                            testNotificationGroup
                        }
        VARIATION       testSysLevelType
        ACCESS          read-only
        DESCRIPTION
            "Not supported."

        VARIATION       testSysLevelType
        ACCESS          read-only
        DESCRIPTION
            "Supported."

     ::= { 1 3 }

    END
    """

    def setUp(self):
        ast = parserFactory()().parse(self.__class__.__doc__)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=True)
        self.mibInfo, pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=True)
        codeobj = compile(pycode, "test", "exec")

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True

        self.ctx = {"mibBuilder": mibBuilder}

        exec(codeobj, self.ctx, self.ctx)

    def testAgentCapabilitiesSymbol(self):
        self.assertTrue("testCapability" in self.ctx, "symbol not present")

    def testAgentCapabilitiesName(self):
        self.assertEqual(self.ctx["testCapability"].getName(), (1, 3), "bad name")

    def testAgentCapabilitiesDescription(self):
        self.assertEqual(self.ctx["testCapability"].getDescription(), "test capabilities", "bad DESCRIPTION")

    def testAgentCapabilitiesClass(self):
        self.assertEqual(self.ctx["testCapability"].__class__.__name__, "AgentCapabilities", "bad SYNTAX class")


class AgentCapabilitiesSupportsTestCase(unittest.TestCase):
    """SUPPORTS, INCLUDES and VARIATION reach the JSON document only.

    pysnmp's ``AgentCapabilities`` carries productRelease, status, description
    and reference, and nothing else -- its class body still says
    ``# TODO: implement the rest of properties``. So the pysnmp backend has
    nowhere to put this and its output is unchanged; see pysnmp/pysnmp#133.
    The JSON document has somewhere, and carries it in full.
    """

    def setUp(self):
        mib = AgentCapabilitiesTestCase.__doc__
        self.doc, self.ctx = render(mib)
        self.capabilities = self.doc["testCapability"]["capabilities"]

    def testTheSupportedModuleIsNamed(self):
        self.assertEqual([c["module"] for c in self.capabilities], ["TEST-MIB"])

    def testIncludesNamesEveryGroup(self):
        self.assertEqual(
            self.capabilities[0]["includes"],
            ["testSystemGroup", "testNotificationObjectGroup", "testNotificationGroup"],
        )

    def testEachVariationIsReported(self):
        variations = self.capabilities[0]["variations"]
        self.assertEqual([v["object"] for v in variations], ["testSysLevelType", "testSysLevelType"])
        self.assertEqual([v["access"] for v in variations], ["read-only", "read-only"])
        self.assertEqual([v["description"] for v in variations], ["Not supported.", "Supported."])

    def testThePysnmpObjectIsUnchanged(self):
        # The parser now keeps the detail, but pysnmp has no setter for it, so
        # nothing about the object it builds may move.
        rendered = str(vars(self.ctx["testCapability"]))
        for dropped in ("testSysLevelType", "SUPPORTS", "INCLUDES", "VARIATION"):
            with self.subTest(clause=dropped):
                self.assertNotIn(dropped, rendered)

    def testTheDocumentCarriesNothingElseNew(self):
        self.assertEqual(
            set(self.doc["testCapability"]),
            {"name", "oid", "class", "productrelease", "status", "description", "capabilities"},
        )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
