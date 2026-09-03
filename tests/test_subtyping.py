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

from tests.harness import render_json, render_source
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
    """Return the JSON constraints and the emitted syntax expression for one SYNTAX."""
    doc = render_json(MIB % syntax, deps=DEPS)
    line = next(x for x in render_source(MIB % syntax, deps=DEPS).splitlines() if x.startswith("testObject ="))
    return doc["testObject"]["syntax"].get("constraints"), line


class RangeBoundsTestCase(unittest.TestCase):
    """A bound may be negative, hexadecimal or binary."""

    def testNegativeLowerBound(self):
        json, spec = constraints("Integer32 (-20..100)")
        self.assertEqual(json, {"range": [{"min": -20, "max": 100}]})
        self.assertIn("Integer32().subtype(subtypeSpec=ValueRangeConstraint(-20, 100))", spec)

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
        self.assertIn("OctetString().subtype(subtypeSpec=ValueSizeConstraint(0, 255))", spec)

    def testAlternationOfExactSizes(self):
        # The DateAndTime shape from RFC 2579.
        json, _ = constraints("OCTET STRING (SIZE(0 | 8 | 11))")
        self.assertEqual(json, {"size": [{"min": 0, "max": 0}, {"min": 8, "max": 8}, {"min": 11, "max": 11}]})

    def testARefinementIsIntersectedWithTheConventionRatherThanReplacingIt(self):
        # DisplayString carries SIZE(0..255) of its own. .subtype() intersects
        # the refinement with it; .clone(subtypeSpec=...) would replace it and
        # silently widen every value the convention already excluded.
        json, spec = constraints("DisplayString (SIZE(0..32))")
        self.assertEqual(json, {"size": [{"min": 0, "max": 32}]})
        self.assertIn("DisplayString().subtype(subtypeSpec=ValueSizeConstraint(0, 32))", spec)
        self.assertNotIn(".clone(subtypeSpec=", spec)

    def testTypeNameSurvivesTheRefinement(self):
        doc = render_json(MIB % "DisplayString (SIZE(0..32))", deps=DEPS)
        self.assertEqual(doc["testObject"]["syntax"]["type"], "DisplayString")
        self.assertIn("DisplayString().subtype(", render_source(MIB % "DisplayString (SIZE(0..32))", deps=DEPS))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
