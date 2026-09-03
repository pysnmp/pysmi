#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Each relaxation option tolerates one specific deviation, and only that one.

pysmi.parser.dialect names nine options and groups them into three dialects.
Tests reached the dialects but never an option on its own, so nothing said
which deviation each one buys, and a flag could stop working while the dialect
that contains it still passed.

Every case below asserts both directions: rejected without the option, and
accepted with it. See pysnmp/pysmi#91.
"""

import sys
import unittest

from pysmi import error
from pysmi.parser import dialect
from tests.harness import parse

COMMA_IN_IMPORT = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE,
        FROM SNMPv2-SMI;

testId OBJECT IDENTIFIER ::= { 1 3 1 }

END
"""

COMMA_IN_SEQUENCE = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

TestEntry ::= SEQUENCE {
    testIndex  Integer32,
}

END
"""

ENUM = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE
        FROM SNMPv2-SMI;

testObject OBJECT-TYPE
    SYNTAX      INTEGER { %s }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The object under test."
    ::= { 1 3 1 }

END
"""

MIXED_SEPARATORS = ENUM % "up(1) down(2), other(3)"
UPPERCASE_ENUM_ITEM = ENUM % "Up(1), Down(2)"

UPPERCASE_NOTIFICATION = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    NOTIFICATION-TYPE
        FROM SNMPv2-SMI;

TestNotify NOTIFICATION-TYPE
    STATUS      current
    DESCRIPTION "A notification named in upper case."
    ::= { 1 3 1 }

END
"""

BRACED_ENTERPRISE = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TRAP-TYPE
        FROM RFC-1215;

testId OBJECT IDENTIFIER ::= { 1 3 1 }

testTrap TRAP-TYPE
    ENTERPRISE  { testId }
    DESCRIPTION "A trap."
    ::= 7

END
"""

BARE_TYPE_IN_INDEX = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE
        FROM RFC1155-SMI;

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    ACCESS      not-accessible
    STATUS      mandatory
    DESCRIPTION "A row indexed by a bare ASN.1 type."
    INDEX       { INTEGER }
    ::= { 1 3 1 1 }

END
"""

EMPTY_CREATION_REQUIRES = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "An object."
    ::= { 1 3 1 }

testCaps AGENT-CAPABILITIES
    PRODUCT-RELEASE "Test release."
    STATUS          current
    DESCRIPTION     "Capabilities."
    SUPPORTS        TEST-MIB
        INCLUDES    { testGroup }
        VARIATION   testObject
        CREATION-REQUIRES { }
        DESCRIPTION "A variation with no cells."
    ::= { 1 3 2 }

END
"""


CASES = {
    "commaAtTheEndOfImport": COMMA_IN_IMPORT,
    "commaAtTheEndOfSequence": COMMA_IN_SEQUENCE,
    "mixOfCommasAndSpaces": MIXED_SEPARATORS,
    "uppercaseIdentifier": UPPERCASE_ENUM_ITEM,
    "lowcaseIdentifier": UPPERCASE_NOTIFICATION,
    "curlyBracesAroundEnterpriseInTrap": BRACED_ENTERPRISE,
    "noCells": EMPTY_CREATION_REQUIRES,
}


class DialectFlagTestCase(unittest.TestCase):
    def testStrictParserRejectsEveryDeviation(self):
        for flag, mib in CASES.items():
            with self.subTest(option=flag), self.assertRaises(error.PySmiError):
                parse(mib)

    def testEachOptionAcceptsItsOwnDeviation(self):
        for flag, mib in CASES.items():
            with self.subTest(option=flag):
                parse(mib, **{flag: True})


class SupportIndexTestCase(unittest.TestCase):
    """supportIndex is the one option that cannot stand on its own."""

    def testStrictParserRejectsABareTypeInIndex(self):
        with self.assertRaises(error.PySmiParserError):
            parse(BARE_TYPE_IN_INDEX)

    def testTheSmiV1PairAcceptsIt(self):
        parse(BARE_TYPE_IN_INDEX, supportSmiV1Keywords=True, supportIndex=True)

    def testItsProductionsNeedTheSmiV1OnesToBuild(self):
        # SupportIndex.p_typeSMIv1 refers to productions that only
        # supportSmiV1Keywords contributes, so the grammar will not build.
        with self.assertRaises(Exception) as caught:
            parse(BARE_TYPE_IN_INDEX, supportIndex=True)
        self.assertIn("Unable to build parser", str(caught.exception))


class DialectTestCase(unittest.TestCase):
    """The shipped dialects accept everything their options cover."""

    def testSmiV1RelaxedAcceptsEveryDeviation(self):
        for flag, mib in CASES.items():
            with self.subTest(option=flag):
                parse(mib, **dialect.smiV1Relaxed)

    def testSmiV1AcceptsTheBareTypeInIndex(self):
        # supportSmiV1Keywords is only additive: the base grammar already
        # accepts NetworkAddress everywhere it was tried, so the option has
        # nothing to assert alone and is exercised through this dialect.
        parse(BARE_TYPE_IN_INDEX, **dialect.smiV1)

    def testStrictSmiV2CarriesNoRelaxations(self):
        self.assertEqual(dialect.smiV2, {})


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
