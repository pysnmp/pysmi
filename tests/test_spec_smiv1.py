#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""SMIv1 constructs are translated as RFC 3584 says to translate them.

RFC 1155 section 3.2.3 defines the application-wide types, RFC 1212 the SMIv1
OBJECT-TYPE macro and RFC 1215 the TRAP-TYPE macro. RFC 3584 section 2 gives
the type mapping into SMIv2 and section 3.1.2 the rule for turning a trap into
a notification.

The translation is where an SMIv1 module can be silently misread, so these
assertions read what pysmi emitted rather than what pysnmp made of it. See
pysnmp/pysmi#127.
"""

import sys
import unittest

from tests.harness import render_json, render_source

TYPES_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    NetworkAddress, IpAddress, Counter, Gauge, TimeTicks, Opaque
        FROM RFC1155-SMI;

TestTypeInteger ::= INTEGER
TestTypeOctetString ::= OCTET STRING
TestTypeObjectIdentifier ::= OBJECT IDENTIFIER

TestTypeNetworkAddress ::= NetworkAddress
TestTypeIpAddress ::= IpAddress
TestTypeCounter ::= Counter
TestTypeGauge ::= Gauge
TestTypeTimeTicks ::= TimeTicks
TestTypeOpaque ::= Opaque

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
    DESCRIPTION "Test trap"
    ::= 1

END
"""

GROUP_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    Counter, IpAddress, TimeTicks
        FROM RFC1155-SMI
    DisplayString, mib-2
        FROM RFC1213-MIB
    OBJECT-TYPE
        FROM RFC-1212
    NOTIFICATION-GROUP
        FROM SNMPv2-CONF;

testNotifyOne OBJECT-TYPE
    SYNTAX INTEGER ACCESS read-only STATUS mandatory DESCRIPTION "a" ::= { 1 4 }

testSmiV1 NOTIFICATION-GROUP
    NOTIFICATIONS { testNotifyOne }
    STATUS        current
    DESCRIPTION   "A collection of test notifications."
    ::= { 1 3 }

END
"""

#: RFC 3584 section 2. The SMIv1 name on the left is what the document keeps;
#: the SMIv2 class on the right is what the generated source has to use,
#: because that is the only name pysnmp defines.
TYPE_MAPPING = (
    ("TestTypeInteger", "INTEGER", "Integer32"),
    ("TestTypeOctetString", "OCTET STRING", "OctetString"),
    ("TestTypeObjectIdentifier", "OBJECT IDENTIFIER", "ObjectIdentifier"),
    ("TestTypeIpAddress", "IpAddress", "IpAddress"),
    ("TestTypeCounter", "Counter", "Counter32"),
    ("TestTypeGauge", "Gauge", "Gauge32"),
    ("TestTypeTimeTicks", "TimeTicks", "TimeTicks"),
    ("TestTypeOpaque", "Opaque", "Opaque"),
)


class ApplicationTypeTestCase(unittest.TestCase):
    """RFC 1155 section 3.2.3 types, mapped by RFC 3584 section 2."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(TYPES_MIB)
        cls.source = render_source(TYPES_MIB)

    def testTheDocumentKeepsTheNameTheMibWrote(self):
        # The document describes the module that was compiled, so an SMIv1
        # module stays recognisably SMIv1 in it.
        for symbol, written, _ in TYPE_MAPPING:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["type"]["type"], written)

    def testTheEmittedClassIsTheSmiV2Equivalent(self):
        for symbol, _, klass in TYPE_MAPPING:
            with self.subTest(symbol=symbol):
                self.assertIn(f"class {symbol}({klass}):", self.source)

    def testNetworkAddressBecomesAnIpAddress(self):
        # RFC 1155 section 3.2.3.1 defines NetworkAddress as a CHOICE with
        # IpAddress as its only alternative, so the two are the same type.
        self.assertEqual(self.doc["TestTypeNetworkAddress"]["type"]["type"], "IpAddress")
        self.assertIn("class TestTypeNetworkAddress(IpAddress):", self.source)

    def testTheThirtyTwoBitWidthIsMadeExplicit(self):
        # Counter and Gauge are 32-bit in RFC 1155 but unnamed as such. The
        # SMIv2 names say the width, and losing it would widen the type.
        self.assertIn("class TestTypeCounter(Counter32):", self.source)
        self.assertIn("class TestTypeGauge(Gauge32):", self.source)


class ObjectTypeTestCase(unittest.TestCase):
    """RFC 1212: the SMIv1 OBJECT-TYPE macro spells two clauses differently."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(TRAP_MIB)["testObject"]
        cls.source = render_source(TRAP_MIB)

    def testAccessIsCarriedWhereMaxAccessWouldBe(self):
        # RFC 1212 writes ACCESS where RFC 2578 section 7.3 writes MAX-ACCESS.
        # They are the same clause, so the document uses the one key.
        self.assertEqual(self.doc["maxaccess"], "read-only")
        self.assertIn('testObject = MibScalar((1, 4), Integer32()).setMaxAccess("readonly")', self.source)

    def testTheSmiV1StatusIsKeptRatherThanTranslated(self):
        # RFC 1212 has "mandatory", which RFC 2578 section 7.4 does not. RFC
        # 3584 section 2 maps it to "current", but nothing downstream needs the
        # translation and rewriting it here would hide what the MIB said.
        self.assertEqual(self.doc["status"], "mandatory")
        self.assertIn("testObject.setStatus('mandatory')", self.source)


class TrapTypeTestCase(unittest.TestCase):
    """RFC 1215 TRAP-TYPE, mapped by RFC 3584 section 3.1.2."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(TRAP_MIB)["testTrap"]
        cls.source = render_source(TRAP_MIB)

    def testATrapBecomesANotification(self):
        self.assertEqual(self.doc["class"], "notificationtype")
        self.assertIn("testTrap = NotificationType(", self.source)

    def testTheOidIsTheEnterpriseThenZeroThenTheSpecificTrapNumber(self):
        # RFC 3584 section 3.1.2: the notification's OID is the ENTERPRISE
        # value, a zero, and the trap number from the value assignment. The
        # zero is what keeps a trap from colliding with a subtree of the
        # enterprise's own objects.
        self.assertEqual(self.doc["oid"], "1.3.0.1")
        self.assertIn("testTrap = NotificationType((1, 3) + (0,1))", self.source)

    def testVariablesBecomeTheNotificationObjects(self):
        # RFC 1215 calls them VARIABLES; RFC 2578 section 8 calls the same list
        # OBJECTS.
        self.assertEqual(self.doc["objects"], [{"module": "TEST-MIB", "object": "testObject"}])
        self.assertIn('.setObjects(("TEST-MIB", "testObject"))', self.source)

    def testTheDescriptionSurvivesTheTranslation(self):
        self.assertEqual(self.doc["description"], "Test trap")
        self.assertIn("if mibBuilder.loadTexts: testTrap.setDescription('Test trap')", self.source)


class MixedDialectTestCase(unittest.TestCase):
    """An SMIv1 module may import SMIv2 macros, and still has to compile."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(GROUP_MIB)
        cls.source = render_source(GROUP_MIB)

    def testTheSmiV2MacroIsHonouredInAnSmiV1Module(self):
        self.assertEqual(self.doc["testSmiV1"]["class"], "notificationgroup")
        self.assertEqual(self.doc["testSmiV1"]["oid"], "1.3")
        self.assertIn("testSmiV1 = NotificationGroup((1, 3))", self.source)

    def testTheSmiV1ModulesAreRewrittenToTheirSmiV2Equivalents(self):
        # RFC 3584 section 2 gives the SMIv2 module that replaces each SMIv1
        # one. The generated module has to import from the replacement, because
        # the SMIv1 modules are the ones that no longer exist.
        self.assertEqual(
            sorted(k for k in self.doc["imports"] if k != "class"),
            ["SNMPv2-CONF", "SNMPv2-SMI", "SNMPv2-TC"],
        )
        for gone in ("RFC1155-SMI", "RFC1213-MIB", "RFC-1212"):
            with self.subTest(module=gone):
                self.assertNotIn(gone, self.doc["imports"])
                self.assertNotIn(f'"{gone}"', self.source)

    def testEachRewrittenSymbolLandsInTheModuleThatNowDefinesIt(self):
        self.assertIn("mib-2", self.doc["imports"]["SNMPv2-SMI"])
        self.assertIn("DisplayString", self.doc["imports"]["SNMPv2-TC"])
        self.assertIn("OBJECT-TYPE", self.doc["imports"]["SNMPv2-SMI"])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
