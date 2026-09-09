#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Type declarations are emitted as RFC 2578 section 7.1 and RFC 2579 define them.

Assertions read the JSON document and the generated source. Asking pysnmp for
``__bases__[0].__name__`` -- which is what the tests these replace did -- says
only that some class was built, and says nothing about the sub-typing written
underneath it. See pysnmp/pysmi#127.
"""

import sys
import unittest

from pysmi.codegen.pysnmp import renders_utf8
from tests.harness import render_json, render_source

#: One declaration per base type of RFC 2578 section 7.1, plus the sub-typing
#: shapes of section 9 and a textual convention from RFC 2579.
MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    IpAddress, Counter32, Gauge32, TimeTicks, Opaque, Integer32, Unsigned32, Counter64
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

TestTypeInteger ::= INTEGER
TestTypeOctetString ::= OCTET STRING
TestTypeObjectIdentifier ::= OBJECT IDENTIFIER

TestTypeIpAddress ::= IpAddress
TestTypeInteger32 ::= Integer32
TestTypeCounter32 ::= Counter32
TestTypeGauge32 ::= Gauge32
TestTypeTimeTicks ::= TimeTicks
TestTypeOpaque ::= Opaque
TestTypeCounter64 ::= Counter64
TestTypeUnsigned32 ::= Unsigned32

TestTypeEnum ::= INTEGER { noResponse(-1), noError(0), tooBig(1) }
TestTypeSizeRangeConstraint ::= OCTET STRING (SIZE (0..255))
TestTypeSizeConstraint ::= OCTET STRING (SIZE (8 | 11))
TestTypeRangeConstraint ::= INTEGER (0..2)
TestTypeSingleValueConstraint ::= INTEGER (0|2|4)

TestTypeBits ::= BITS { sunday(0), monday(1), tuesday(2) }

TestTextualConvention ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "1x:"
    STATUS       current
    DESCRIPTION  "Test TC"
    REFERENCE    "Test reference"
    SYNTAX       OCTET STRING

END
"""

#: RFC 2578 section 7.1: the base types a declaration may name, and the pysnmp
#: class each one is emitted as. INTEGER maps to Integer32 because section
#: 7.1.1 makes them the same range.
BASE_TYPES = (
    ("TestTypeInteger", "INTEGER", "Integer32"),
    ("TestTypeOctetString", "OCTET STRING", "OctetString"),
    ("TestTypeObjectIdentifier", "OBJECT IDENTIFIER", "ObjectIdentifier"),
    ("TestTypeIpAddress", "IpAddress", "IpAddress"),
    ("TestTypeInteger32", "Integer32", "Integer32"),
    ("TestTypeCounter32", "Counter32", "Counter32"),
    ("TestTypeGauge32", "Gauge32", "Gauge32"),
    ("TestTypeTimeTicks", "TimeTicks", "TimeTicks"),
    ("TestTypeOpaque", "Opaque", "Opaque"),
    ("TestTypeCounter64", "Counter64", "Counter64"),
    ("TestTypeUnsigned32", "Unsigned32", "Unsigned32"),
)


class BaseTypeTestCase(unittest.TestCase):
    """RFC 2578 section 7.1 base types reach both artifacts."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)
        cls.source = render_source(MIB)

    def testTheDocumentNamesTheTypeAsTheMibWroteIt(self):
        # The document is the interchange format, so it keeps the ASN.1
        # spelling rather than the pysnmp class name.
        for symbol, written, _ in BASE_TYPES:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["class"], "type")
                self.assertEqual(self.doc[symbol]["type"]["type"], written)

    def testTheEmittedClassDerivesFromThePysnmpBaseType(self):
        for symbol, _, klass in BASE_TYPES:
            with self.subTest(symbol=symbol):
                self.assertIn(f"class {symbol}({klass}):", self.source)

    def testAnUnconstrainedDeclarationAddsNothing(self):
        # Nothing was refined, so nothing may be emitted underneath it: an
        # invented subtypeSpec would narrow a type the MIB left open.
        self.assertIn("class TestTypeInteger(Integer32):\n    pass\n", self.source)

    def testEveryDeclaredTypeIsExported(self):
        exported = self.source.rsplit("exportSymbols(", 1)[1]
        for symbol, _, _ in BASE_TYPES:
            with self.subTest(symbol=symbol):
                self.assertIn(f"{symbol}={symbol}", exported)


class RefinementTestCase(unittest.TestCase):
    """RFC 2578 section 9 refinements, as constraints on the emitted class."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)
        cls.source = render_source(MIB)

    def testARangeIsIntersectedWithTheBaseTypeConstraint(self):
        # The refinement narrows the base type rather than replacing it, so the
        # emitted spec has to be added to the base's own.
        self.assertIn(
            "class TestTypeRangeConstraint(Integer32):\n"
            "    subtypeSpec = Integer32.subtypeSpec + ValueRangeConstraint(0, 2)",
            self.source,
        )
        self.assertEqual(
            self.doc["TestTypeRangeConstraint"]["type"]["constraints"],
            {"range": [{"min": 0, "max": 2}]},
        )

    def testAValueSetBecomesAUnionOfSingleValueRanges(self):
        self.assertIn(
            "ConstraintsUnion(ValueRangeConstraint(0, 0), ValueRangeConstraint(2, 2), ValueRangeConstraint(4, 4), )",
            self.source,
        )

    def testASizeRangeBecomesOneValueSizeConstraint(self):
        self.assertIn(
            "subtypeSpec = OctetString.subtypeSpec + ValueSizeConstraint(0, 255)",
            self.source,
        )
        self.assertEqual(
            self.doc["TestTypeSizeRangeConstraint"]["type"]["constraints"],
            {"size": [{"min": 0, "max": 255}]},
        )

    def testAlternativeSizesBecomeAUnionOfExactSizes(self):
        self.assertIn(
            "ConstraintsUnion(ValueSizeConstraint(8, 8), ValueSizeConstraint(11, 11), )",
            self.source,
        )
        self.assertEqual(
            self.doc["TestTypeSizeConstraint"]["type"]["constraints"],
            {"size": [{"min": 8, "max": 8}, {"min": 11, "max": 11}]},
        )

    def testAnEnumerationCarriesBothItsValuesAndItsLabels(self):
        # RFC 2578 section 7.1.1: an enumeration constrains the value *and*
        # names it. Emitting only the names would leave the type unconstrained;
        # emitting only the constraint would lose the labels a DEFVAL needs.
        self.assertIn(
            "    subtypeSpec = Integer32.subtypeSpec + ConstraintsUnion(SingleValueConstraint(-1, 0, 1))\n"
            '    namedValues = NamedValues(("noResponse", -1), ("noError", 0), ("tooBig", 1))',
            self.source,
        )
        self.assertEqual(
            self.doc["TestTypeEnum"]["type"]["constraints"]["enumeration"],
            {"noResponse": -1, "noError": 0, "tooBig": 1},
        )

    def testANegativeEnumerationValueSurvives(self):
        # RFC 2578 section 7.1.1 permits negative labelled values, and a sign
        # dropped here would silently move the value.
        self.assertEqual(
            self.doc["TestTypeEnum"]["type"]["constraints"]["enumeration"][
                "noResponse"
            ],
            -1,
        )

    def testBitsCarryTheirPositionsInOrder(self):
        # RFC 2578 section 7.1.4 numbers bits from zero, and the position is
        # the value -- not the order of declaration.
        self.assertIn(
            'namedValues = NamedValues(("sunday", 0), ("monday", 1), ("tuesday", 2))',
            self.source,
        )
        self.assertEqual(
            self.doc["TestTypeBits"]["type"]["bits"],
            {"sunday": 0, "monday": 1, "tuesday": 2},
        )


class TextualConventionTestCase(unittest.TestCase):
    """RFC 2579 section 3: the TEXTUAL-CONVENTION macro."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(MIB)["TestTextualConvention"]
        cls.source = render_source(MIB)

    def testTheDocumentMarksItAsAConventionRatherThanAPlainType(self):
        # RFC 2579 section 3.5: a textual convention has the same syntax as its
        # base type but is not the same type, so the document has to say which
        # it is.
        self.assertEqual(self.doc["class"], "textualconvention")
        self.assertEqual(self.doc["type"], {"type": "OCTET STRING", "class": "type"})

    def testTheDocumentCarriesEveryClause(self):
        self.assertEqual(self.doc["displayhint"], "1x:")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "Test TC")
        self.assertEqual(self.doc["reference"], "Test reference")

    def testTextualConventionComesAheadOfTheBaseType(self):
        # Python resolves the display hint along the MRO, so TextualConvention
        # has to be first or the base type's rendering wins.
        self.assertIn(
            "class TestTextualConvention(TextualConvention, OctetString):", self.source
        )

    def testTheDisplayHintIsEmittedAsAClassAttribute(self):
        # RFC 2579 section 3.1: DISPLAY-HINT says how a value is rendered, so it
        # belongs to the type rather than to any object using it.
        self.assertIn("    displayHint = '1x:'", self.source)

    def testTheNarrativeClausesAreEmittedAsClassAttributes(self):
        self.assertIn("    reference = 'Test reference'", self.source)
        self.assertIn("    description = 'Test TC'", self.source)
        self.assertIn("    status = 'current'", self.source)

    def testAUtf8DisplayHintAlsoSetsTheEncoding(self):
        # RFC 2579 section 3.1 gives "t" as the display format for UTF-8, which
        # says what the octets are as well as how to render them. pyasn1 reads
        # that off `encoding` and defaults it to ISO 8859-1, so a hint left to
        # speak only about rendering converts every character above U+007F to
        # the wrong octets.
        mib = MIB.replace('    DISPLAY-HINT "1x:"\n', '    DISPLAY-HINT "255t"\n')
        source = render_source(mib)

        self.assertIn("    displayHint = '255t'", source)
        self.assertIn("    encoding = 'utf-8'", source)

    def testAnAsciiDisplayHintLeavesTheEncodingAlone(self):
        # Only "t" names a character set. "a" is RFC 2579's ascii format, and a
        # convention that does not ask for UTF-8 must keep pyasn1's default
        # rather than be quietly widened to it.
        mib = MIB.replace('    DISPLAY-HINT "1x:"\n', '    DISPLAY-HINT "255a"\n')

        self.assertNotIn("encoding", render_source(mib))

    def testTheHintIsReadAsSpecificationsRatherThanSearchedForTheLetter(self):
        # RFC 2579 section 3.1 part 4: the display separator is a single
        # character that may be anything but a decimal digit and a "*", so a "t"
        # in a hint is only UTF-8 when it lands in part 3. "2dt2d" renders two
        # numbers with a "t" between them and no UTF-8 anywhere.
        mib = MIB.replace('    DISPLAY-HINT "1x:"\n', '    DISPLAY-HINT "2dt2d"\n')

        self.assertNotIn("encoding", render_source(mib))

    def testAConventionWithoutADisplayHintEmitsNone(self):
        # RFC 2579 section 3.1 makes DISPLAY-HINT optional, and an absent hint
        # must not become an empty one -- "" would render every value as blank.
        mib = MIB.replace('    DISPLAY-HINT "1x:"\n', "")
        self.assertNotIn("displayHint", render_source(mib))
        self.assertNotIn("displayhint", render_json(mib)["TestTextualConvention"])


class DisplayHintGrammarTestCase(unittest.TestCase):
    """Where a ``t`` falls in RFC 2579 section 3.1's octet-format grammar.

    The three parts a ``t`` can occupy read alike in the text of a hint: the
    display format, the display separator and the repeat terminator. Only the
    first is UTF-8, so the corners of the grammar are asserted directly rather
    than through a module each.
    """

    #: Hint, and whether any part of it renders as UTF-8.
    HINTS = {
        # Part 3, the display format, with and without a repeat indicator.
        "255t": True,
        "*1t": True,
        "1x:1t": True,
        "1a*1t": True,
        # The other four display formats of part 3.
        "255a": False,
        "1x:": False,
        "1d.1d.1d.1d/2d": False,
        "0a[2x:2x:2x:2x:2x:2x:2x:2x]0a:2d": False,
        # Part 4, the display separator, which may be any character but a
        # decimal digit and a "*".
        "2dt2d": False,
        # Not octet-format specifications at all: an integer hint of section
        # 3.1's first paragraph, and text that parses as neither.
        "d-2": False,
        "d": False,
        "255": False,
        "": False,
    }

    def testOnlyADisplayFormatMeansUtf8(self):
        for hint, utf8 in self.HINTS.items():
            with self.subTest(displayHint=hint):
                self.assertEqual(utf8, renders_utf8(hint))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
