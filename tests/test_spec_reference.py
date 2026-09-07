#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""REFERENCE reaches the document for every macro that may carry one.

RFC 2578 gives OBJECT-IDENTITY (section 6), OBJECT-TYPE (section 7.6) and
NOTIFICATION-TYPE (section 8) a REFERENCE clause; RFC 2580 gives one to all
four conformance macros; RFC 1215 gives one to TRAP-TYPE. So the clause is
never optional to *record*.

Emitting a ``setReference()`` call used to be a different question. Three
classes had no such setter, so pysmi suppressed the call for them
(pysnmp/pysmi#101) and their text survived only in the JSON document. pysnmp
added the setters in pysnmp/pysnmp#133 and loader contract v1 states them, so
the suppression was removed in pysnmp/pysmi#194 and every class that may carry
a REFERENCE now emits one.
"""

import re
import sys
import unittest

from tests.harness import render_json, render_source

#: A module carrying every macro RFC 2578 and RFC 2580 give a REFERENCE clause.
MACROS_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, NOTIFICATION-TYPE, OBJECT-IDENTITY, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

testObjectIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "Object identity."
    REFERENCE   "RFC 2578 Section 6"
    ::= { 1 3 1 }

testObjectType OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Object type."
    REFERENCE   "RFC 2578 Section 7"
    ::= { 1 3 2 }

testNotificationType NOTIFICATION-TYPE
    OBJECTS     { testObjectType }
    STATUS      current
    DESCRIPTION "Notification type."
    REFERENCE   "RFC 2578 Section 8"
    ::= { 1 3 3 }

testObjectGroup OBJECT-GROUP
    OBJECTS     { testObjectType }
    STATUS      current
    DESCRIPTION "Object group."
    REFERENCE   "RFC 2580 Section 3"
    ::= { 1 3 4 }

testNotificationGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testNotificationType }
    STATUS        current
    DESCRIPTION   "Notification group."
    REFERENCE     "RFC 2580 Section 4"
    ::= { 1 3 5 }

testModuleCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "Module compliance."
    REFERENCE   "RFC 2580 Section 5"
    MODULE
        MANDATORY-GROUPS { testObjectGroup }
    ::= { 1 3 6 }

testAgentCapabilities AGENT-CAPABILITIES
    PRODUCT-RELEASE "Test release."
    STATUS          current
    DESCRIPTION     "Agent capabilities."
    REFERENCE       "RFC 2580 Section 6"
    ::= { 1 3 7 }

END
"""

TRAP_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TRAP-TYPE
        FROM RFC-1215
    OBJECT-TYPE
        FROM RFC1155-SMI;

testId OBJECT IDENTIFIER ::= { 1 3 }

testObject OBJECT-TYPE
    SYNTAX      INTEGER
    ACCESS      read-only
    STATUS      mandatory
    DESCRIPTION "Test object"
    ::= { 1 4 }

testTrap TRAP-TYPE
    ENTERPRISE  testId
    VARIABLES   { testObject }
    DESCRIPTION "Trap type."
    REFERENCE   "RFC 1215"
    ::= 1

END
"""

TC_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

TestConvention ::= TEXTUAL-CONVENTION
    STATUS       current
    DESCRIPTION  "A convention."
    REFERENCE    "RFC 2579 Section 3"
    SYNTAX       OCTET STRING

END
"""

#: Every symbol in MACROS_MIB carrying a REFERENCE, and the text it carries.
#: All of them reach both artifacts: loader contract v1 gives every class here
#: a ``setReference()``.
WITH_SET_REFERENCE = {
    "testObjectIdentity": "RFC 2578 Section 6",
    "testObjectType": "RFC 2578 Section 7",
    "testNotificationType": "RFC 2578 Section 8",
    "testAgentCapabilities": "RFC 2580 Section 6",
    "testObjectGroup": "RFC 2580 Section 3",
    "testNotificationGroup": "RFC 2580 Section 4",
    "testModuleCompliance": "RFC 2580 Section 5",
}

#: The three the generator used to suppress, kept named so the regression is
#: asserted directly rather than only as part of the total. See
#: pysnmp/pysmi#194.
FORMERLY_SUPPRESSED = (
    "testObjectGroup",
    "testNotificationGroup",
    "testModuleCompliance",
)


class DocumentTestCase(unittest.TestCase):
    """Every REFERENCE the MIB wrote reaches the document."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MACROS_MIB)

    def testEveryMacroKeepsItsReference(self):
        for symbol, reference in WITH_SET_REFERENCE.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], reference)

    def testATrapTypeKeepsItsReference(self):
        self.assertEqual(render_json(TRAP_MIB)["testTrap"]["reference"], "RFC 1215")

    def testATextualConventionKeepsItsReference(self):
        # RFC 2579 section 3.4 permits REFERENCE on a TEXTUAL-CONVENTION.
        self.assertEqual(
            render_json(TC_MIB)["TestConvention"]["reference"], "RFC 2579 Section 3"
        )
        self.assertNotIn(
            "reference", render_json(TC_MIB, genTexts=False)["TestConvention"]
        )

    def testTheEmittedSourceKeepsThemAsWell(self):
        # The document used to be the only artifact carrying these three. It is
        # not any more: pysnmp/pysmi#194 removed the suppression, so a consumer
        # of the pysnmp format gets the text too.
        source = render_source(MACROS_MIB)
        for symbol in FORMERLY_SUPPRESSED:
            reference = WITH_SET_REFERENCE[symbol]
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], reference)
                self.assertIn(reference, source)

    def testNoReferenceIsRecordedWithoutTexts(self):
        # REFERENCE is narrative: it points a reader at prose. A module compiled
        # without texts has no use for it.
        doc = render_json(MACROS_MIB, genTexts=False)
        for symbol in WITH_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertNotIn("reference", doc[symbol])


class EmittedCallTestCase(unittest.TestCase):
    """setReference() is emitted for every macro that may carry one."""

    @classmethod
    def setUpClass(cls):
        cls.source = render_source(MACROS_MIB)

    def testTheClassesWithASetterGetExactlyOneCall(self):
        for symbol in WITH_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.source.count(f"{symbol}.setReference("), 1)

    def testTheFormerlySuppressedClassesGetOneToo(self):
        for symbol in FORMERLY_SUPPRESSED:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.source.count(f"{symbol}.setReference("), 1)

    def testNoOtherCallIsEmitted(self):
        # Counting pins the list: a new macro that starts emitting a call has
        # to be added here rather than appearing silently.
        self.assertEqual(
            len(re.findall(r"\.setReference\(", self.source)), len(WITH_SET_REFERENCE)
        )

    def testEveryCallIsGuarded(self):
        for line in self.source.splitlines():
            if ".setReference(" in line:
                with self.subTest(line=line.strip()):
                    self.assertTrue(line.startswith("if mibBuilder.loadTexts: "))

    def testNoCallSurvivesWithoutTexts(self):
        self.assertEqual(
            len(
                re.findall(
                    r"\.setReference\(", render_source(MACROS_MIB, genTexts=False)
                )
            ),
            0,
        )

    def testATrapTypeGetsAGuardedCall(self):
        source = render_source(TRAP_MIB)
        self.assertIn(
            "if mibBuilder.loadTexts: testTrap.setReference('RFC 1215')", source
        )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
