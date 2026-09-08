#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Assert on the source pysmi emits, not on what pysnmp makes of it.

Every other pysnmp test compiles the generated module, runs it, and inspects the
objects that built. That cannot see a setter emitted without its
``mibBuilder.loadTexts`` guard, because the harness loads texts: a guard that is
missing and a guard that is satisfied leave the same objects behind. Only the
source says which one was written. See pysnmp/pysmi#99 for the shape, and
pysnmp/pysmi#101 for the bug it hid.
"""

import sys
import unittest

from tests.harness import render_source
from tests.test_spec_reference import MACROS_MIB

MODULE_IDENTITY_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "Module."
    REVISION     "202401010000Z"
    DESCRIPTION  "Revised."
    ::= { 1 3 0 }

END
"""

#: A module carrying one of each construct, to read the emitted line for each.
CONSTRUCTS_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, MODULE-IDENTITY, OBJECT-IDENTITY, NOTIFICATION-TYPE,
    Integer32
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

testModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "C."
    DESCRIPTION  "M."
    ::= { 1 3 0 }

TestTC ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "tc"
    SYNTAX       OCTET STRING (SIZE (0..255))

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "oi"
    ::= { testModule 9 }

testScalar OBJECT-TYPE
    SYNTAX      Integer32 (0..7)
    UNITS       "widgets"
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "s"
    DEFVAL      { 3 }
    ::= { testModule 2 }

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "t"
    ::= { testModule 1 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "e"
    INDEX       { IMPLIED testIndex }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE { testIndex Integer32, testNotify Integer32 }

testIndex OBJECT-TYPE
    SYNTAX      Integer32 (1..100)
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "i"
    ::= { testEntry 1 }

testNotify OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  accessible-for-notify
    STATUS      deprecated
    DESCRIPTION "n"
    ::= { testEntry 2 }

testNotification NOTIFICATION-TYPE
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "nt"
    ::= { testModule 3 }

END
"""

#: The line pysmi puts in front of a setter whose value pysnmp keeps only when
#: it has been asked to load texts.
GUARD = "if mibBuilder.loadTexts:"

#: Setters for clauses that only describe a module to a reader. Each one has to
#: be emitted behind the guard, or a module compiled with texts cannot be loaded
#: without them.
NARRATIVE_SETTERS = (
    "setDescription",
    "setReference",
    "setLastUpdated",
    "setOrganization",
    "setContactInfo",
)

#: RFC 2580 gives these three a REFERENCE clause. pysmi used to drop it,
#: because their pysnmp classes had no ``setReference``; pysnmp added the
#: setters in pysnmp/pysnmp#133 and loader contract v1 states them, so the call
#: is emitted now. See pysnmp/pysmi#101 and pysnmp/pysmi#194.
FORMERLY_SUPPRESSED = (
    "testObjectGroup",
    "testNotificationGroup",
    "testModuleCompliance",
)

#: Every macro in MACROS_MIB whose pysnmp class takes a REFERENCE, which under
#: loader contract v1 is every macro that may carry the clause.
WITH_SET_REFERENCE = (
    "testObjectIdentity",
    "testObjectType",
    "testNotificationType",
    "testAgentCapabilities",
    *FORMERLY_SUPPRESSED,
)


def setter_lines(pycode, setter):
    """Return every emitted line calling *setter*."""
    return [line for line in pycode.splitlines() if f".{setter}(" in line]


class NarrativeGuardTestCase(unittest.TestCase):
    """A narrative clause is emitted behind the loadTexts guard, or not at all."""

    def testEveryNarrativeSetterIsGuarded(self):
        for mib in (MACROS_MIB, MODULE_IDENTITY_MIB):
            pycode = render_source(mib)
            for setter in NARRATIVE_SETTERS:
                for line in setter_lines(pycode, setter):
                    with self.subTest(setter=setter, line=line.strip()):
                        self.assertTrue(line.strip().startswith(GUARD))

    def testEverySetterIsReachedAtLeastOnce(self):
        # The guard assertion passes vacuously on a setter nothing emits, which
        # would leave the invariant untested the day one stops being emitted.
        emitted = set()
        for mib in (MACROS_MIB, MODULE_IDENTITY_MIB):
            pycode = render_source(mib)
            emitted.update(
                setter for setter in NARRATIVE_SETTERS if setter_lines(pycode, setter)
            )

        self.assertEqual(emitted, set(NARRATIVE_SETTERS))

    def testNarrativeSettersVanishWithoutTexts(self):
        for setter in ("setDescription", "setReference"):
            with self.subTest(setter=setter):
                self.assertEqual(
                    setter_lines(render_source(MACROS_MIB, genTexts=False), setter), []
                )

    def testStatusSurvivesWithoutTexts(self):
        # STATUS says whether an object may still be used, which is not
        # narrative. It is emitted either way.
        self.assertNotEqual(
            setter_lines(render_source(MACROS_MIB, genTexts=False), "setStatus"), []
        )


class ConformanceReferenceTestCase(unittest.TestCase):
    """REFERENCE is emitted for every macro that may carry one."""

    def setUp(self):
        self.pycode = render_source(MACROS_MIB)

    def testTheFormerlySuppressedClassesGetACall(self):
        for name in FORMERLY_SUPPRESSED:
            with self.subTest(symbol=name):
                self.assertEqual(self.pycode.count(f"{name}.setReference("), 1)

    def testTheClassesWithASetterGetOne(self):
        for name in WITH_SET_REFERENCE:
            with self.subTest(symbol=name):
                self.assertEqual(self.pycode.count(f"{name}.setReference("), 1)


class ConstructTestCase(unittest.TestCase):
    """What each construct is emitted as.

    The runtime assertions elsewhere can only see what pysnmp made of a line.
    These read the line. See pysnmp/pysmi#99.
    """

    @classmethod
    def setUpClass(cls):
        cls.pycode = render_source(CONSTRUCTS_MIB)
        cls.lines = {
            line.split(" = ", 1)[0]: line
            for line in cls.pycode.splitlines()
            if " = " in line and "import" not in line
        }

    def line(self, symbol):
        self.assertIn(symbol, self.lines, f"{symbol} was not emitted")
        return self.lines[symbol]

    def testEachConstructPicksItsNodeClass(self):
        for symbol, cls in (
            ("testModule", "ModuleIdentity"),
            ("testIdentity", "ObjectIdentity"),
            ("testScalar", "MibScalar"),
            ("testTable", "MibTable"),
            ("testEntry", "MibTableRow"),
            ("testIndex", "MibTableColumn"),
            ("testNotification", "NotificationType"),
        ):
            with self.subTest(symbol=symbol):
                self.assertIn(f"= {cls}((", self.line(symbol))

    def testAnOidIsEmittedAsATupleOfIntegers(self):
        self.assertIn("MibTableColumn((1, 3, 0, 1, 1, 1), ", self.line("testIndex"))

    def testMaxAccessIsEmittedWithoutItsHyphens(self):
        # pysnmp does not normalise this: the value it hands back is the one
        # written here. A runtime assertion on getMaxAccess() cannot tell which
        # side dropped the hyphens, so it goes unread.
        for symbol, access in (
            ("testScalar", "readwrite"),
            ("testIndex", "readcreate"),
            ("testNotify", "accessiblefornotify"),
        ):
            with self.subTest(symbol=symbol):
                self.assertIn(f'.setMaxAccess("{access}")', self.line(symbol))

    def testStructuralSettersAreNotGuarded(self):
        # These say what an object is, not what it is for, so a module loaded
        # without texts still needs them.
        for symbol, setter in (
            ("testScalar", ".setUnits("),
            ("testScalar", ".setMaxAccess("),
            ("testEntry", ".setIndexNames("),
            ("testNotification", ".setObjects("),
        ):
            with self.subTest(symbol=symbol, setter=setter):
                line = self.line(symbol)
                self.assertIn(setter, line)
                self.assertFalse(line.startswith(GUARD))

    def testAConstraintIsAppliedBeforeADefault(self):
        # .clone() carries the DEFVAL and has to be applied to the subtyped
        # syntax, not the other way round.
        self.assertIn(
            "Integer32().subtype(subtypeSpec=ValueRangeConstraint(0, 7)).clone(3)",
            self.line("testScalar"),
        )

    def testAnImpliedIndexIsFlaggedInTheIndexNames(self):
        self.assertIn(
            '.setIndexNames((1, "TEST-MIB", "testIndex"))', self.line("testEntry")
        )

    def testATextualConventionIsAClassAheadOfItsBaseType(self):
        # TextualConvention has to come first, or its display hint loses to the
        # base type's rendering.
        self.assertIn("class TestTC(TextualConvention, OctetString):", self.pycode)
        self.assertIn(
            "subtypeSpec = OctetString.subtypeSpec + ValueSizeConstraint(0, 255)",
            self.pycode,
        )

    def testEverySymbolDefinedIsAlsoExported(self):
        exported = self.pycode.rsplit("exportSymbols(", 1)[1]
        for symbol in (
            "TestTC",
            "testEntry",
            "testIdentity",
            "testIndex",
            "testNotification",
            "testScalar",
        ):
            with self.subTest(symbol=symbol):
                self.assertIn(f"{symbol}=", exported)


def _many_objects_mib(count):
    """A MIB whose OBJECT-GROUP names *count* objects.

    ``setObjects()`` takes at most 255 at a time, so above that the generator
    emits a loop that appends in batches. Built here rather than written out
    because the interesting sizes are larger than a fixture should be.
    """
    objects = "\n".join(
        f"""testObject{i} OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Object {i}."
    ::= {{ 1 3 1 {i} }}"""
        for i in range(count)
    )
    names = ", ".join(f"testObject{i}" for i in range(count))
    return f"""
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP
        FROM SNMPv2-CONF;

{objects}

testGroup OBJECT-GROUP
    OBJECTS     {{ {names} }}
    STATUS      current
    DESCRIPTION "Every object."
    ::= {{ 1 3 2 }}

END
"""


class BatchedSetObjectsTestCase(unittest.TestCase):
    """An OBJECT-GROUP too large for one setObjects() call.

    ``setObjects()`` accepts 255 arguments, so a group naming more is emitted
    as a loop over batches. Every batch after the first has to append, or the
    ones before it are discarded -- which is what the generated code used to
    warn about, in a branch taken on any pysnmp older than 4.4.2. Loader
    contract v1 states ``setObjects(..., append=True)``, so the branch is gone
    and the append is unconditional. See pysnmp/pysnmp#197.
    """

    @classmethod
    def setUpClass(cls):
        cls.small = render_source(_many_objects_mib(3))
        cls.large = render_source(_many_objects_mib(260))

    def testAGroupThatFitsIsOneCall(self):
        # Chained onto the constructor, so there is no loop and no append.
        self.assertIn("testGroup = ObjectGroup((1, 3, 2)).setObjects(", self.small)
        self.assertNotIn("for _testGroup_obj", self.small)
        self.assertNotIn("append=True", self.small)

    def testAGroupThatDoesNotFitIsALoop(self):
        self.assertIn("for _testGroup_obj in [", self.large)

    def testEveryBatchAppends(self):
        # Without this the first 255 are replaced by the last 5.
        self.assertIn(
            "testGroup = testGroup.setObjects(*_testGroup_obj, **dict(append=True))",
            self.large,
        )

    def testTheLoopTestsNoLoaderVersion(self):
        self.assertNotIn("getattr(mibBuilder", self.large)
        self.assertNotIn("Upgrade your pysnmp", self.large)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
