#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A generated module loads under pysnmp and its public API accepts it.

This is the only file that reads a pysmi artifact back off a pysnmp object, and
it is deliberately thin. It answers one question -- does the module we emit
still load and work in the consumer it is emitted for -- and it answers no
question about correctness. Whether the emitted output matches the SMI
specifications is settled in the ``test_spec_*`` files, against RFC 2578, RFC
2579, RFC 2580 and RFC 3584, by reading the output itself.

Nothing here may become the oracle for a clause. If a pysnmp release changes an
accessor, this file goes red and pysmi is not at fault, which is why it is
marked ``pysnmp_consumer`` and does not gate CI. See pysnmp/pysmi#127.
"""

import sys
import unittest

import pytest

from pysmi.codegen import PySnmpCodeGen
from tests.harness import render_pysnmp
from tests.test_standard_corpus import LOAD_ORDER, compiled, documents

pytestmark = pytest.mark.pysnmp_consumer

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-IDENTITY, NOTIFICATION-TYPE, OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

testModule MODULE-IDENTITY
    LAST-UPDATED "200001100000Z"
    ORGANIZATION "AgentX Working Group"
    CONTACT-INFO "WG-email: agentx@example.com"
    DESCRIPTION  "Module."
    REVISION     "200001100000Z"
    DESCRIPTION  "Initial version."
    ::= { 1 3 }

TestConvention ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "1x:"
    STATUS       current
    DESCRIPTION  "A convention."
    SYNTAX       OCTET STRING

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "Identity."
    REFERENCE   "ABC"
    ::= { testModule 1 }

testScalar OBJECT-TYPE
    SYNTAX      Integer32 (0..7)
    UNITS       "seconds"
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "Scalar."
    DEFVAL      { 3 }
    ::= { testModule 2 }

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Table."
    ::= { testModule 3 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Row."
    INDEX       { testIndex, IMPLIED testName }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE { testIndex Integer32, testName OCTET STRING }

testIndex OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "Index column."
    ::= { testEntry 1 }

testName OBJECT-TYPE
    SYNTAX      OCTET STRING
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "Name column."
    ::= { testEntry 2 }

testNotification NOTIFICATION-TYPE
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "Notification."
    ::= { testModule 4 }

testObjectGroup OBJECT-GROUP
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "Object group."
    ::= { testModule 5 }

testNotificationGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testNotification }
    STATUS        current
    DESCRIPTION   "Notification group."
    ::= { testModule 6 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "Compliance."
    MODULE
        MANDATORY-GROUPS { testObjectGroup }
    ::= { testModule 7 }

testCapability AGENT-CAPABILITIES
    PRODUCT-RELEASE "Release."
    STATUS          current
    DESCRIPTION     "Capabilities."
    SUPPORTS        TEST-MIB
    INCLUDES        { testObjectGroup }
    ::= { testModule 8 }

END
"""

#: Every construct the pysnmp backend emits, and the class pysnmp builds for it.
CONSTRUCTS = (
    ("testModule", "ModuleIdentity"),
    ("testIdentity", "ObjectIdentity"),
    ("testScalar", "MibScalar"),
    ("testTable", "MibTable"),
    ("testEntry", "MibTableRow"),
    ("testIndex", "MibTableColumn"),
    ("testNotification", "NotificationType"),
    ("testObjectGroup", "ObjectGroup"),
    ("testNotificationGroup", "NotificationGroup"),
    ("testCompliance", "ModuleCompliance"),
    ("testCapability", "AgentCapabilities"),
)


class LoadTestCase(unittest.TestCase):
    """The generated module executes against a MibBuilder."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = render_pysnmp(MIB)

    def testEveryConstructBuildsItsObject(self):
        for symbol, klass in CONSTRUCTS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, self.ctx)
                self.assertEqual(self.ctx[symbol].__class__.__name__, klass)

    def testATextualConventionBuildsItsClass(self):
        self.assertEqual(self.ctx["TestConvention"]().getDisplayHint(), "1x:")

    def testTheModuleAlsoLoadsWithoutTexts(self):
        # The narrative setters are emitted behind a guard, so a module built
        # without them has to remain loadable.
        ctx = render_pysnmp(MIB, genTexts=False)
        for symbol, _ in CONSTRUCTS:
            with self.subTest(symbol=symbol):
                self.assertIn(symbol, ctx)


class PublicApiTestCase(unittest.TestCase):
    """pysnmp's accessors return what the module was built with."""

    @classmethod
    def setUpClass(cls):
        cls.ctx = render_pysnmp(MIB)

    def testAnObjectKnowsItsName(self):
        self.assertEqual(self.ctx["testScalar"].getName(), (1, 3, 2))

    def testAScalarCarriesItsSyntaxAndDefault(self):
        self.assertEqual(self.ctx["testScalar"].getSyntax(), 3)
        self.assertEqual(self.ctx["testScalar"].getUnits(), "seconds")

    def testARowKnowsItsIndexColumns(self):
        self.assertEqual(
            self.ctx["testEntry"].getIndexNames(),
            ((0, "TEST-MIB", "testIndex"), (1, "TEST-MIB", "testName")),
        )

    def testTheRowEncodesAnInstanceIdentifier(self):
        # The encoding itself belongs to pysnmp; that it agrees with the
        # section 7.7 model in test_spec_index is what this checks.
        self.assertEqual(self.ctx["testEntry"].getInstIdFromIndices(7, b"ab"), (7, 97, 98))

    def testANotificationKnowsItsObjects(self):
        self.assertEqual(self.ctx["testNotification"].getObjects(), (("TEST-MIB", "testScalar"),))

    def testTheModuleIdentityCarriesItsRevisions(self):
        self.assertEqual(self.ctx["testModule"].getRevisions(), ("2000-01-10 00:00",))


class CorpusLoadTestCase(unittest.TestCase):
    """The real-MIB corpus loads into one builder.

    A missing guard, or a call pysnmp does not implement, leaves source that
    compiles and then fails at load. Only running it finds that. The corpus
    fixtures live in tests/test_standard_corpus.py, which asserts on the
    documents and the sources themselves.
    """

    def testEveryGeneratedModuleLoadsIntoOneBuilder(self):
        from pysnmp.smi.builder import MibBuilder

        _, written = compiled(PySnmpCodeGen)

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True
        ctx = {"mibBuilder": mibBuilder}

        for name in LOAD_ORDER:
            with self.subTest(module=name):
                exec(compile(written[name], name, "exec"), ctx, ctx)

    def testTheLoadedSymbolsCarryTheOidsTheJsonDocumentReports(self):
        from pysnmp.smi.builder import MibBuilder

        _, written = compiled(PySnmpCodeGen)
        docs = documents()

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True
        ctx = {"mibBuilder": mibBuilder}
        for name in LOAD_ORDER:
            exec(compile(written[name], name, "exec"), ctx, ctx)

        compared = 0
        for name in LOAD_ORDER:
            for symbol, node in docs[name].items():
                if not isinstance(node, dict) or "oid" not in node:
                    continue
                built = ctx.get(symbol)
                if built is None or not hasattr(built, "getName"):
                    continue
                with self.subTest(module=name, symbol=symbol):
                    self.assertEqual(".".join(str(x) for x in built.getName()), node["oid"])
                compared += 1

        self.assertGreater(compared, 200)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
