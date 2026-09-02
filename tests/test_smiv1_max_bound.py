#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""SMIv1 allows MAX as the upper bound of a range or SIZE constraint.

MAX stands for the largest value the constrained type can hold. It is resolved
while parsing, where the syntax naming the type is still at hand, so the code
generators only ever see numbers.

MAX is a forbidden word in SMIv2, and MIN is forbidden in both dialects, so
neither may be written where an SMIv2 MIB is expected.
"""

import unittest

from pysmi import error
from pysmi.parser.dialect import smiV1, smiV2
from pysmi.parser.smi import parserFactory

INTEGER32_MAX = 2147483647
UNSIGNED32_MAX = 4294967295
COUNTER64_MAX = 18446744073709551615
SIZE_MAX = 65535


def mib(body):
    return f"""
MAX-TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE
        FROM RFC-1212
    Gauge, Counter
        FROM RFC1155-SMI;

maxTest OBJECT IDENTIFIER ::= {{ 1 3 6 1 4 1 99998 }}

{body}

END
"""


def scalar(name, syntax, index=1):
    return f"""{name} OBJECT-TYPE
    SYNTAX  {syntax}
    ACCESS  read-only
    STATUS  mandatory
    DESCRIPTION "A scalar."
    ::= {{ maxTest {index} }}"""


def syntaxOf(parsed, name):
    """Return the SYNTAX value the parser produced for *name*."""
    for clause in parsed[0][3]:
        if isinstance(clause, tuple) and clause and clause[0] == "objectTypeClause" and clause[1] == name:
            return clause[2]
    raise AssertionError(f"no objectTypeClause for {name}")


def rangesOf(parsed, name):
    """Return the range or size entries the parser produced for *name*."""
    return syntaxOf(parsed, name)[2][1]


class SmiV1MaxBoundTestCase(unittest.TestCase):
    def setUp(self):
        self.parser = parserFactory(**smiV1)()

    def parse(self, body):
        return self.parser.parse(mib(body))

    def testSizeMaxResolvesToLongestOctetString(self):
        parsed = self.parse(scalar("maxOctets", "OCTET STRING (SIZE (0..MAX))"))
        self.assertEqual([(0, SIZE_MAX)], rangesOf(parsed, "maxOctets"))

    def testIntegerRangeMaxResolvesToInteger32Max(self):
        parsed = self.parse(scalar("maxInt", "INTEGER (0..MAX)"))
        self.assertEqual([(0, INTEGER32_MAX)], rangesOf(parsed, "maxInt"))

    def testGaugeMaxResolvesToUnsigned32Max(self):
        parsed = self.parse(scalar("maxGauge", "Gauge (0..MAX)"))
        self.assertEqual([(0, UNSIGNED32_MAX)], rangesOf(parsed, "maxGauge"))

    def testCounterMaxResolvesToUnsigned32Max(self):
        parsed = self.parse(scalar("maxCounter", "Counter (0..MAX)"))
        self.assertEqual([(0, UNSIGNED32_MAX)], rangesOf(parsed, "maxCounter"))

    def testOnlyTheMaxBoundIsRewritten(self):
        """A MAX in one range leaves every other bound alone."""
        parsed = self.parse(scalar("maxMulti", "INTEGER (0..10 | 20..MAX)"))
        self.assertEqual([(0, 10), (20, INTEGER32_MAX)], rangesOf(parsed, "maxMulti"))

    def testRangesWithoutMaxAreUntouched(self):
        parsed = self.parse(scalar("plainInt", "INTEGER (0..100)"))
        self.assertEqual([(0, 100)], rangesOf(parsed, "plainInt"))

    def testMaxIsResolvedForEveryScalarInOneModule(self):
        """Resolution is per constraint, not once per module."""
        parsed = self.parse(
            "\n\n".join(
                [
                    scalar("maxOctets", "OCTET STRING (SIZE (0..MAX))", 1),
                    scalar("maxInt", "INTEGER (0..MAX)", 2),
                    scalar("maxGauge", "Gauge (0..MAX)", 3),
                ]
            )
        )
        self.assertEqual([(0, SIZE_MAX)], rangesOf(parsed, "maxOctets"))
        self.assertEqual([(0, INTEGER32_MAX)], rangesOf(parsed, "maxInt"))
        self.assertEqual([(0, UNSIGNED32_MAX)], rangesOf(parsed, "maxGauge"))

    def testNoKeywordSurvivesParsing(self):
        """The generators are handed numbers, never the keyword."""
        parsed = self.parse(scalar("maxInt", "INTEGER (0..MAX)"))
        for rng in rangesOf(parsed, "maxInt"):
            for bound in rng:
                self.assertNotEqual("MAX", bound)
                self.assertIsInstance(bound, int)


class SmiV2MaxBoundTestCase(unittest.TestCase):
    """MAX is not part of SMIv2, and the lexer rejects it as before."""

    def testSmiV2RejectsMaxAsForbidden(self):
        parser = parserFactory(**smiV2)()
        with self.assertRaises(error.PySmiLexerError) as caught:
            parser.parse(mib(scalar("maxInt", "INTEGER (0..MAX)")))
        self.assertIn("MAX is forbidden", str(caught.exception))

    def testSmiV2StillParsesOrdinaryRanges(self):
        parser = parserFactory(**smiV2)()
        parsed = parser.parse(mib(scalar("plainInt", "INTEGER (0..100)")))
        self.assertEqual([(0, 100)], rangesOf(parsed, "plainInt"))


class MinBoundTestCase(unittest.TestCase):
    """MIN is a forbidden word in both dialects, so it is never a bound."""

    def testSmiV1RejectsMin(self):
        parser = parserFactory(**smiV1)()
        with self.assertRaises(error.PySmiLexerError) as caught:
            parser.parse(mib(scalar("minInt", "INTEGER (MIN..0)")))
        self.assertIn("MIN is forbidden", str(caught.exception))


suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
