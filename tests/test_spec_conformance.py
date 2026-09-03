#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The conformance macros are emitted as RFC 2580 defines them.

RFC 2580 section 3 gives OBJECT-GROUP, section 4 NOTIFICATION-GROUP, section 5
MODULE-COMPLIANCE and section 6 AGENT-CAPABILITIES.

pysnmp's classes for these carry a fraction of what the macros define -- no
REFERENCE on three of them, and nothing at all of SUPPORTS, INCLUDES or
VARIATION. So a runtime assertion can only reach the fraction, and everything
the spec requires beyond it is untestable through pysnmp by construction. The
JSON document carries it in full, and is what these assertions read. See
pysnmp/pysmi#127 and pysnmp/pysnmp#133.
"""

import sys
import unittest

from tests.harness import render_json, render_source

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, NOTIFICATION-TYPE, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

testStorageType OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS current DESCRIPTION "a" ::= { 1 3 1 }

testRowStatus OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS current DESCRIPTION "b" ::= { 1 3 2 }

testStatusChangeNotify NOTIFICATION-TYPE
    OBJECTS { testStorageType } STATUS current DESCRIPTION "c" ::= { 1 3 3 }

testClassEventNotify NOTIFICATION-TYPE
    OBJECTS { testRowStatus } STATUS current DESCRIPTION "d" ::= { 1 3 4 }

testObjectGroup OBJECT-GROUP
    OBJECTS     { testStorageType, testRowStatus }
    STATUS      current
    DESCRIPTION "A collection of test objects."
    REFERENCE   "Group reference"
    ::= { 1 3 5 }

testNotificationGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testStatusChangeNotify, testClassEventNotify }
    STATUS        current
    DESCRIPTION   "A collection of test notifications."
    REFERENCE     "Notification group reference"
    ::= { 1 3 6 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "This is the MIB compliance statement"
    REFERENCE   "Compliance reference"
    MODULE
        MANDATORY-GROUPS { testObjectGroup }
        GROUP       testNotificationGroup
        DESCRIPTION "Support for these notifications is optional."
    ::= { 1 3 7 }

testCapability AGENT-CAPABILITIES
    PRODUCT-RELEASE "Test produce"
    STATUS          current
    DESCRIPTION     "test capabilities"
    SUPPORTS        TEST-MIB
    INCLUDES        { testObjectGroup, testNotificationGroup }
    VARIATION       testStorageType
    ACCESS          read-only
    DESCRIPTION     "Not supported."
    VARIATION       testRowStatus
    ACCESS          read-only
    DESCRIPTION     "Supported."
    ::= { 1 3 8 }

END
"""

#: The three classes RFC 2580 gives a REFERENCE that pysnmp cannot hold: their
#: classes have no setReference, so pysmi carries the text to the JSON document
#: instead of emitting a call that would fail on load. See pysnmp/pysmi#101.
WITHOUT_SET_REFERENCE = ("testObjectGroup", "testNotificationGroup", "testCompliance")


class ObjectGroupTestCase(unittest.TestCase):
    """RFC 2580 section 3: OBJECT-GROUP."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testObjectGroup"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "objectgroup")
        self.assertEqual(self.doc["oid"], "1.3.5")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "A collection of test objects.")
        self.assertEqual(self.doc["reference"], "Group reference")

    def testTheObjectsAreNamedWithTheirModuleInClauseOrder(self):
        # Section 3 makes OBJECTS a list of object descriptors. A group may name
        # objects from another module, so each entry has to carry its module.
        self.assertEqual(
            self.doc["objects"],
            [
                {"module": "TEST-MIB", "object": "testStorageType"},
                {"module": "TEST-MIB", "object": "testRowStatus"},
            ],
        )

    def testTheEmittedGroupPassesItsObjectsAsPairs(self):
        self.assertIn(
            "testObjectGroup = ObjectGroup((1, 3, 5)).setObjects("
            '("TEST-MIB", "testStorageType"), ("TEST-MIB", "testRowStatus"))',
            self.source,
        )


class NotificationGroupTestCase(unittest.TestCase):
    """RFC 2580 section 4: NOTIFICATION-GROUP."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testNotificationGroup"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "notificationgroup")
        self.assertEqual(self.doc["oid"], "1.3.6")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "A collection of test notifications.")
        self.assertEqual(self.doc["reference"], "Notification group reference")

    def testTheNotificationsAreNamedInClauseOrder(self):
        self.assertEqual(
            self.doc["objects"],
            [
                {"module": "TEST-MIB", "object": "testStatusChangeNotify"},
                {"module": "TEST-MIB", "object": "testClassEventNotify"},
            ],
        )

    def testTheEmittedGroupPassesItsNotificationsAsPairs(self):
        self.assertIn(
            "testNotificationGroup = NotificationGroup((1, 3, 6)).setObjects("
            '("TEST-MIB", "testStatusChangeNotify"), ("TEST-MIB", "testClassEventNotify"))',
            self.source,
        )


class ModuleComplianceTestCase(unittest.TestCase):
    """RFC 2580 section 5: MODULE-COMPLIANCE."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testCompliance"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "modulecompliance")
        self.assertEqual(self.doc["oid"], "1.3.7")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "This is the MIB compliance statement")
        self.assertEqual(self.doc["reference"], "Compliance reference")

    def testMandatoryAndConditionalGroupsAreBothRecorded(self):
        # Section 5 makes MANDATORY-GROUPS and GROUP two different obligations,
        # so a document that flattened them would say every group is required.
        self.assertEqual(
            self.doc["modulecompliance"],
            [
                {"object": "testObjectGroup", "module": "TEST-MIB"},
                {"object": "testNotificationGroup", "module": "TEST-MIB"},
            ],
        )
        self.assertEqual(
            self.doc["refinements"],
            [
                {
                    "module": "TEST-MIB",
                    "object": "testNotificationGroup",
                    "kind": "group",
                    "description": "Support for these notifications is optional.",
                }
            ],
        )

    def testTheEmittedComplianceNamesEveryGroupItMentions(self):
        self.assertIn(
            "testCompliance = ModuleCompliance((1, 3, 7)).setObjects("
            '("TEST-MIB", "testObjectGroup"), ("TEST-MIB", "testNotificationGroup"))',
            self.source,
        )


class AgentCapabilitiesTestCase(unittest.TestCase):
    """RFC 2580 section 6: AGENT-CAPABILITIES.

    pysnmp's ``AgentCapabilities`` holds productRelease, status, description and
    reference and nothing else -- its class body still says ``# TODO: implement
    the rest of properties``. SUPPORTS, INCLUDES and VARIATION therefore reach
    the JSON document only, and a runtime assertion cannot see them at all.

    Section 6.5 -- what a SUPPORTS clause carries, down to the VARIATION -- is
    covered in full in tests/test_agentcapabilities_supports.py. What is here is
    the macro's own clauses.
    """

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testCapability"]
        cls.source = render_source(MIB)
        cls.capabilities = cls.doc["capabilities"]

    def testTheDocumentCarriesEveryClausePysnmpCanHold(self):
        self.assertEqual(self.doc["class"], "agentcapabilities")
        self.assertEqual(self.doc["oid"], "1.3.8")
        self.assertEqual(self.doc["productrelease"], "Test produce")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "test capabilities")

    def testTheSupportedModuleIsNamed(self):
        self.assertEqual([c["module"] for c in self.capabilities], ["TEST-MIB"])

    def testIncludesNamesEveryGroup(self):
        self.assertEqual(self.capabilities[0]["includes"], ["testObjectGroup", "testNotificationGroup"])

    def testEachVariationIsReportedInClauseOrder(self):
        variations = self.capabilities[0]["variations"]
        self.assertEqual([v["object"] for v in variations], ["testStorageType", "testRowStatus"])
        self.assertEqual([v["access"] for v in variations], ["read-only", "read-only"])
        self.assertEqual([v["description"] for v in variations], ["Not supported.", "Supported."])

    def testTheDocumentCarriesNothingElse(self):
        self.assertEqual(
            set(self.doc),
            {"name", "oid", "class", "productrelease", "status", "description", "capabilities"},
        )

    def testTheEmittedObjectGuardsTheClausesOlderPysnmpLacks(self):
        # setProductRelease and setStatus arrived after pysnmp 4.4.0, so the
        # generated module has to keep loading on an older one.
        self.assertIn(
            "if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):\n"
            "    testCapability = testCapability.setProductRelease('Test produce')",
            self.source,
        )


class ReferenceTestCase(unittest.TestCase):
    """REFERENCE is emitted only for the classes that can hold one."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)
        cls.source = render_source(MIB)

    def testTheDocumentKeepsEveryReferenceTheMibWrote(self):
        # RFC 2580 gives all three a REFERENCE clause, so dropping it from the
        # document because one consumer cannot hold it would lose it for every
        # other consumer too.
        for symbol in WITHOUT_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertTrue(self.doc[symbol]["reference"])

    def testNoSetReferenceIsEmittedForTheClassesWithoutOne(self):
        for symbol in WITHOUT_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertNotIn(f"{symbol}.setReference(", self.source)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
