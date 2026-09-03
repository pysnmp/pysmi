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

from tests import test_reference_smiv2_pysnmp as reference_fixtures
from tests.harness import render_source

#: A module carrying every macro that takes a REFERENCE clause.
MACROS_MIB = reference_fixtures.ReferenceTestCase.__doc__

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

#: RFC 2580 gives these three a REFERENCE clause, but pysnmp has nowhere to put
#: it: their classes have no ``setReference``. pysmi carries the text to the JSON
#: document instead of emitting a call that would fail on load. See
#: pysnmp/pysmi#101 and pysnmp/pysnmp#133.
WITHOUT_SET_REFERENCE = ("testObjectGroup", "testNotificationGroup", "testModuleCompliance")

#: The macros whose pysnmp classes do take a REFERENCE.
WITH_SET_REFERENCE = ("testObjectIdentity", "testObjectType", "testNotificationType", "testAgentCapabilities")


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
            emitted.update(setter for setter in NARRATIVE_SETTERS if setter_lines(pycode, setter))

        self.assertEqual(emitted, set(NARRATIVE_SETTERS))

    def testNarrativeSettersVanishWithoutTexts(self):
        for setter in ("setDescription", "setReference"):
            with self.subTest(setter=setter):
                self.assertEqual(setter_lines(render_source(MACROS_MIB, genTexts=False), setter), [])

    def testStatusSurvivesWithoutTexts(self):
        # STATUS says whether an object may still be used, which is not
        # narrative. It is emitted either way.
        self.assertNotEqual(setter_lines(render_source(MACROS_MIB, genTexts=False), "setStatus"), [])


class ConformanceReferenceTestCase(unittest.TestCase):
    """REFERENCE is emitted only for the classes that can hold one."""

    def setUp(self):
        self.pycode = render_source(MACROS_MIB)

    def testTheClassesWithoutASetterGetNoCall(self):
        for name in WITHOUT_SET_REFERENCE:
            with self.subTest(symbol=name):
                self.assertNotIn(f"{name}.setReference(", self.pycode)

    def testTheClassesWithASetterGetOne(self):
        for name in WITH_SET_REFERENCE:
            with self.subTest(symbol=name):
                self.assertEqual(self.pycode.count(f"{name}.setReference("), 1)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
