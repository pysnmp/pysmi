#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The JSON backend is asserted against the same MIBs as the pysnmp backend.

Every construct with a dedicated ``*_smiv2_pysnmp.py`` fixture and no JSON
counterpart had a completely uncovered generator in ``pysmi.codegen.jsondoc``.
The JSON document is what ``pysnmp/mibs`` republishes, so it is a shipped
artifact in its own right and not a by-product of the pysnmp one.

These tests render the fixture MIBs through both backends and assert the JSON
document directly, rather than through a consumer's object model. See
pysnmp/pysmi#96 and #99.
"""

import sys
import unittest

from tests.harness import render

NOTIFICATION_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    NOTIFICATION-TYPE, OBJECT-TYPE, OBJECT-IDENTITY, Integer32
        FROM SNMPv2-SMI
    NOTIFICATION-GROUP
        FROM SNMPv2-CONF;

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "An identity."
    REFERENCE   "RFC 2578 Section 4"
    ::= { 1 3 1 }

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  accessible-for-notify
    STATUS      current
    DESCRIPTION "An object carried by the notification."
    ::= { 1 3 2 }

testNotify NOTIFICATION-TYPE
    OBJECTS     { testObject }
    STATUS      current
    DESCRIPTION "A notification."
    REFERENCE   "RFC 2578 Section 8"
    ::= { 1 3 3 }

testNotifyGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testNotify }
    STATUS      current
    DESCRIPTION "A notification group."
    REFERENCE   "RFC 2580 Section 4"
    ::= { 1 3 4 }

END
"""


class ObjectIdentityJsonTestCase(unittest.TestCase):
    def setUp(self):
        self.doc, self.ctx = render(NOTIFICATION_MIB)

    def testShape(self):
        self.assertEqual(
            self.doc["testIdentity"],
            {
                "name": "testIdentity",
                "oid": "1.3.1",
                "class": "objectidentity",
                "status": "current",
                "description": "An identity.",
                "reference": "RFC 2578 Section 4",
            },
        )

    def testOidAgreesWithPySnmp(self):
        self.assertEqual(self.doc["testIdentity"]["oid"], "1.3.1")
        self.assertEqual(self.ctx["testIdentity"].getName(), (1, 3, 1))


class NotificationTypeJsonTestCase(unittest.TestCase):
    def setUp(self):
        self.doc, self.ctx = render(NOTIFICATION_MIB)

    def testShape(self):
        self.assertEqual(
            self.doc["testNotify"],
            {
                "name": "testNotify",
                "oid": "1.3.3",
                "class": "notificationtype",
                "objects": [{"module": "TEST-MIB", "object": "testObject"}],
                "status": "current",
                "description": "A notification.",
                "reference": "RFC 2578 Section 8",
            },
        )

    def testObjectsAgreeWithPySnmp(self):
        self.assertEqual(
            [(o["module"], o["object"]) for o in self.doc["testNotify"]["objects"]],
            list(self.ctx["testNotify"].getObjects()),
        )


class NotificationGroupJsonTestCase(unittest.TestCase):
    def setUp(self):
        self.doc, self.ctx = render(NOTIFICATION_MIB)

    def testShape(self):
        self.assertEqual(
            self.doc["testNotifyGroup"],
            {
                "name": "testNotifyGroup",
                "oid": "1.3.4",
                "class": "notificationgroup",
                "objects": [{"module": "TEST-MIB", "object": "testNotify"}],
                "status": "current",
                "description": "A notification group.",
                "reference": "RFC 2580 Section 4",
            },
        )

    def testObjectsAgreeWithPySnmp(self):
        self.assertEqual(
            [(o["module"], o["object"]) for o in self.doc["testNotifyGroup"]["objects"]],
            list(self.ctx["testNotifyGroup"].getObjects()),
        )

    def testReferenceSurvivesWherePySnmpCannotTakeIt(self):
        # pysnmp's NotificationGroup has no setReference(), so the pysnmp
        # backend drops the clause. The JSON document still carries it.
        self.assertEqual(self.doc["testNotifyGroup"]["reference"], "RFC 2580 Section 4")
        self.assertFalse(hasattr(self.ctx["testNotifyGroup"], "setReference"))


TRAP_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TRAP-TYPE
        FROM RFC-1215

    OBJECT-TYPE
        FROM RFC1155-SMI;

testId  OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 20408 }

testObject OBJECT-TYPE
    SYNTAX          INTEGER
    MAX-ACCESS      accessible-for-notify
    STATUS          current
    DESCRIPTION     "An object carried by the trap."
    ::= { 1 3 6 1 4 1 20408 1 }

testTrap TRAP-TYPE
    ENTERPRISE  testId
    VARIABLES   { testObject }
    DESCRIPTION "A trap."
    REFERENCE   "RFC 1215"
    ::= 7

END
"""


class TrapTypeJsonTestCase(unittest.TestCase):
    """RFC 3584 section 3: an SMIv1 trap maps to enterprise.0.specific."""

    def setUp(self):
        self.doc, self.ctx = render(TRAP_MIB)

    def testShape(self):
        self.assertEqual(
            self.doc["testTrap"],
            {
                "name": "testTrap",
                "oid": "1.3.6.1.4.1.20408.0.7",
                "class": "notificationtype",
                "objects": [{"module": "TEST-MIB", "object": "testObject"}],
                "description": "A trap.",
                "reference": "RFC 1215",
            },
        )

    def testOidIsEnterpriseZeroSpecific(self):
        self.assertEqual(self.doc["testTrap"]["oid"], "1.3.6.1.4.1.20408" + ".0." + "7")

    def testBothBackendsAgreeOnTheConvertedOid(self):
        self.assertEqual(
            tuple(int(x) for x in self.doc["testTrap"]["oid"].split(".")),
            tuple(self.ctx["testTrap"].getName()),
        )

    def testTheBracedEnterpriseFormGivesTheSameOid(self):
        # curlyBracesAroundEnterpriseInTrap is a spelling relaxation, not a
        # semantic one: the converted OID must not move.
        braced = TRAP_MIB.replace("ENTERPRISE  testId", "ENTERPRISE  { testId }")
        doc, ctx = render(braced, curlyBracesAroundEnterpriseInTrap=True)
        self.assertEqual(doc["testTrap"]["oid"], self.doc["testTrap"]["oid"])
        self.assertEqual(ctx["testTrap"].getName(), self.ctx["testTrap"].getName())

    def testTrapBecomesANotificationType(self):
        self.assertEqual(self.doc["testTrap"]["class"], "notificationtype")
        self.assertEqual(self.ctx["testTrap"].__class__.__name__, "NotificationType")


GENERIC_TRAP_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TRAP-TYPE
        FROM RFC-1215;

snmp OBJECT IDENTIFIER ::= { 1 3 6 1 2 1 11 }
acme OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 9 }

testTrap TRAP-TYPE
    ENTERPRISE  %s
    DESCRIPTION "A trap to give an OID to."
    ::= %d

END
"""

#: The six generic traps of RFC 3584 section 3.1, and the snmpTraps OID each
#: is mapped to. They are numbered from one, where the traps are from zero.
GENERIC_TRAP_OIDS = (
    (0, "1.3.6.1.6.3.1.1.5.1"),  # coldStart
    (1, "1.3.6.1.6.3.1.1.5.2"),  # warmStart
    (2, "1.3.6.1.6.3.1.1.5.3"),  # linkDown
    (3, "1.3.6.1.6.3.1.1.5.4"),  # linkUp
    (4, "1.3.6.1.6.3.1.1.5.5"),  # authenticationFailure
    (5, "1.3.6.1.6.3.1.1.5.6"),  # egpNeighborLoss
)


class GenericTrapTestCase(unittest.TestCase):
    """RFC 3584 section 2.1.2 (5): an ENTERPRISE of snmp goes to snmpTraps."""

    def assertTrapOid(self, enterprise, value, oid):
        doc, ctx = render(GENERIC_TRAP_MIB % (enterprise, value))
        self.assertEqual(doc["testTrap"]["oid"], oid)
        self.assertEqual(tuple(ctx["testTrap"].getName()), tuple(int(subId) for subId in oid.split(".")))

    def testEachGenericTrapTakesItsSnmpTrapsOid(self):
        for value, oid in GENERIC_TRAP_OIDS:
            with self.subTest(trap=value):
                self.assertTrapOid("snmp", value, oid)

    def testAnyOtherEnterpriseKeepsTheZeroInsertion(self):
        self.assertTrapOid("acme", 3, "1.3.6.1.4.1.9.0.3")

    def testSnmpPastTheSixthTrapKeepsTheZeroInsertion(self):
        # RFC 1215 section 2.1.5 says the snmp convention "is not intended to
        # provide a means to define additional standard SNMP traps", so a
        # seventh has no snmpTraps OID waiting for it. Rather than reject the
        # module or invent one, it keeps the form it already had.
        self.assertTrapOid("snmp", 6, "1.3.6.1.2.1.11.0.6")


class WithoutTextsTestCase(unittest.TestCase):
    """genTexts=False must strip every narrative clause from the document."""

    def testNotificationTextsAreOmitted(self):
        doc, _ = render(NOTIFICATION_MIB, genTexts=False)
        for symbol in ("testIdentity", "testNotify", "testNotifyGroup"):
            with self.subTest(symbol=symbol):
                self.assertNotIn("description", doc[symbol])
                self.assertNotIn("reference", doc[symbol])

    def testStructuralClausesSurviveWithoutTexts(self):
        doc, _ = render(NOTIFICATION_MIB, genTexts=False)
        self.assertEqual(doc["testNotify"]["oid"], "1.3.3")
        self.assertEqual(doc["testNotify"]["objects"], [{"module": "TEST-MIB", "object": "testObject"}])

    def testTrapTextsAreOmitted(self):
        doc, _ = render(TRAP_MIB, genTexts=False)
        self.assertNotIn("description", doc["testTrap"])
        self.assertNotIn("reference", doc["testTrap"])
        self.assertEqual(doc["testTrap"]["oid"], "1.3.6.1.4.1.20408.0.7")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
