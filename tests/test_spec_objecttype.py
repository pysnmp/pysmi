#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""OBJECT-TYPE is emitted as RFC 2578 section 7 defines it.

Every assertion here reads pysmi's own output -- the JSON document and the
generated source -- against the clause definitions in the RFC. Nothing asks
pysnmp what it made of the output, because pysnmp normalises and discards, so
an assertion routed through it cannot tell a faithful emission from one it
happened to tolerate. See pysnmp/pysmi#127.
"""

import sys
import unittest

from tests.harness import render_json, render_source
from tests.mibs import SNMPV2_SMI

#: One scalar carrying every clause RFC 2578 section 7 gives OBJECT-TYPE.
FULL_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testObjectType OBJECT-TYPE
    SYNTAX      Integer32 (0..7)
    UNITS       "seconds"
    MAX-ACCESS  accessible-for-notify
    STATUS      current
    DESCRIPTION "Test object"
    REFERENCE   "ABC"
    DEFVAL      { 3 }
    ::= { 1 3 }

END
"""

#: A scalar per MAX-ACCESS value of RFC 2578 section 7.3, plus the STATUS
#: values of section 7.4.
ACCESS_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testNotAccessible OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS not-accessible STATUS current DESCRIPTION "a" ::= { 1 3 1 }

testForNotify OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS accessible-for-notify STATUS deprecated DESCRIPTION "b" ::= { 1 3 2 }

testReadOnly OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS obsolete DESCRIPTION "c" ::= { 1 3 3 }

testReadWrite OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-write STATUS current DESCRIPTION "d" ::= { 1 3 4 }

testReadCreate OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-create STATUS current DESCRIPTION "e" ::= { 1 3 5 }

END
"""

#: A scalar per SYNTAX shape of RFC 2578 section 7.1 that pysmi has to
#: translate rather than pass through.
SYNTAX_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, Unsigned32
        FROM SNMPv2-SMI;

testRange OBJECT-TYPE
    SYNTAX Unsigned32 (0..4294967295) MAX-ACCESS read-only STATUS current DESCRIPTION "a"
    DEFVAL { 0 } ::= { 1 3 1 }

testValueSet OBJECT-TYPE
    SYNTAX Unsigned32 (0|2|44) MAX-ACCESS read-only STATUS current DESCRIPTION "b" ::= { 1 3 2 }

testSize OBJECT-TYPE
    SYNTAX OCTET STRING (SIZE (0..512)) MAX-ACCESS read-only STATUS current DESCRIPTION "c" ::= { 1 3 3 }

testBits OBJECT-TYPE
    SYNTAX BITS { notification(0), set(1) } MAX-ACCESS read-only STATUS current DESCRIPTION "d" ::= { 1 3 4 }

testEnum OBJECT-TYPE
    SYNTAX INTEGER { enable(1), disable(2) } MAX-ACCESS read-only STATUS current DESCRIPTION "e"
    DEFVAL { enable } ::= { 1 3 5 }

testString OBJECT-TYPE
    SYNTAX OCTET STRING MAX-ACCESS read-only STATUS current DESCRIPTION "f"
    DEFVAL { "test value" } ::= { 1 3 6 }

testInteger OBJECT-TYPE
    SYNTAX Integer32 MAX-ACCESS read-only STATUS current DESCRIPTION "g"
    DEFVAL { 123456 } ::= { 1 3 7 }

END
"""


def emitted_lines(pycode):
    """Index the emitted assignment lines by the symbol each one defines."""
    return {line.split(" = ", 1)[0]: line for line in pycode.splitlines() if " = " in line and "import" not in line}


class ClauseTestCase(unittest.TestCase):
    """Each OBJECT-TYPE clause of RFC 2578 section 7 reaches both artifacts."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(FULL_MIB)["testObjectType"]
        cls.line = emitted_lines(render_source(FULL_MIB))["testObjectType"]

    def testTheDocumentCarriesEveryClause(self):
        # RFC 2578 section 7: SYNTAX, UNITS, MAX-ACCESS, STATUS, DESCRIPTION,
        # REFERENCE and DEFVAL are each a distinct clause, so each one is a
        # distinct key rather than something folded into the syntax.
        self.assertEqual(self.doc["nodetype"], "scalar")
        self.assertEqual(self.doc["class"], "objecttype")
        self.assertEqual(self.doc["oid"], "1.3")
        self.assertEqual(self.doc["units"], "seconds")
        self.assertEqual(self.doc["maxaccess"], "accessible-for-notify")
        self.assertEqual(self.doc["status"], "current")
        self.assertEqual(self.doc["description"], "Test object")
        self.assertEqual(self.doc["reference"], "ABC")
        self.assertEqual(self.doc["default"], {"value": 3, "format": "decimal"})
        self.assertEqual(
            self.doc["syntax"],
            {"type": "Integer32", "class": "type", "constraints": {"range": [{"min": 0, "max": 7}]}},
        )

    def testTheDocumentSpellsMaxAccessAsTheRfcDoes(self):
        # RFC 2578 section 7.3 names the value "accessible-for-notify". The
        # document is the interchange format, so it keeps the spelling from the
        # spec rather than the one the pysnmp backend needs.
        self.assertEqual(self.doc["maxaccess"], "accessible-for-notify")

    def testTheEmittedOidIsATupleOfIntegers(self):
        self.assertIn("MibScalar((1, 3), ", self.line)

    def testTheEmittedSyntaxAppliesTheConstraintBeforeTheDefault(self):
        # DEFVAL is a value of the sub-typed SYNTAX, not of the base type, so
        # .clone() has to be applied to the constrained type.
        self.assertIn("Integer32().subtype(subtypeSpec=ValueRangeConstraint(0, 7)).clone(3)", self.line)

    def testTheEmittedUnitsAreNotGuarded(self):
        # UNITS says what the value means, not what the object is for, so a
        # module loaded without texts still needs it.
        self.assertIn(".setUnits('seconds')", self.line)
        self.assertFalse(self.line.startswith("if mibBuilder.loadTexts:"))


class MaxAccessTestCase(unittest.TestCase):
    """RFC 2578 section 7.3 defines five MAX-ACCESS values."""

    #: The five values of section 7.3, and the spelling each one is emitted as.
    #: pysnmp holds the value verbatim, so a runtime assertion on
    #: getMaxAccess() cannot say which side dropped the hyphens. Reading the
    #: emitted line can. See pysnmp/pysmi#99.
    VALUES = (
        ("testNotAccessible", "not-accessible", "notaccessible"),
        ("testForNotify", "accessible-for-notify", "accessiblefornotify"),
        ("testReadOnly", "read-only", "readonly"),
        ("testReadWrite", "read-write", "readwrite"),
        ("testReadCreate", "read-create", "readcreate"),
    )

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(ACCESS_MIB)
        cls.lines = emitted_lines(render_source(ACCESS_MIB))

    def testTheDocumentKeepsTheRfcSpelling(self):
        for symbol, spelling, _ in self.VALUES:
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["maxaccess"], spelling)

    def testNotAccessibleIsEmittedRatherThanLeftToTheClassDefault(self):
        # pysnmp defaults MibScalar and MibTableColumn to "readonly", so
        # omitting the call does not make the object inaccessible -- it makes it
        # readable. See pysnmp/pysmi#128.
        self.assertIn('.setMaxAccess("notaccessible")', self.lines["testNotAccessible"])

    def testTheEmittedSourceDropsTheHyphens(self):
        for symbol, _, emitted in self.VALUES:
            with self.subTest(symbol=symbol):
                self.assertIn(f'.setMaxAccess("{emitted}")', self.lines[symbol])

    def testEveryStatusOfSection74IsCarried(self):
        # RFC 2578 section 7.4: current, deprecated, obsolete.
        for symbol, status in (
            ("testNotAccessible", "current"),
            ("testForNotify", "deprecated"),
            ("testReadOnly", "obsolete"),
        ):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["status"], status)


class SyntaxTestCase(unittest.TestCase):
    """RFC 2578 section 7.1 SYNTAX shapes, as pysmi renders them."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(SYNTAX_MIB, deps=[SNMPV2_SMI])
        cls.lines = emitted_lines(render_source(SYNTAX_MIB, deps=[SNMPV2_SMI]))

    def testARangeBecomesAValueRangeConstraint(self):
        self.assertEqual(
            self.doc["testRange"]["syntax"]["constraints"],
            {"range": [{"min": 0, "max": 4294967295}]},
        )
        self.assertIn("ValueRangeConstraint(0, 4294967295)", self.lines["testRange"])

    def testAValueSetBecomesAUnionOfSingleRanges(self):
        # RFC 2578 section 7.1.1 permits a set of values as well as a range.
        # Each alternative is its own range with equal bounds.
        self.assertEqual(
            self.doc["testValueSet"]["syntax"]["constraints"],
            {"range": [{"min": 0, "max": 0}, {"min": 2, "max": 2}, {"min": 44, "max": 44}]},
        )
        self.assertIn(
            "ConstraintsUnion(ValueRangeConstraint(0, 0), ValueRangeConstraint(2, 2), ValueRangeConstraint(44, 44), )",
            self.lines["testValueSet"],
        )

    def testASizeBecomesAValueSizeConstraint(self):
        self.assertEqual(self.doc["testSize"]["syntax"]["constraints"], {"size": [{"min": 0, "max": 512}]})
        self.assertIn("ValueSizeConstraint(0, 512)", self.lines["testSize"])

    def testBitsCarryTheirNamedPositions(self):
        # RFC 2578 section 7.1.4: a BITS value is a set of named bit positions.
        self.assertEqual(self.doc["testBits"]["syntax"]["bits"], {"notification": 0, "set": 1})
        self.assertIn('Bits().clone(namedValues=NamedValues(("notification", 0), ("set", 1)))', self.lines["testBits"])

    def testAnEnumerationCarriesItsNamedNumbers(self):
        # RFC 2578 section 7.1.1: an enumerated INTEGER names each value it
        # permits, and the enumeration is itself the constraint.
        self.assertEqual(self.doc["testEnum"]["syntax"]["constraints"]["enumeration"], {"enable": 1, "disable": 2})
        self.assertIn("SingleValueConstraint(1, 2)", self.lines["testEnum"])
        self.assertIn('NamedValues(("enable", 1), ("disable", 2))', self.lines["testEnum"])


class DefvalTestCase(unittest.TestCase):
    """RFC 2578 section 7.9 DEFVAL, one per value notation it allows."""

    @classmethod
    def setUpClass(cls):
        cls.doc = render_json(SYNTAX_MIB, deps=[SNMPV2_SMI])
        cls.lines = emitted_lines(render_source(SYNTAX_MIB, deps=[SNMPV2_SMI]))

    def testAnIntegerDefaultIsCarriedAsANumber(self):
        self.assertEqual(self.doc["testInteger"]["default"], {"value": 123456, "format": "decimal"})
        self.assertIn(".clone(123456)", self.lines["testInteger"])

    def testAStringDefaultIsCarriedAsText(self):
        self.assertEqual(self.doc["testString"]["default"], {"value": "test value", "format": "string"})
        self.assertIn(".clone('test value')", self.lines["testString"])

    def testAnEnumeratedDefaultIsCarriedByName(self):
        # RFC 2578 section 7.9: the DEFVAL of an enumerated INTEGER is written
        # as a label, and stays a label -- resolving it to its number here would
        # lose the only thing that makes the document readable.
        self.assertEqual(self.doc["testEnum"]["default"], {"value": "enable", "format": "enum"})
        self.assertIn(".clone('enable')", self.lines["testEnum"])

    def testAZeroDefaultIsNotDiscarded(self):
        # A falsy default is still a default. See the strict_equality note in
        # pyproject.toml for the bug this shape hid.
        self.assertEqual(self.doc["testRange"]["default"], {"value": 0, "format": "decimal"})
        self.assertIn(".clone(0)", self.lines["testRange"])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
