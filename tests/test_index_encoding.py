#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""INDEX objects must produce the instance identifiers RFC 2578 section 7.7 defines.

The encoding decides the wire OID of every table instance, and getting one
wrong is silent and severe. See pysnmp/pysmi#86.
"""

import sys
import unittest

from tests.harness import render

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, IpAddress
        FROM SNMPv2-SMI;

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A table."
    ::= { 1 3 1 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A row."
    INDEX       { %s }
    ::= { 1 3 1 1 }

TestEntry ::= SEQUENCE {
    testIndex  %s,
    testValue  Integer32
}

testIndex OBJECT-TYPE
    SYNTAX      %s
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The index column."
    ::= { 1 3 1 1 1 }

testValue OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A plain column."
    ::= { 1 3 1 1 2 }

END
"""


def row(syntax, index="testIndex", base=None):
    """Build a one-column-indexed table and return its pysnmp row and JSON entry.

    Args:
        syntax: SYNTAX of the index column, sub-typing included
        index: the INDEX clause body, so IMPLIED can be placed
        base: SEQUENCE element type, when it differs from *syntax*
    """
    doc, ctx = render(MIB % (index, base or syntax, syntax))
    return ctx["testEntry"], doc["testEntry"]


class ScalarIndexTestCase(unittest.TestCase):
    """One sub-identifier for an integer, four for an IpAddress."""

    def testIntegerIndexIsOneSubIdentifier(self):
        entry, _ = row("Integer32")
        self.assertEqual(entry.getInstIdFromIndices(42), (42,))

    def testIpAddressIndexIsFourSubIdentifiers(self):
        entry, _ = row("IpAddress")
        self.assertEqual(entry.getInstIdFromIndices("192.0.2.1"), (192, 0, 2, 1))


class StringIndexTestCase(unittest.TestCase):
    """A variable-length string is length-prefixed unless it is IMPLIED."""

    def testFixedLengthStringHasNoLengthPrefix(self):
        entry, _ = row("OCTET STRING (SIZE(4))", base="OCTET STRING")
        self.assertEqual(entry.getInstIdFromIndices(b"abcd"), (97, 98, 99, 100))

    def testVariableLengthStringIsLengthPrefixed(self):
        entry, _ = row("OCTET STRING")
        self.assertEqual(entry.getInstIdFromIndices(b"abc"), (3, 97, 98, 99))

    def testImpliedStringDropsTheLengthPrefix(self):
        entry, doc = row("OCTET STRING", index="IMPLIED testIndex")
        self.assertEqual(entry.getInstIdFromIndices(b"abc"), (97, 98, 99))
        self.assertEqual(doc["indices"], [{"module": "TEST-MIB", "object": "testIndex", "implied": 1}])

    def testNotImpliedIsRecordedInTheDocument(self):
        _, doc = row("OCTET STRING")
        self.assertEqual(doc["indices"], [{"module": "TEST-MIB", "object": "testIndex", "implied": 0}])


class OidIndexTestCase(unittest.TestCase):
    """An OID index is counted unless it is IMPLIED."""

    def testOidIndexIsCountPrefixed(self):
        entry, _ = row("OBJECT IDENTIFIER")
        self.assertEqual(entry.getInstIdFromIndices((1, 3, 6)), (3, 1, 3, 6))

    def testImpliedOidIndexDropsTheCount(self):
        entry, _ = row("OBJECT IDENTIFIER", index="IMPLIED testIndex")
        self.assertEqual(entry.getInstIdFromIndices((1, 3, 6)), (1, 3, 6))


MULTI_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A table."
    ::= { 1 3 1 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A row."
    INDEX       { testInt, %s testStr }
    ::= { 1 3 1 1 }

TestEntry ::= SEQUENCE {
    testInt  Integer32,
    testStr  OCTET STRING
}

testInt OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "First index."
    ::= { 1 3 1 1 1 }

testStr OBJECT-TYPE
    SYNTAX      OCTET STRING
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "Second index."
    ::= { 1 3 1 1 2 }

END
"""


class MultiColumnIndexTestCase(unittest.TestCase):
    """Each INDEX column contributes its own encoding, in clause order."""

    def testFixedThenVariablePartsConcatenate(self):
        _, ctx = render(MULTI_MIB % "")
        self.assertEqual(ctx["testEntry"].getInstIdFromIndices(7, b"ab"), (7, 2, 97, 98))

    def testTrailingImpliedAppliesToTheLastColumnOnly(self):
        _, ctx = render(MULTI_MIB % "IMPLIED")
        self.assertEqual(ctx["testEntry"].getInstIdFromIndices(7, b"ab"), (7, 97, 98))


class IndexOrderTestCase(unittest.TestCase):
    """The document records index columns in clause order, not OID order."""

    def testDocumentKeepsClauseOrder(self):
        doc, _ = render(MULTI_MIB % "")
        self.assertEqual([i["object"] for i in doc["testEntry"]["indices"]], ["testInt", "testStr"])

    def testPySnmpKeepsClauseOrder(self):
        _, ctx = render(MULTI_MIB % "")
        self.assertEqual([n[-1] for n in ctx["testEntry"].getIndexNames()], ["testInt", "testStr"])


AUGMENTS_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

baseTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF BaseEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The base table."
    ::= { 1 3 1 }

baseEntry OBJECT-TYPE
    SYNTAX      BaseEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The base row."
    INDEX       { baseIndex }
    ::= { 1 3 1 1 }

BaseEntry ::= SEQUENCE { baseIndex Integer32 }

baseIndex OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The base index."
    ::= { 1 3 1 1 1 }

augTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF AugEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The augmenting table."
    ::= { 1 3 2 }

augEntry OBJECT-TYPE
    SYNTAX      AugEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The augmenting row."
    AUGMENTS    { baseEntry }
    ::= { 1 3 2 1 }

AugEntry ::= SEQUENCE { augValue Integer32 }

augValue OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A column of the augmenting row."
    ::= { 1 3 2 1 1 }

END
"""


class AugmentsTestCase(unittest.TestCase):
    """An augmenting row is indexed exactly as the row it augments."""

    def setUp(self):
        self.doc, self.ctx = render(AUGMENTS_MIB)

    def testAugmentingRowInheritsTheBaseEncoding(self):
        self.assertEqual(
            self.ctx["augEntry"].getInstIdFromIndices(5),
            self.ctx["baseEntry"].getInstIdFromIndices(5),
        )

    def testAugmentingRowNamesItsBase(self):
        # "augmention" is the published spelling; pinned, not endorsed.
        self.assertEqual(
            self.doc["augEntry"]["augmention"],
            {"name": "augEntry", "module": "TEST-MIB", "object": "baseEntry"},
        )

    def testAugmentingRowHasNoIndicesOfItsOwn(self):
        self.assertNotIn("indices", self.doc["augEntry"])
        self.assertEqual(self.doc["baseEntry"]["indices"][0]["object"], "baseIndex")


class ForeignIndexTestCase(unittest.TestCase):
    """RFC 2578 section 7.7 permits INDEX to name a column of another table."""

    def setUp(self):
        mib = AUGMENTS_MIB.replace("AUGMENTS    { baseEntry }", "INDEX       { baseIndex }")
        self.doc, self.ctx = render(mib)

    def testIndexResolvesAcrossTables(self):
        self.assertEqual(
            self.doc["augEntry"]["indices"],
            [{"module": "TEST-MIB", "object": "baseIndex", "implied": 0}],
        )

    def testForeignIndexEncodesLikeItsOwnTable(self):
        self.assertEqual(
            self.ctx["augEntry"].getInstIdFromIndices(5),
            self.ctx["baseEntry"].getInstIdFromIndices(5),
        )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
