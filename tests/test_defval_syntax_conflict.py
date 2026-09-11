#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A DEFVAL that contradicts its object's own SYNTAX is dropped, not emitted.

pysmi 1.1.12 dropped these defaults silently; 2.0.x emitted them. Neither
validated them. Emitted, the default is a ``clone()`` on the constrained type,
so pyasn1 raises while the module is being imported and the whole module --
along with every module importing it -- fails to load. A full-corpus A/B over
pysnmp/mibs put that at 35 newly unloadable modules.

Emitting the DEFVAL is the more correct behaviour in general, so the fix is to
check it rather than to go back to dropping every one. A violation is dropped
rather than clamped: a value moved into range is one the MIB never stated.

The constraints reach the codegens through the symbol table, which used to
discard every SIZE and range it read. See pysnmp/pysmi#134.
"""

import logging
import sys
import unittest

from pysmi.codegen import PySnmpCodeGen
from tests.harness import render_json, render_source
from tests.mibs import SNMPV2_SMI, SNMPV2_TC

DEPS = (SNMPV2_SMI, SNMPV2_TC)

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, Unsigned32, IpAddress
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION, DisplayString
        FROM SNMPv2-TC;

SizedString ::= TEXTUAL-CONVENTION
    STATUS      current
    DESCRIPTION "A convention carrying a size of its own."
    SYNTAX      OCTET STRING (SIZE (4..8))

testObject OBJECT-TYPE
    SYNTAX      %s
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "The object under test."
    DEFVAL      { %s }
    ::= { 1 3 1 }

END
"""


def default(syntax, defval):
    """Return the JSON default and the emitted line for one SYNTAX/DEFVAL pair."""
    mib = MIB % (syntax, defval)
    line = next(
        x
        for x in render_source(mib, deps=DEPS).splitlines()
        if x.startswith("testObject =")
    )
    return render_json(mib, deps=DEPS)["testObject"].get("default"), line


class DroppedDefaultTestCase(unittest.TestCase):
    """Both backends drop a default no constraint on the object permits."""

    def assertDropped(self, syntax, defval):
        json, emitted = default(syntax, defval)
        self.assertIsNone(json, f"JSON kept a default {syntax} forbids")
        self.assertNotIn(
            ".clone(", emitted, f"pysnmp source kept a default {syntax} forbids"
        )

    def assertKept(self, syntax, defval, clone):
        json, emitted = default(syntax, defval)
        self.assertIsNotNone(json, f"JSON dropped a default {syntax} permits")
        self.assertIn(
            clone, emitted, f"pysnmp source dropped a default {syntax} permits"
        )


class SizeConflictTestCase(DroppedDefaultTestCase):
    """RFC 2578 Section 7.9 against a SIZE the value cannot satisfy.

    The empty string is the case behind the report: ``EQLVOLUME-MIB`` documents
    a "not a clone" sentinel its own ``SIZE (16)`` forbids.
    """

    def testEmptyStringUnderARangeOfSizes(self):
        self.assertDropped("OCTET STRING (SIZE (1..31))", '""')

    def testEmptyStringUnderAFixedSize(self):
        self.assertDropped("OCTET STRING (SIZE (16))", '""')

    def testEmptyStringIsKeptWhereTheSizeAllowsIt(self):
        self.assertKept("OCTET STRING (SIZE (0..31))", '""', ".clone('')")

    def testAnUnconstrainedStringKeepsItsEmptyDefault(self):
        # The pre-existing rule for a bare OCTET STRING is untouched.
        self.assertKept("OCTET STRING", '""', "OctetString().clone('')")

    def testTooLongIsDroppedAsWellAsTooShort(self):
        self.assertDropped("OCTET STRING (SIZE (1..4))", '"toolong"')


class RangeConflictTestCase(DroppedDefaultTestCase):
    """A numeric default outside every range the object permits."""

    def testBelowTheLowerBound(self):
        self.assertDropped("Unsigned32 (1..255)", "0")

    def testAboveTheUpperBound(self):
        self.assertDropped("Unsigned32 (1..255)", "256")

    def testInsideTheRangeSurvives(self):
        self.assertKept("Unsigned32 (1..255)", "5", ".clone(5)")

    def testBetweenTwoRangesIsDropped(self):
        self.assertDropped("Integer32 (1..10 | 20..30)", "15")

    def testInsideTheSecondRangeSurvives(self):
        self.assertKept("Integer32 (1..10 | 20..30)", "25", ".clone(25)")

    def testTheBoundsThemselvesAreInclusive(self):
        self.assertKept("Unsigned32 (1..255)", "1", ".clone(1)")
        self.assertKept("Unsigned32 (1..255)", "255", ".clone(255)")


class ValueKindConflictTestCase(DroppedDefaultTestCase):
    """RFC 2578 Section 7.9 gives a string-valued object a string default.

    ``IpAddress`` is the case that reaches pyasn1 as ``ProtocolError: Bad IP
    address syntax`` rather than a constraint failure.
    """

    def testNumericDefaultForIpAddress(self):
        self.assertDropped("IpAddress", "0")

    def testNumericDefaultForAnOctetString(self):
        self.assertDropped("OCTET STRING", "0")

    def testHexadecimalDefaultForIpAddressSurvives(self):
        self.assertKept(
            "IpAddress", "'C0000201'H", 'IpAddress().clone(hexValue="C0000201")'
        )

    def testHexadecimalDefaultOfTheWrongWidthIsDropped(self):
        # SNMPv2-SMI gives IpAddress SIZE (4); three octets is not an address.
        self.assertDropped("IpAddress", "'C00002'H")


class InheritedConstraintTestCase(DroppedDefaultTestCase):
    """A constraint counts wherever on the derivation chain it was written.

    ``get_base_type`` resolves an object to its base type; the restrictions
    picked up on the way are what the check needs, and a refinement written on
    the object is only the innermost of them.
    """

    def testAConventionsOwnSizeIsEnforced(self):
        # The object writes no SIZE at all; SizedString carries SIZE (4..8).
        self.assertDropped("SizedString", '""')

    def testAConventionsOwnSizeStillAdmitsAValidDefault(self):
        self.assertKept("SizedString", '"abcd"', ".clone('abcd')")

    def testARefinementNarrowsTheConvention(self):
        # DisplayString is SIZE (0..255) and would permit the empty string; the
        # refinement written on the object does not.
        self.assertDropped("DisplayString (SIZE (1..8))", '""')

    def testARefinedConventionKeepsAConformingDefault(self):
        self.assertKept("DisplayString (SIZE (0..32))", '"hello"', ".clone('hello')")


class HexAndBinaryConflictTestCase(DroppedDefaultTestCase):
    """RFC 2578 Section 7.9 also writes a default in hexadecimal or binary.

    Both are read against the base type the object resolves to: as a number
    where that is an integer -- the MIB bug ``gen_def_val`` already absorbs --
    and as octets otherwise. Each reading has its own constraint to answer to.
    """

    def testHexadecimalReadAsANumberOutOfRange(self):
        self.assertDropped("Integer32 (1..255)", "'FFFF'H")

    def testHexadecimalReadAsANumberInRange(self):
        self.assertKept("Integer32 (1..255)", "'0A'H", ".clone(10)")

    def testBinaryReadAsANumberOutOfRange(self):
        self.assertDropped("Integer32 (1..10)", "'11111111'B")

    def testBinaryReadAsANumberInRange(self):
        self.assertKept("Integer32 (1..255)", "'1010'B", ".clone(10)")

    def testBinaryReadAsOctetsOfTheWrongWidth(self):
        # '1010'B is one octet; the object takes four.
        self.assertDropped("OCTET STRING (SIZE (4))", "'1010'B")

    def testHexadecimalReadAsOctetsOfTheRightWidth(self):
        self.assertKept(
            "OCTET STRING (SIZE (4))", "'C0000201'H", '.clone(hexValue="C0000201")'
        )

    def testHexadecimalReadAsOctetsOfTheWrongWidth(self):
        self.assertDropped("OCTET STRING (SIZE (2))", "'C0000201'H")


class ConstraintLookupTestCase(unittest.TestCase):
    """The lookup answers for a symbol table a MIB cannot produce.

    These two paths are what stop a malformed module turning into a traceback
    rather than a rendered MIB, so they are exercised against a symbol table
    written by hand: reaching either through the parser would need a module the
    grammar rejects before the symbol table is ever built.
    """

    def codegen(self, symbolTable):
        codegen = PySnmpCodeGen()
        codegen.symbolTable = symbolTable
        return codegen

    def testAMalformedBoundYieldsNoConstraint(self):
        # An empty binary string has no digits to convert. Reporting no
        # constraint leaves the renderer to reject it, rather than building one
        # no value could satisfy.
        self.assertEqual(self.codegen({}).value_ranges("range", [[("''b", "10")]]), "")

    def testAnEmptyRangeListYieldsNoConstraint(self):
        self.assertEqual(self.codegen({}).value_ranges("size", [[]]), "")

    def testASymbolOutsideTheTableIsNotConstrained(self):
        codegen = self.codegen({"TEST-MIB": {}})
        self.assertEqual(codegen.get_value_ranges("absent", "TEST-MIB"), [])
        self.assertEqual(codegen.get_value_ranges("absent", "NO-SUCH-MIB"), [])

    def testATypeDerivedFromItselfTerminates(self):
        # A circular derivation is a broken MIB, but the walk must end.
        codegen = self.codegen(
            {
                "TEST-MIB": {
                    "Ouroboros": {"syntax": (("Snake", "TEST-MIB"), "")},
                    "Snake": {"syntax": (("Ouroboros", "TEST-MIB"), "")},
                }
            }
        )
        self.assertEqual(codegen.get_value_ranges("Ouroboros", "TEST-MIB"), [])


class WarningTestCase(unittest.TestCase):
    """The drop is loud. 1.1.12 was silent, which is how this went unnoticed.

    The parent logger is watched rather than one backend's: a size or range is
    checked in the shared helper, while a numeric default for a string-valued
    object is rejected by each backend in turn.
    """

    def testTheViolationIsNamed(self):
        with self.assertLogs("pysmi.codegen", level=logging.WARNING) as captured:
            render_source(MIB % ("OCTET STRING (SIZE (1..31))", '""'), deps=DEPS)

        message = "\n".join(captured.output)
        self.assertIn("testObject", message, "the warning does not name the object")
        self.assertIn("TEST-MIB", message, "the warning does not name the module")
        self.assertIn(
            "SIZE (1..31)", message, "the warning does not name the constraint"
        )

    def testAConformingDefaultWarnsAboutNothing(self):
        logger = logging.getLogger("pysmi.codegen")
        with self.assertLogs(logger, level=logging.WARNING) as captured:
            render_source(MIB % ("OCTET STRING (SIZE (0..31))", '""'), deps=DEPS)
            logger.warning("nothing else was logged")

        self.assertEqual(len(captured.output), 1, "a conforming default warned")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
