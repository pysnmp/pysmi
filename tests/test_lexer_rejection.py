#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The small set of inputs the lexer does reject should stay deliberate.

pysmi is relaxed on purpose: MIBs in the wild are broken and compiling them
anyway is the point. That makes the handful of things it refuses worth pinning,
so none of them can regress into silent acceptance.

This asserts behaviour that already exists. It is not a request for validation.
See pysnmp/pysmi#93.
"""

import sys
import unittest

from pysmi import error
from pysmi.lexer.smi import SmiV2Lexer
from tests.harness import parse

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE
        FROM SNMPv2-SMI;

%s

END
"""


class LexerRejectionTestCase(unittest.TestCase):
    def rejects(self, body):
        """Return the error raised while lexing *body* inside a module."""
        with self.assertRaises(error.PySmiLexerError) as caught:
            parse(MIB % body)
        return str(caught.exception)

    def testForbiddenAsn1WordIsRejected(self):
        self.assertIn("BOOLEAN is forbidden", self.rejects("BOOLEAN ::= INTEGER"))

    def testEveryForbiddenWordIsRejected(self):
        for word in SmiV2Lexer.forbidden_words:
            with self.subTest(word=word):
                self.assertIn("is forbidden", self.rejects(f"{word} ::= INTEGER"))

    def testUppercaseIdentifierEndingInAHyphenIsRejected(self):
        self.assertIn("should not end with '-': Test-", self.rejects("Test- ::= INTEGER"))

    def testLowercaseIdentifierEndingInAHyphenIsRejected(self):
        self.assertIn("should not end with '-': test-", self.rejects("test- OBJECT IDENTIFIER ::= { 1 3 1 }"))

    def testNumberWiderThanSixtyFourBitsIsRejected(self):
        self.assertIn("is too big", self.rejects("testId OBJECT IDENTIFIER ::= { 1 3 184467440737095516150 }"))

    def testIllegalCharacterIsRejected(self):
        self.assertIn("Illegal character '$'", self.rejects("testId OBJECT IDENTIFIER ::= { 1 3 1 }\n$$$"))


class RelaxedAcceptanceTestCase(unittest.TestCase):
    """The counterpart: shapes that look wrong but must keep compiling."""

    def testHyphenInsideAnIdentifierIsFine(self):
        parse(MIB % "test-id OBJECT IDENTIFIER ::= { 1 3 1 }")

    def testSixtyFourBitNumberIsAccepted(self):
        # Too wide for an OID sub-identifier, but the lexer must still produce
        # it: a Counter64 range reaches that far.
        parse(MIB % "TestType ::= Counter64 (0..18446744073709551615)")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
