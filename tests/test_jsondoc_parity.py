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

import json
import sys
import unittest

from pysnmp.smi.builder import MibBuilder

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory


def render(mib, genTexts=True):
    """Compile *mib* through both backends, returning the JSON dict and pysnmp scope."""
    ast = parserFactory()().parse(mib)[0]
    mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=genTexts)

    _, doc = JsonCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=genTexts)

    _, pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=genTexts)
    mibBuilder = MibBuilder()
    mibBuilder.loadTexts = genTexts
    ctx = {"mibBuilder": mibBuilder}
    exec(compile(pycode, "test", "exec"), ctx, ctx)

    return json.loads(doc), ctx


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

    def testTrapBecomesANotificationType(self):
        self.assertEqual(self.doc["testTrap"]["class"], "notificationtype")
        self.assertEqual(self.ctx["testTrap"].__class__.__name__, "NotificationType")


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
