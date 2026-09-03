#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Sub-typing forms from RFC 2578 section 11.1 that pysmi must accept.

Existing tests reach (0..N), (a|b|c) and SIZE(0..255). The value production
also allows negative, hexadecimal and binary bounds, ranges wider than 32 bits,
alternation inside SIZE, and sub-typing applied to a textual convention.

Asserting rejection of the RFC's invalid examples is deliberately out of scope:
real MIBs contain them and tolerating them is correct here. See pysnmp/pysmi#88.
"""

import sys
import unittest

from tests.harness import render
from tests.mibs import SNMPV2_SMI, SNMPV2_TC

DEPS = (SNMPV2_SMI, SNMPV2_TC)

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, Unsigned32, Counter64
        FROM SNMPv2-SMI
    DisplayString
        FROM SNMPv2-TC;

testObject OBJECT-TYPE
    SYNTAX      %s
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The object under test."
    ::= { 1 3 1 }

END
"""


def constraints(syntax):
    """Return the JSON constraints and the pysnmp subtype spec for one SYNTAX."""
    doc, ctx = render(MIB % syntax, deps=DEPS)
    return doc["testObject"]["syntax"].get("constraints"), ctx["testObject"].getSyntax().subtypeSpec


class RangeBoundsTestCase(unittest.TestCase):
    """A bound may be negative, hexadecimal or binary."""

    def testNegativeLowerBound(self):
        json, spec = constraints("Integer32 (-20..100)")
        self.assertEqual(json, {"range": [{"min": -20, "max": 100}]})
        self.assertIn("consts -20, 100", repr(spec))

    def testHexadecimalBoundsBecomeNumbers(self):
        json, _ = constraints("Integer32 ('0F'H..'FF'H)")
        self.assertEqual(json, {"range": [{"min": 15, "max": 255}]})

    def testBinaryBoundsBecomeNumbers(self):
        json, _ = constraints("Integer32 ('0000'B..'1111'B)")
        self.assertEqual(json, {"range": [{"min": 0, "max": 15}]})

    def testAlternationKeepsEveryRange(self):
        json, _ = constraints("Integer32 (1..10 | 20..30)")
        self.assertEqual(json, {"range": [{"min": 1, "max": 10}, {"min": 20, "max": 30}]})

    def testCounter64RangeExceedsThirtyTwoBits(self):
        json, _ = constraints("Counter64 (0..18446744073709551615)")
        self.assertEqual(json, {"range": [{"min": 0, "max": 18446744073709551615}]})


class SizeConstraintTestCase(unittest.TestCase):
    """SIZE takes the same alternation as a range, and applies to a convention."""

    def testSingleSizeRange(self):
        json, spec = constraints("OCTET STRING (SIZE(0..255))")
        self.assertEqual(json, {"size": [{"min": 0, "max": 255}]})
        self.assertIn("consts 0, 255", repr(spec))

    def testAlternationOfExactSizes(self):
        # The DateAndTime shape from RFC 2579.
        json, _ = constraints("OCTET STRING (SIZE(0 | 8 | 11))")
        self.assertEqual(json, {"size": [{"min": 0, "max": 0}, {"min": 8, "max": 8}, {"min": 11, "max": 11}]})

    def testTextualConventionKeepsItsOwnSizeAndTheRefinement(self):
        json, spec = constraints("DisplayString (SIZE(0..32))")
        self.assertEqual(json, {"size": [{"min": 0, "max": 32}]})
        self.assertIn("consts 0, 255", repr(spec))
        self.assertIn("consts 0, 32", repr(spec))

    def testTypeNameSurvivesTheRefinement(self):
        doc, ctx = render(MIB % "DisplayString (SIZE(0..32))", deps=DEPS)
        self.assertEqual(doc["testObject"]["syntax"]["type"], "DisplayString")
        self.assertEqual(ctx["testObject"].getSyntax().__class__.__name__, "DisplayString")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
