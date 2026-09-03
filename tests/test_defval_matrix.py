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

from tests.harness import render_json, render_source
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
    """Return the JSON default and the emitted syntax expression for one DEFVAL."""
    mib = MIB % (syntax, defval)
    line = next(x for x in render_source(mib, deps=DEPS).splitlines() if x.startswith("testObject ="))
    return render_json(mib, deps=DEPS)["testObject"].get("default"), line


class NumericDefValTestCase(unittest.TestCase):
    """RFC 2578 section 7.9: a numeric default is written as a plain integer."""

    def testNegativeInteger(self):
        json, emitted = default("Integer32 (-100..100)", "-20")
        self.assertEqual(json, {"value": -20, "format": "decimal"})
        self.assertIn(".clone(-20)", emitted)

    def testUnsignedUpperBound(self):
        json, emitted = default("Unsigned32", "4294967295")
        self.assertEqual(json, {"value": 4294967295, "format": "decimal"})
        self.assertIn("Unsigned32().clone(4294967295)", emitted)

    def testTimeTicks(self):
        json, emitted = default("TimeTicks", "100")
        self.assertEqual(json, {"value": 100, "format": "decimal"})
        self.assertIn("TimeTicks().clone(100)", emitted)

    def testZero(self):
        json, emitted = default("Integer32", "0")
        self.assertEqual(json, {"value": 0, "format": "decimal"})
        self.assertIn("Integer32().clone(0)", emitted)


class ApplicationTypeDefValTestCase(unittest.TestCase):
    """Application types resolve to their base before the default is read."""

    def testIpAddressTakesAHexadecimalDefault(self):
        json, emitted = default("IpAddress", "'C0000201'H")
        self.assertEqual(json, {"value": "C0000201", "format": "hex"})
        # The octets stay hexadecimal: a dotted-quad written here would have
        # to be re-parsed, and IpAddress().clone("192.0.2.1") means something
        # else to pysnmp than the four octets the MIB gave.
        self.assertIn('IpAddress().clone(hexValue="C0000201")', emitted)

    def testTextualConventionTakesAStringDefault(self):
        json, emitted = default("DisplayString", '"hello"')
        self.assertEqual(json, {"value": "hello", "format": "string"})
        self.assertIn("DisplayString().clone('hello')", emitted)

    def testSubTypedTextualConventionKeepsBothConstraints(self):
        json, emitted = default("DisplayString (SIZE(0..32))", '"hello"')
        self.assertEqual(json, {"value": "hello", "format": "string"})
        # .subtype() intersects the refinement with the convention's own
        # SIZE(0..255); the default is cloned onto the result, not onto the base.
        self.assertIn(
            "DisplayString().subtype(subtypeSpec=ValueSizeConstraint(0, 32)).clone('hello')",
            emitted,
        )


class BitsDefValTestCase(unittest.TestCase):
    """A BITS default names the bits that are set, and sets no others."""

    def bits(self, defval):
        return default("BITS { first(0), second(1), fourth(3) }", defval)

    def testNamedBitsAreSet(self):
        json, emitted = self.bits("{ first, fourth }")
        self.assertEqual(json["value"]["bits"], {"first": 0, "fourth": 3})
        self.assertIn(".clone(('first', 'fourth',))", emitted)

    def testASingleBitIsSet(self):
        json, emitted = self.bits("{ second }")
        self.assertEqual(json["value"]["bits"], {"second": 1})
        self.assertIn(".clone(('second',))", emitted)

    def testTheDefaultIsNamedRatherThanEncoded(self):
        # RFC 2578 section 7.1.4 numbers the bits, so the octets a set of them
        # encodes to are fixed. Emitting the labels leaves that encoding to the
        # consumer instead of baking one side's arithmetic into the module.
        _, emitted = self.bits("{ first, fourth }")
        self.assertNotIn("hexValue", emitted)

    def testTheTypeKeepsEveryBitItDeclared(self):
        # The default selects bits; it must not redefine the enumeration.
        _, emitted = self.bits("{ first }")
        self.assertIn('NamedValues(("first", 0), ("second", 1), ("fourth", 3))', emitted)


class OidDefValTestCase(unittest.TestCase):
    """RFC 2578 section 7.9: an OID default names an object, not a numeric OID."""

    def testDefaultNamedByIdentifierResolves(self):
        json, emitted = default("OBJECT IDENTIFIER", "anchor")
        self.assertEqual(json, {"value": "(1, 3, 9)", "format": "oid"})
        self.assertIn("ObjectIdentifier().clone((1, 3, 9))", emitted)

    def testNumericNotationIsDroppedRatherThanRejected(self):
        # Not valid SMI, but MIBs in the wild write it. pysmi swallows the
        # clause instead of failing the parse. See pysnmp/pysmi#87.
        doc = render_json(MIB % ("OBJECT IDENTIFIER", "{ 1 3 6 }"), deps=DEPS)
        self.assertNotIn("default", doc["testObject"])


class EnumerationDefValTestCase(unittest.TestCase):
    """An enumeration default is written as a label and emitted as its number."""

    def testLabelBecomesItsNumber(self):
        json, emitted = default("INTEGER { up(1), down(2) }", "down")
        self.assertEqual(json, {"value": "down", "format": "enum"})
        # The label survives into the emitted call: pysnmp resolves it through
        # the namedValues on the same expression.
        self.assertIn('NamedValues(("up", 1), ("down", 2))).clone(\'down\')', emitted)

    def testZeroValuedLabelSurvives(self):
        # A label naming zero is still a label. Resolving it to its number here
        # would make it indistinguishable from an absent default.
        json, emitted = default("INTEGER { off(0), on(1) }", "off")
        self.assertEqual(json, {"value": "off", "format": "enum"})
        self.assertIn("SingleValueConstraint(0, 1)", emitted)
        self.assertIn(".clone('off')", emitted)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
