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


class AgentCapabilitiesDroppedClausesTestCase(unittest.TestCase):
    """SUPPORTS, INCLUDES and VARIATION are discarded in the parser.

    The fixture above declares all three. Neither backend reports any of it,
    which is pinned here so that the drop is a documented decision rather than
    something noticed by its absence.

    pysnmp's ``AgentCapabilities`` carries productRelease, status, description
    and reference, and nothing else -- its class body still says
    ``# TODO: implement the rest of properties``. So for the pysnmp backend
    there is nowhere to put this. The JSON document has somewhere, and the
    parser productions would have to be restored first. See pysnmp/pysmi#90.
    """

    def setUp(self):
        mib = AgentCapabilitiesTestCase.__doc__
        self.doc, self.ctx = render(mib)

    def testTheDocumentCarriesOnlyTheClausesPysnmpCanHold(self):
        self.assertEqual(
            set(self.doc["testCapability"]),
            {"name", "oid", "class", "productrelease", "status", "description"},
        )

    def testNothingOfTheVariationReachesEitherBackend(self):
        rendered = str(self.doc["testCapability"]) + str(vars(self.ctx["testCapability"]))
        for dropped in ("testSysLevelType", "SUPPORTS", "INCLUDES", "VARIATION", "testSysLevelEntry"):
            with self.subTest(clause=dropped):
                self.assertNotIn(dropped, rendered)

    def testTheSupportedModuleIsNotNamed(self):
        self.assertNotIn("supports", self.doc["testCapability"])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
