#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import re
import sys
import unittest

from pysnmp.smi.builder import MibBuilder

from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory

# RFC 2578 and RFC 2580 permit a REFERENCE clause on every macro below, but
# pysnmp only implements setReference() on some of the classes they compile
# to. Emitting the call for the rest yields a module that raises
# AttributeError when loaded with loadTexts=True.
SUPPORTED = {
    "testObjectIdentity": "RFC 2578 Section 4",
    "testObjectType": "RFC 2578 Section 7",
    "testNotificationType": "RFC 2578 Section 8",
    "testAgentCapabilities": "RFC 2580 Section 6",
}

UNSUPPORTED = ("testObjectGroup", "testNotificationGroup", "testModuleCompliance")


class ReferenceTestCase(unittest.TestCase):
    """
    TEST-MIB DEFINITIONS ::= BEGIN
    IMPORTS
      OBJECT-TYPE, NOTIFICATION-TYPE, OBJECT-IDENTITY, Integer32
        FROM SNMPv2-SMI
      OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

    testObjectIdentity OBJECT-IDENTITY
        STATUS          current
        DESCRIPTION     "Object identity."
        REFERENCE       "RFC 2578 Section 4"
     ::= { 1 3 1 }

    testObjectType OBJECT-TYPE
        SYNTAX          Integer32
        MAX-ACCESS      read-only
        STATUS          current
        DESCRIPTION     "Object type."
        REFERENCE       "RFC 2578 Section 7"
     ::= { 1 3 2 }

    testNotificationType NOTIFICATION-TYPE
        OBJECTS         { testObjectType }
        STATUS          current
        DESCRIPTION     "Notification type."
        REFERENCE       "RFC 2578 Section 8"
     ::= { 1 3 3 }

    testObjectGroup OBJECT-GROUP
        OBJECTS         { testObjectType }
        STATUS          current
        DESCRIPTION     "Object group."
        REFERENCE       "RFC 2580 Section 3"
     ::= { 1 3 4 }

    testNotificationGroup NOTIFICATION-GROUP
        NOTIFICATIONS   { testNotificationType }
        STATUS          current
        DESCRIPTION     "Notification group."
        REFERENCE       "RFC 2580 Section 4"
     ::= { 1 3 5 }

    testModuleCompliance MODULE-COMPLIANCE
        STATUS          current
        DESCRIPTION     "Module compliance."
        REFERENCE       "RFC 2580 Section 5"
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

    def setUp(self):
        ast = parserFactory()().parse(self.__class__.__doc__)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=True)
        self.mibInfo, self.pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=True)
        codeobj = compile(self.pycode, "test", "exec")

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True

        self.ctx = {"mibBuilder": mibBuilder}

        exec(codeobj, self.ctx, self.ctx)

    def testReferenceOnSupportedClasses(self):
        for symbol, reference in SUPPORTED.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.ctx[symbol].getReference(), reference, "bad REFERENCE")

    def testNoReferenceOnUnsupportedClasses(self):
        for symbol in UNSUPPORTED:
            with self.subTest(symbol=symbol):
                self.assertNotIn(
                    f"{symbol}.setReference(",
                    self.pycode,
                    "setReference() emitted for a class that does not implement it",
                )

    def testEveryReferenceCallIsGuarded(self):
        for line in self.pycode.splitlines():
            if ".setReference(" in line:
                self.assertTrue(
                    line.startswith("if mibBuilder.loadTexts: "),
                    f"unguarded setReference(): {line}",
                )

    def testReferenceCallCount(self):
        self.assertEqual(len(re.findall(r"\.setReference\(", self.pycode)), len(SUPPORTED))


class ReferenceNoTextsTestCase(ReferenceTestCase):
    """Same module compiled without texts; see the parent for the source."""

    __doc__ = ReferenceTestCase.__doc__

    def setUp(self):
        ast = parserFactory()().parse(self.__class__.__doc__)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=False)
        self.mibInfo, self.pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=False)
        codeobj = compile(self.pycode, "test", "exec")

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = False

        self.ctx = {"mibBuilder": mibBuilder}

        exec(codeobj, self.ctx, self.ctx)

    def testReferenceOnSupportedClasses(self):
        for symbol in SUPPORTED:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.ctx[symbol].getReference(), "", "REFERENCE set without genTexts")

    def testReferenceCallCount(self):
        self.assertEqual(len(re.findall(r"\.setReference\(", self.pycode)), 0)


class TrapTypeReferenceTestCase(unittest.TestCase):
    """
    TEST-MIB DEFINITIONS ::= BEGIN
    IMPORTS
      TRAP-TYPE
        FROM RFC-1215

      OBJECT-TYPE
        FROM RFC1155-SMI;

    testId  OBJECT IDENTIFIER ::= { 1 3 }

    testObject OBJECT-TYPE
        SYNTAX          INTEGER
        MAX-ACCESS      accessible-for-notify
        STATUS          current
        DESCRIPTION     "Test object"
     ::= { 1 3 }

    testTrap TRAP-TYPE
        ENTERPRISE  testId
        VARIABLES   { testObject }
        DESCRIPTION "Trap type."
        REFERENCE   "RFC 1215"
     ::= 1

    END
    """

    def setUp(self):
        ast = parserFactory()().parse(self.__class__.__doc__)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=True)
        self.mibInfo, self.pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=True)
        codeobj = compile(self.pycode, "test", "exec")

        mibBuilder = MibBuilder()
        mibBuilder.loadTexts = True

        self.ctx = {"mibBuilder": mibBuilder}

        exec(codeobj, self.ctx, self.ctx)

    def testTrapTypeReference(self):
        self.assertEqual(self.ctx["testTrap"].getReference(), "RFC 1215", "bad REFERENCE")

    def testTrapTypeReferenceIsGuarded(self):
        for line in self.pycode.splitlines():
            if ".setReference(" in line:
                self.assertTrue(
                    line.startswith("if mibBuilder.loadTexts: "),
                    f"unguarded setReference(): {line}",
                )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
