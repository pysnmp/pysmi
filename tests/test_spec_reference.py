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

Emitting a ``setReference()`` call is a different question, and pysnmp answers
it differently per class: three of the classes have no such setter, and a call
to one raises AttributeError as the module loads. That split is a property of
the emitted source, so it is read there. See pysnmp/pysmi#101.
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

#: The classes whose pysnmp counterpart implements setReference(), and the
#: reference each one carries in MACROS_MIB.
WITH_SET_REFERENCE = {
    "testObjectIdentity": "RFC 2578 Section 6",
    "testObjectType": "RFC 2578 Section 7",
    "testNotificationType": "RFC 2578 Section 8",
    "testAgentCapabilities": "RFC 2580 Section 6",
}

#: The classes whose pysnmp counterpart does not. RFC 2580 gives all three a
#: REFERENCE clause; emitting the call anyway yields a module that raises
#: AttributeError when loaded with texts. See pysnmp/pysnmp#133.
WITHOUT_SET_REFERENCE = {
    "testObjectGroup": "RFC 2580 Section 3",
    "testNotificationGroup": "RFC 2580 Section 4",
    "testModuleCompliance": "RFC 2580 Section 5",
}


class DocumentTestCase(unittest.TestCase):
    """Every REFERENCE the MIB wrote reaches the document."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MACROS_MIB)

    def testEveryMacroKeepsItsReference(self):
        # What one consumer cannot hold is not a reason to drop the clause from
        # the interchange format, which every other consumer reads.
        for symbol, reference in {**WITH_SET_REFERENCE, **WITHOUT_SET_REFERENCE}.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], reference)

    def testATrapTypeKeepsItsReference(self):
        self.assertEqual(render_json(TRAP_MIB)["testTrap"]["reference"], "RFC 1215")

    def testATextualConventionKeepsItsReference(self):
        # RFC 2579 section 3.4 permits REFERENCE on a TEXTUAL-CONVENTION.
        self.assertEqual(render_json(TC_MIB)["TestConvention"]["reference"], "RFC 2579 Section 3")
        self.assertNotIn("reference", render_json(TC_MIB, genTexts=False)["TestConvention"])

    def testTheDocumentIsTheOnlyArtifactThatKeepsTheRestOfThem(self):
        # ObjectGroup, NotificationGroup and ModuleCompliance have no setter, so
        # the document is the only place their REFERENCE survives. pysnmp/mibs
        # republishes the document, which makes this load-bearing. See
        # pysnmp/pysmi#100.
        source = render_source(MACROS_MIB)
        for symbol, reference in WITHOUT_SET_REFERENCE.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], reference)
                self.assertNotIn(reference, source)

    def testNoReferenceIsRecordedWithoutTexts(self):
        # REFERENCE is narrative: it points a reader at prose. A module compiled
        # without texts has no use for it.
        doc = render_json(MACROS_MIB, genTexts=False)
        for symbol in {**WITH_SET_REFERENCE, **WITHOUT_SET_REFERENCE}:
            with self.subTest(symbol=symbol):
                self.assertNotIn("reference", doc[symbol])


class EmittedCallTestCase(unittest.TestCase):
    """setReference() is emitted for exactly the classes that implement it."""

    @classmethod
    def setUpClass(cls):
        cls.source = render_source(MACROS_MIB)

    def testTheClassesWithASetterGetExactlyOneCall(self):
        for symbol in WITH_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.source.count(f"{symbol}.setReference("), 1)

    def testTheClassesWithoutASetterGetNone(self):
        for symbol in WITHOUT_SET_REFERENCE:
            with self.subTest(symbol=symbol):
                self.assertNotIn(f"{symbol}.setReference(", self.source)

    def testNoOtherCallIsEmitted(self):
        # Counting pins the two lists together: a new macro that starts
        # emitting a call has to be classified rather than silently added.
        self.assertEqual(len(re.findall(r"\.setReference\(", self.source)), len(WITH_SET_REFERENCE))

    def testEveryCallIsGuarded(self):
        for line in self.source.splitlines():
            if ".setReference(" in line:
                with self.subTest(line=line.strip()):
                    self.assertTrue(line.startswith("if mibBuilder.loadTexts: "))

    def testNoCallSurvivesWithoutTexts(self):
        self.assertEqual(len(re.findall(r"\.setReference\(", render_source(MACROS_MIB, genTexts=False))), 0)

    def testATrapTypeGetsAGuardedCall(self):
        source = render_source(TRAP_MIB)
        self.assertIn("if mibBuilder.loadTexts: testTrap.setReference('RFC 1215')", source)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
