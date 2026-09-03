#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The module-level macros are emitted as RFC 2578 defines them.

RFC 2578 section 3 gives the shape of an information module and its IMPORTS,
section 5 the MODULE-IDENTITY macro, section 6 OBJECT-IDENTITY and section 8
NOTIFICATION-TYPE.

Assertions read the JSON document and the generated source. See
pysnmp/pysmi#127 for why they do not read them back off a pysnmp object.
"""

import sys
import unittest

from tests.harness import render_json, render_source

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-IDENTITY, NOTIFICATION-TYPE, OBJECT-TYPE, Unsigned32, Integer32, mib-2
        FROM SNMPv2-SMI
    SnmpAdminString
        FROM SNMP-FRAMEWORK-MIB;

testModule MODULE-IDENTITY
    LAST-UPDATED "200001100000Z"
    ORGANIZATION "AgentX Working Group"
    CONTACT-INFO "WG-email:   agentx@dorothy.bmc.com"
    DESCRIPTION  "This is the MIB module for the SNMP"
    REVISION     "200001100000Z"
    DESCRIPTION  "Initial version published as RFC 2742."
    ::= { 1 3 }

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "Initial version"
    REFERENCE   "ABC"
    ::= { 1 4 }

testScalar OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS current DESCRIPTION "s" ::= { 1 5 }

testOther OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS current DESCRIPTION "o" ::= { 1 6 }

testNotificationType NOTIFICATION-TYPE
    OBJECTS     { testScalar, testOther }
    STATUS      current
    DESCRIPTION "A collection of test notification types."
    REFERENCE   "NT reference"
    ::= { 1 7 }

testValue1 OBJECT IDENTIFIER ::= { 1 9 }
testValue2 OBJECT IDENTIFIER ::= { testValue1 3 }
testValue3 OBJECT IDENTIFIER ::= { 1 3 6 1 2 }

END
"""


class ModuleIdentityTestCase(unittest.TestCase):
    """RFC 2578 section 5: MODULE-IDENTITY."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testModule"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "moduleidentity")
        self.assertEqual(self.doc["oid"], "1.3")
        self.assertEqual(self.doc["lastupdated"], "2000-01-10 00:00")
        self.assertEqual(self.doc["organization"], "AgentX Working Group")
        self.assertEqual(self.doc["contactinfo"], "WG-email: agentx@dorothy.bmc.com")
        self.assertEqual(self.doc["description"], "This is the MIB module for the SNMP")

    def testRunsOfWhitespaceInATextClauseAreCollapsed(self):
        # RFC 2578 section 3.1.1 makes these clauses free-form text laid out to
        # suit the MIB author, so the layout is not part of the value. The
        # CONTACT-INFO above is written with the columns lined up.
        self.assertIn("WG-email:   agentx", MIB)
        self.assertEqual(self.doc["contactinfo"], "WG-email: agentx@dorothy.bmc.com")

    def testEachRevisionKeepsItsOwnDescription(self):
        # Section 5 pairs every REVISION with the DESCRIPTION that follows it.
        # Two parallel lists would lose the pairing the moment one is filtered.
        self.assertEqual(
            self.doc["revisions"],
            [{"revision": "2000-01-10 00:00", "description": "Initial version published as RFC 2742."}],
        )

    def testTheModuleIdentityIsExportedUnderItsWellKnownAlias(self):
        # pysnmp finds the module's identity by this name rather than by
        # scanning for a ModuleIdentity instance.
        self.assertIn("PYSNMP_MODULE_ID=testModule", self.source.rsplit("exportSymbols(", 1)[1])

    def testTheRevisionsAreNotGuardedButTheirDescriptionsAre(self):
        # A revision date says which version of the module this is, so it is
        # structural. The prose attached to it is not.
        self.assertIn("testModule.setRevisions(('2000-01-10 00:00',))", self.source)
        self.assertIn(
            "    if mibBuilder.loadTexts: "
            "testModule.setRevisionsDescriptions(('Initial version published as RFC 2742.',))",
            self.source,
        )

    def testTheRevisionDescriptionsAreGuardedForOlderPysnmp(self):
        # setRevisionsDescriptions arrived after pysnmp 4.4.0.
        self.assertIn(
            "if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):\n"
            "    if mibBuilder.loadTexts: testModule.setRevisionsDescriptions(",
            self.source,
        )


class ObjectIdentityTestCase(unittest.TestCase):
    """RFC 2578 section 6: OBJECT-IDENTITY."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testIdentity"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "objectidentity")
        self.assertEqual(self.doc["oid"], "1.4")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "Initial version")
        self.assertEqual(self.doc["reference"], "ABC")

    def testTheEmittedObjectIsAnObjectIdentity(self):
        self.assertIn("testIdentity = ObjectIdentity((1, 4))", self.source)

    def testItsReferenceIsEmittedBehindTheTextGuard(self):
        self.assertIn("if mibBuilder.loadTexts: testIdentity.setReference('ABC')", self.source)


class NotificationTypeTestCase(unittest.TestCase):
    """RFC 2578 section 8: NOTIFICATION-TYPE."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["testNotificationType"]
        cls.source = render_source(MIB)

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["class"], "notificationtype")
        self.assertEqual(self.doc["oid"], "1.7")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "A collection of test notification types.")
        self.assertEqual(self.doc["reference"], "NT reference")

    def testTheObjectsAreNamedWithTheirModuleInClauseOrder(self):
        # Section 8 makes OBJECTS an ordered list: it fixes the order of the
        # variable bindings in the notification that gets sent.
        self.assertEqual(
            self.doc["objects"],
            [
                {"module": "TEST-MIB", "object": "testScalar"},
                {"module": "TEST-MIB", "object": "testOther"},
            ],
        )

    def testTheEmittedObjectsKeepThatOrder(self):
        self.assertIn(
            "testNotificationType = NotificationType((1, 7)).setObjects("
            '("TEST-MIB", "testScalar"), ("TEST-MIB", "testOther"))',
            self.source,
        )

    def testSetObjectsIsNotGuarded(self):
        # The variable bindings are what the notification carries, so a module
        # loaded without texts still needs them.
        line = next(line for line in self.source.splitlines() if line.startswith("testNotificationType ="))
        self.assertIn(".setObjects(", line)


class ValueDeclarationTestCase(unittest.TestCase):
    """RFC 2578 section 4: an OBJECT IDENTIFIER value declaration."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)
        cls.source = render_source(MIB)

    def testAnAbsoluteOidIsCarriedWhole(self):
        self.assertEqual(self.doc["testValue3"]["oid"], "1.3.6.1.2")
        self.assertIn("testValue3 = MibIdentifier((1, 3, 6, 1, 2))", self.source)

    def testARelativeOidIsResolvedAgainstItsParent(self):
        # Section 4 lets a declaration name its parent rather than repeating the
        # prefix, and the emitted OID has to be the resolved one.
        self.assertEqual(self.doc["testValue1"]["oid"], "1.9")
        self.assertEqual(self.doc["testValue2"]["oid"], "1.9.3")
        self.assertIn("testValue2 = MibIdentifier((1, 9, 3))", self.source)

    def testAPlainValueIsEmittedAsAMibIdentifier(self):
        # It names a node and nothing else: it has no SYNTAX and no access, so
        # it must not become a scalar.
        self.assertIn("testValue1 = MibIdentifier((1, 9))", self.source)
        self.assertNotIn("testValue1 = MibScalar", self.source)


class ImportsTestCase(unittest.TestCase):
    """RFC 2578 section 3.2: the IMPORTS clause."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)
        cls.source = render_source(MIB)

    def testEveryImportedModuleIsRecorded(self):
        # SNMPv2-CONF and SNMPv2-TC are not written in the MIB. Both backends
        # add them because the generated module always imports from them, so a
        # consumer resolving dependencies has to be told.
        self.assertEqual(
            sorted(k for k in self.doc["imports"] if k != "class"),
            ["SNMP-FRAMEWORK-MIB", "SNMPv2-CONF", "SNMPv2-SMI", "SNMPv2-TC"],
        )

    def testAnImportedSymbolIsRecordedUnderItsModule(self):
        self.assertIn("SnmpAdminString", self.doc["imports"]["SNMP-FRAMEWORK-MIB"])
        self.assertIn("mib-2", self.doc["imports"]["SNMPv2-SMI"])

    def testTheEmittedModuleImportsTheSymbolItWasGiven(self):
        self.assertIn(
            'SnmpAdminString, = mibBuilder.importSymbols("SNMP-FRAMEWORK-MIB", "SnmpAdminString")',
            self.source,
        )

    def testASymbolWithAHyphenIsNotEmittedAsAName(self):
        # "mib-2" is a legal descriptor and an illegal Python identifier, so it
        # can only be imported for its side effect. Emitting it as a target
        # would not compile.
        self.assertNotIn("mib-2 =", self.source)
        self.assertNotIn('"mib-2"', self.source.rsplit("exportSymbols(", 1)[1])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
