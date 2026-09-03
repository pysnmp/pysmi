#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""DEFVAL means something different for every syntax it is written against.

RFC 2578 section 7.9 lists the literal forms. Hexadecimal and binary strings
have their own file; this one covers the rest of the matrix and asserts the
value that reaches each backend, not merely that the MIB compiled.

See pysnmp/pysmi#87.
"""

import sys
import unittest

from tests.harness import render, render_json
from tests.mibs import SNMPV2_SMI, SNMPV2_TC

DEPS = (SNMPV2_SMI, SNMPV2_TC)

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, Unsigned32, TimeTicks, IpAddress
        FROM SNMPv2-SMI
    DisplayString
        FROM SNMPv2-TC;

anchor OBJECT IDENTIFIER ::= { 1 3 9 }

testObject OBJECT-TYPE
    SYNTAX      %s
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The object under test."
    DEFVAL      { %s }
    ::= { 1 3 1 }

END
"""


def default(syntax, defval):
    """Return the JSON default and the pysnmp syntax for one DEFVAL."""
    doc, ctx = render(MIB % (syntax, defval), deps=DEPS)
    return doc["testObject"].get("default"), ctx["testObject"].getSyntax()


class NumericDefValTestCase(unittest.TestCase):
    """RFC 2578 section 7.9: a numeric default is written as a plain integer."""

    def testNegativeInteger(self):
        json, syntax = default("Integer32 (-100..100)", "-20")
        self.assertEqual(json, {"value": -20, "format": "decimal"})
        self.assertEqual(syntax, -20)

    def testUnsignedUpperBound(self):
        json, syntax = default("Unsigned32", "4294967295")
        self.assertEqual(json, {"value": 4294967295, "format": "decimal"})
        self.assertEqual(syntax, 4294967295)

    def testTimeTicks(self):
        json, syntax = default("TimeTicks", "100")
        self.assertEqual(json, {"value": 100, "format": "decimal"})
        self.assertEqual(syntax, 100)

    def testZero(self):
        json, syntax = default("Integer32", "0")
        self.assertEqual(json, {"value": 0, "format": "decimal"})
        self.assertEqual(syntax, 0)


class ApplicationTypeDefValTestCase(unittest.TestCase):
    """Application types resolve to their base before the default is read."""

    def testIpAddressTakesAHexadecimalDefault(self):
        json, syntax = default("IpAddress", "'C0000201'H")
        self.assertEqual(json, {"value": "C0000201", "format": "hex"})
        self.assertEqual(syntax.prettyPrint(), "192.0.2.1")

    def testTextualConventionTakesAStringDefault(self):
        json, syntax = default("DisplayString", '"hello"')
        self.assertEqual(json, {"value": "hello", "format": "string"})
        self.assertEqual(syntax, b"hello")

    def testSubTypedTextualConventionKeepsBothConstraints(self):
        json, syntax = default("DisplayString (SIZE(0..32))", '"hello"')
        self.assertEqual(json, {"value": "hello", "format": "string"})
        self.assertEqual(syntax, b"hello")
        consts = repr(syntax.subtypeSpec)
        self.assertIn("consts 0, 32", consts)
        self.assertIn("consts 0, 255", consts)


class BitsDefValTestCase(unittest.TestCase):
    """A BITS default names the bits that are set, and sets no others."""

    def bits(self, defval):
        syntax = "BITS { first(0), second(1), fourth(3) }"
        json, value = default(syntax, defval)
        return json, bytes(value).hex()

    def testNamedBitsAreSet(self):
        json, octets = self.bits("{ first, fourth }")
        self.assertEqual(json["value"]["bits"], {"first": 0, "fourth": 3})
        self.assertEqual(octets, "90")

    def testASingleBitIsSet(self):
        json, octets = self.bits("{ second }")
        self.assertEqual(json["value"]["bits"], {"second": 1})
        self.assertEqual(octets, "40")

    def testTheTypeKeepsEveryBitItDeclared(self):
        # The default selects bits; it must not redefine the enumeration.
        _, ctx = render(MIB % ("BITS { first(0), second(1), fourth(3) }", "{ first }"), deps=DEPS)
        named = ctx["testObject"].getSyntax().namedValues
        self.assertEqual(sorted(named.items()), [("first", 0), ("fourth", 3), ("second", 1)])


class OidDefValTestCase(unittest.TestCase):
    """RFC 2578 section 7.9: an OID default names an object, not a numeric OID."""

    def testDefaultNamedByIdentifierResolves(self):
        json, syntax = default("OBJECT IDENTIFIER", "anchor")
        self.assertEqual(json, {"value": "(1, 3, 9)", "format": "oid"})
        self.assertEqual(syntax.prettyPrint(), "1.3.9")

    def testNumericNotationIsDroppedRatherThanRejected(self):
        # Not valid SMI, but MIBs in the wild write it. pysmi swallows the
        # clause instead of failing the parse. See pysnmp/pysmi#87.
        doc = render_json(MIB % ("OBJECT IDENTIFIER", "{ 1 3 6 }"), deps=DEPS)
        self.assertNotIn("default", doc["testObject"])


class EnumerationDefValTestCase(unittest.TestCase):
    """An enumeration default is written as a label and emitted as its number."""

    def testLabelBecomesItsNumber(self):
        json, syntax = default("INTEGER { up(1), down(2) }", "down")
        self.assertEqual(json, {"value": "down", "format": "enum"})
        self.assertEqual(syntax, 2)

    def testZeroValuedLabelSurvives(self):
        json, syntax = default("INTEGER { off(0), on(1) }", "off")
        self.assertEqual(json, {"value": "off", "format": "enum"})
        self.assertEqual(syntax, 0)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
