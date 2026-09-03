#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""What an AGENT-CAPABILITIES says it supports.

RFC 2580 section 6.5 gives the clause a SUPPORTS sub-clause per module, each
naming the groups it INCLUDES and the VARIATIONs it implements them with. The
parser used to discard all of it. It is kept now, and the JSON document carries
it; pysnmp has no setter for any of it, so its output must not move.
"""

import sys
import unittest

from tests.harness import render_json, render_source

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    AGENT-CAPABILITIES
        FROM SNMPv2-CONF
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testObject OBJECT-TYPE
    SYNTAX      Integer32 (0..100)
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "An object a variation can refine."
    ::= { 1 3 1 }

testCapability AGENT-CAPABILITIES
    PRODUCT-RELEASE "Test product"
    STATUS          current
    DESCRIPTION     "test capabilities"

    SUPPORTS        TEST-MIB
    INCLUDES        { testGroupOne, testGroupTwo }

    VARIATION       testObject
    SYNTAX          Integer32 (0..10)
    WRITE-SYNTAX    Integer32 (0..5)
    ACCESS          read-only
    CREATION-REQUIRES { testObject }
    DEFVAL          { 3 }
    DESCRIPTION     "Narrowed on both sides."

    SUPPORTS        OTHER-MIB
    INCLUDES        { otherGroup }

 ::= { 1 3 2 }

END
"""


class SupportsTestCase(unittest.TestCase):
    """One entry per SUPPORTS clause, in the order the clauses appear."""

    def setUp(self):
        self.capabilities = render_json(MIB)["testCapability"]["capabilities"]

    def testEverySupportedModuleIsNamed(self):
        self.assertEqual([c["module"] for c in self.capabilities], ["TEST-MIB", "OTHER-MIB"])

    def testEachClauseCarriesItsOwnGroups(self):
        self.assertEqual(self.capabilities[0]["includes"], ["testGroupOne", "testGroupTwo"])
        self.assertEqual(self.capabilities[1]["includes"], ["otherGroup"])

    def testAClauseWithoutVariationsReportsNone(self):
        self.assertNotIn("variations", self.capabilities[1])


class VariationTestCase(unittest.TestCase):
    """Every VARIATION sub-clause RFC 2580 section 6.5.2 defines."""

    def setUp(self):
        doc = render_json(MIB)
        self.variation = doc["testCapability"]["capabilities"][0]["variations"][0]

    def testTheVariedObjectIsNamed(self):
        self.assertEqual(self.variation["object"], "testObject")

    def testSyntaxIsRenderedAsAType(self):
        self.assertEqual(self.variation["syntax"]["constraints"]["range"], [{"min": 0, "max": 10}])

    def testWriteSyntaxIsSeparateFromSyntax(self):
        self.assertEqual(self.variation["writesyntax"]["constraints"]["range"], [{"min": 0, "max": 5}])

    def testAccessIsReported(self):
        self.assertEqual(self.variation["access"], "read-only")

    def testCreationRequiresNamesItsCells(self):
        self.assertEqual(self.variation["creationrequires"], ["testObject"])

    def testDefValIsRenderedAsTheObjectsType(self):
        # The same shape an OBJECT-TYPE's own default is given.
        self.assertEqual(self.variation["default"], {"value": 3, "format": "decimal"})

    def testDescriptionIsReported(self):
        self.assertEqual(self.variation["description"], "Narrowed on both sides.")


class SuppressedTextsTestCase(unittest.TestCase):
    """What survives ``genTexts=False``.

    A variation's DESCRIPTION is narrative, so it goes. What it refines is
    structural -- an implementation is held to it -- so that stays.
    """

    def setUp(self):
        doc = render_json(MIB, genTexts=False)
        self.capabilities = doc["testCapability"]["capabilities"]

    def testTheRefinementSurvives(self):
        variation = self.capabilities[0]["variations"][0]
        self.assertEqual(variation["object"], "testObject")
        self.assertIn("syntax", variation)
        self.assertIn("writesyntax", variation)
        self.assertEqual(variation["access"], "read-only")

    def testTheDescriptionIsDropped(self):
        self.assertNotIn("description", self.capabilities[0]["variations"][0])

    def testTheSupportedModulesAreStillNamed(self):
        self.assertEqual([c["module"] for c in self.capabilities], ["TEST-MIB", "OTHER-MIB"])


class PysnmpOutputTestCase(unittest.TestCase):
    """None of it reaches the pysnmp backend.

    ``AgentCapabilities`` has no setter for a SUPPORTS clause -- see
    pysnmp/pysnmp#133 -- so restoring the parser productions must leave the
    generated module exactly as it was.
    """

    def setUp(self):
        self.source = render_source(MIB)

    def testTheCapabilitiesObjectIsBuiltFromItsOidAlone(self):
        self.assertIn("testCapability = AgentCapabilities((1, 3, 2))\n", self.source)

    def testNothingOfTheSupportsClauseIsEmitted(self):
        for dropped in ("SUPPORTS", "INCLUDES", "VARIATION", "setSupports", "OTHER-MIB", "testGroupOne"):
            with self.subTest(clause=dropped):
                self.assertNotIn(dropped, self.source)

    def testTheClausesPysnmpCanHoldAreStillEmitted(self):
        self.assertIn("setProductRelease('Test product')", self.source)
        self.assertIn("setStatus('current')", self.source)
        self.assertIn("setDescription('test capabilities')", self.source)


class UnresolvableDefValTestCase(unittest.TestCase):
    """A DEFVAL on an object this module cannot resolve.

    The object a variation names belongs to the module SUPPORTS names. Where
    that module was not read, its type cannot be walked back to a base, so the
    default is reported as written rather than dropped.
    """

    MIB = """
    TEST-MIB DEFINITIONS ::= BEGIN
    IMPORTS
        AGENT-CAPABILITIES
            FROM SNMPv2-CONF;

    testCapability AGENT-CAPABILITIES
        PRODUCT-RELEASE "Test product"
        STATUS          current
        DESCRIPTION     "test capabilities"

        SUPPORTS        OTHER-MIB
        INCLUDES        { otherGroup }

        VARIATION       otherObject
        DEFVAL          { 7 }
        DESCRIPTION     "Defaulted elsewhere."

     ::= { 1 3 }

    END
    """

    def testTheDefaultIsReportedAsWritten(self):
        with self.assertLogs("pysmi.codegen.jsondoc", level="WARNING") as logs:
            doc = render_json(self.MIB)

        variation = doc["testCapability"]["capabilities"][0]["variations"][0]
        self.assertEqual(variation["default"], [7])
        self.assertIn("otherObject", logs.output[0])
        self.assertIn("OTHER-MIB", logs.output[0])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
