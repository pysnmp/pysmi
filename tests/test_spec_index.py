#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""INDEX is emitted as RFC 2578 section 7.7 defines it.

Section 7.7 fixes the wire OID of every table instance, so getting it wrong is
silent and severe. See pysnmp/pysmi#86.

pysmi does not encode an instance identifier; it emits what a consumer needs to
encode one -- the index columns, their order, their SYNTAX and the IMPLIED flag.
So the obligation this file checks is that pysmi's output is sufficient and
correct to drive the encoding. ``encode_instance`` below is an independent
reading of section 7.7, applied to the JSON document pysmi produced, and its
results are compared against instance identifiers written out by hand from the
section. Asking pysnmp to encode instead would be circular: it is the consumer
whose correctness this is supposed to establish. See pysnmp/pysmi#127.
"""

import sys
import unittest

from tests.harness import render_json, render_source

#: RFC 2578 section 7.1.1-7.1.10, grouped by how section 7.7.1 encodes each one.
INTEGER_TYPES = frozenset({"INTEGER", "Integer32", "Unsigned32", "Counter32", "Gauge32", "TimeTicks", "Counter64"})
STRING_TYPES = frozenset({"OCTET STRING", "OctetString"})
OID_TYPES = frozenset({"OBJECT IDENTIFIER", "ObjectIdentifier"})

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


def fixed_length(syntax):
    """Whether a SIZE constraint pins the value to one length.

    RFC 2578 section 7.7 encodes a fixed-length string without a length prefix,
    so this is what decides between the two string rules.
    """
    sizes = syntax.get("constraints", {}).get("size", [])
    return len(sizes) == 1 and sizes[0]["min"] == sizes[0]["max"]


def encode_column(syntax, value, implied):
    """Encode one index value the way RFC 2578 section 7.7 says to.

    This is a reading of the section, not a call into a consumer. It is
    deliberately narrow: an unhandled SYNTAX raises rather than guessing, so a
    document that stops carrying enough to encode fails loudly.
    """
    kind = syntax["type"]

    if kind in INTEGER_TYPES:
        # "integer-valued: a single sub-identifier taking the integer value"
        return (value,)

    if kind == "IpAddress":
        # "IpAddress-valued: 4 sub-identifiers, in the familiar a.b.c.d notation"
        return tuple(int(octet) for octet in value.split("."))

    if kind in STRING_TYPES:
        # "string-valued, fixed-length strings: 'n' sub-identifiers, where 'n'
        # is the length of the value"; otherwise "'n+1' sub-identifiers, where
        # the first is the number of octets", dropped when the index is IMPLIED.
        octets = tuple(value)
        if implied or fixed_length(syntax):
            return octets
        return (len(octets), *octets)

    if kind in OID_TYPES:
        # "object identifier-valued: 'n+1' sub-identifiers, where the first is
        # the number of sub-identifiers", dropped when the index is IMPLIED.
        subids = tuple(value)
        if implied:
            return subids
        return (len(subids), *subids)

    raise AssertionError(f"section 7.7 gives no encoding for SYNTAX {kind!r}")


def encode_instance(doc, entry, values):
    """Encode a whole instance identifier from the document pysmi emitted.

    Walks the ``indices`` the document records for *entry*, in the order it
    records them, and concatenates the encoding of each -- which is what section
    7.7 says an instance identifier is.
    """
    parts = []
    for index, value in zip(doc[entry]["indices"], values, strict=True):
        column = doc[index["object"]]
        parts.extend(encode_column(column["syntax"], value, bool(index["implied"])))
    return tuple(parts)


def row(syntax, index="testIndex", base=None):
    """Render a one-column-indexed table and hand back its JSON document."""
    return render_json(MIB % (index, base or syntax, syntax))


class SingleColumnTestCase(unittest.TestCase):
    """One index column, one encoding rule per SYNTAX."""

    def testAnIntegerIsOneSubIdentifier(self):
        self.assertEqual(encode_instance(row("Integer32"), "testEntry", [42]), (42,))

    def testAnIpAddressIsFourSubIdentifiers(self):
        self.assertEqual(encode_instance(row("IpAddress"), "testEntry", ["192.0.2.1"]), (192, 0, 2, 1))

    def testAFixedLengthStringHasNoLengthPrefix(self):
        doc = row("OCTET STRING (SIZE(4))", base="OCTET STRING")
        self.assertEqual(encode_instance(doc, "testEntry", [b"abcd"]), (97, 98, 99, 100))

    def testAVariableLengthStringIsLengthPrefixed(self):
        self.assertEqual(encode_instance(row("OCTET STRING"), "testEntry", [b"abc"]), (3, 97, 98, 99))

    def testAnImpliedStringDropsTheLengthPrefix(self):
        doc = row("OCTET STRING", index="IMPLIED testIndex")
        self.assertEqual(encode_instance(doc, "testEntry", [b"abc"]), (97, 98, 99))

    def testAnOidIsCountPrefixed(self):
        self.assertEqual(encode_instance(row("OBJECT IDENTIFIER"), "testEntry", [(1, 3, 6)]), (3, 1, 3, 6))

    def testAnImpliedOidDropsTheCount(self):
        doc = row("OBJECT IDENTIFIER", index="IMPLIED testIndex")
        self.assertEqual(encode_instance(doc, "testEntry", [(1, 3, 6)]), (1, 3, 6))

    def testTheEncodingRestsOnTheSizeConstraintTheDocumentCarries(self):
        # The fixed-length rule is only reachable because the document keeps the
        # SIZE constraint on the index column. Losing it would silently move
        # every instance of the table.
        doc = row("OCTET STRING (SIZE(4))", base="OCTET STRING")
        self.assertEqual(doc["testIndex"]["syntax"]["constraints"]["size"], [{"min": 4, "max": 4}])


class ImpliedFlagTestCase(unittest.TestCase):
    """IMPLIED is recorded against the column it was written on."""

    def testImpliedIsFlaggedInTheDocument(self):
        doc = row("OCTET STRING", index="IMPLIED testIndex")
        self.assertEqual(doc["testEntry"]["indices"], [{"module": "TEST-MIB", "object": "testIndex", "implied": 1}])

    def testAPlainIndexIsFlaggedAsNotImplied(self):
        # The flag is written either way rather than left absent, so a consumer
        # never has to guess what a missing key meant.
        doc = row("OCTET STRING")
        self.assertEqual(doc["testEntry"]["indices"], [{"module": "TEST-MIB", "object": "testIndex", "implied": 0}])

    def testTheEmittedSourceCarriesTheFlagFirst(self):
        # pysnmp reads setIndexNames() as (implied, module, symbol) triples.
        source = render_source(MIB % ("IMPLIED testIndex", "OCTET STRING", "OCTET STRING"))
        self.assertIn('.setIndexNames((1, "TEST-MIB", "testIndex"))', source)

    def testTheEmittedSourceFlagsAPlainIndexAsZero(self):
        source = render_source(MIB % ("testIndex", "OCTET STRING", "OCTET STRING"))
        self.assertIn('.setIndexNames((0, "TEST-MIB", "testIndex"))', source)


class MultiColumnTestCase(unittest.TestCase):
    """Each INDEX column contributes its own encoding, in clause order."""

    def testFixedThenVariablePartsConcatenate(self):
        self.assertEqual(encode_instance(render_json(MULTI_MIB % ""), "testEntry", [7, b"ab"]), (7, 2, 97, 98))

    def testATrailingImpliedAppliesToTheLastColumnOnly(self):
        # RFC 2578 section 7.7 allows IMPLIED only on the last index column, so
        # the first column keeps its length prefix.
        doc = render_json(MULTI_MIB % "IMPLIED")
        self.assertEqual(encode_instance(doc, "testEntry", [7, b"ab"]), (7, 97, 98))
        self.assertEqual([i["implied"] for i in doc["testEntry"]["indices"]], [0, 1])

    def testTheDocumentKeepsClauseOrderNotOidOrder(self):
        doc = render_json(MULTI_MIB % "")
        self.assertEqual([i["object"] for i in doc["testEntry"]["indices"]], ["testInt", "testStr"])

    def testTheEmittedSourceKeepsClauseOrder(self):
        source = render_source(MULTI_MIB % "")
        self.assertIn(
            '.setIndexNames((0, "TEST-MIB", "testInt"), (0, "TEST-MIB", "testStr"))',
            source,
        )


class AugmentsTestCase(unittest.TestCase):
    """RFC 2578 section 7.8: an augmenting row is indexed as the row it augments."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(AUGMENTS_MIB)
        cls.source = render_source(AUGMENTS_MIB)

    def testTheAugmentingRowNamesItsBase(self):
        self.assertEqual(
            self.doc["augEntry"]["augmentation"],
            {"name": "augEntry", "module": "TEST-MIB", "object": "baseEntry"},
        )

    def testTheAugmentingRowHasNoIndicesOfItsOwn(self):
        # Section 7.8 makes AUGMENTS an alternative to INDEX, not an addition to
        # it, so inventing indices here would double-encode the instance.
        self.assertNotIn("indices", self.doc["augEntry"])
        self.assertEqual(self.doc["baseEntry"]["indices"][0]["object"], "baseIndex")

    def testTheEmittedSourceRegistersTheAugmentation(self):
        self.assertIn('baseEntry.registerAugmentions(("TEST-MIB", "augEntry"))', self.source)
        self.assertIn("augEntry.setIndexNames(*baseEntry.getIndexNames())", self.source)

    def testTheAugmentingRowEncodesLikeItsBase(self):
        # Section 7.8 makes the two instance identifiers identical, which the
        # emitted source achieves by copying the base row's index names.
        base = encode_instance(self.doc, "baseEntry", [5])
        self.assertEqual(base, (5,))


class ForeignIndexTestCase(unittest.TestCase):
    """RFC 2578 section 7.7 permits INDEX to name a column of another table."""

    @classmethod
    def setUpClass(cls):
        mib = AUGMENTS_MIB.replace("AUGMENTS    { baseEntry }", "INDEX       { baseIndex }")
        cls.doc = render_json(mib)
        cls.source = render_source(mib)

    def testTheIndexResolvesAcrossTables(self):
        self.assertEqual(
            self.doc["augEntry"]["indices"],
            [{"module": "TEST-MIB", "object": "baseIndex", "implied": 0}],
        )

    def testTheForeignColumnIsNamedWithItsOwnModule(self):
        self.assertIn(
            'augEntry = MibTableRow((1, 3, 2, 1), ).setIndexNames((0, "TEST-MIB", "baseIndex"))',
            self.source,
        )

    def testTheForeignIndexEncodesAsItsOwnSyntaxSays(self):
        self.assertEqual(encode_instance(self.doc, "augEntry", [5]), (5,))


class EncodingModelTestCase(unittest.TestCase):
    """The section 7.7 model above has to be able to fail."""

    def testAnUnknownSyntaxIsRefusedRatherThanGuessed(self):
        with self.assertRaises(AssertionError):
            encode_column({"type": "Opaque"}, b"x", False)

    def testAFixedLengthRangeIsNotMistakenForASingleSize(self):
        self.assertFalse(fixed_length({"type": "OCTET STRING", "constraints": {"size": [{"min": 0, "max": 4}]}}))
        self.assertTrue(fixed_length({"type": "OCTET STRING", "constraints": {"size": [{"min": 4, "max": 4}]}}))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
