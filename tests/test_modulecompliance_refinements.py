#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""RFC 2580 sections 5.4.2 and 5.4.3: the GROUP and OBJECT sub-clauses.

A GROUP names a group and states the condition it applies under. An OBJECT
names an object and narrows what an implementation must support for it. Both
used to be discarded in the parser, so neither backend could see them.

The pysnmp backend still emits only the names, because pysnmp's
``ModuleCompliance`` has nowhere to put the rest. The JSON document carries it.
"""

import unittest

from tests.harness import render_json, render_source

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI

    MODULE-COMPLIANCE, OBJECT-GROUP
        FROM SNMPv2-CONF;

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "An object a compliance refines."
    ::= { 1 3 1 }

testOther OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "An object a compliance only weakens access to."
    ::= { 1 3 2 }

testGroup OBJECT-GROUP
    OBJECTS     { testObject, testOther }
    STATUS      current
    DESCRIPTION "A group."
    ::= { 1 3 3 }

conditionalGroup OBJECT-GROUP
    OBJECTS     { testOther }
    STATUS      current
    DESCRIPTION "A group that is not always required."
    ::= { 1 3 4 }

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "A compliance."
    MODULE
        MANDATORY-GROUPS { testGroup }

        GROUP        conditionalGroup
        DESCRIPTION  "Required only for implementations that do X."

        OBJECT       testObject
        SYNTAX       INTEGER (0..7)
        WRITE-SYNTAX INTEGER (0..3)
        MIN-ACCESS   read-only
        DESCRIPTION  "Write support is not required."

        OBJECT       testOther
        MIN-ACCESS   not-accessible
        DESCRIPTION  "Need not be implemented at all."
    ::= { 1 3 5 }

END
"""

PLAIN_MIB = MIB.replace(
    """
        GROUP        conditionalGroup
        DESCRIPTION  "Required only for implementations that do X."

        OBJECT       testObject
        SYNTAX       INTEGER (0..7)
        WRITE-SYNTAX INTEGER (0..3)
        MIN-ACCESS   read-only
        DESCRIPTION  "Write support is not required."

        OBJECT       testOther
        MIN-ACCESS   not-accessible
        DESCRIPTION  "Need not be implemented at all."
""",
    "",
)


class RefinementTestCase(unittest.TestCase):
    def setUp(self):
        self.doc = render_json(MIB)
        self.source = render_source(MIB)
        self.refinements = self.doc["testCompliance"]["refinements"]

    def testWhatTheComplianceRequiresIsUnchanged(self):
        # The name list is what a compliance requires, and it must not move
        # when the sub-clause detail starts riding alongside it. A GROUP
        # contributes its name here; an OBJECT does not.
        self.assertEqual(
            self.doc["testCompliance"]["modulecompliance"],
            [
                {"object": "testGroup", "module": "TEST-MIB"},
                {"object": "conditionalGroup", "module": "TEST-MIB"},
            ],
        )

    def testTheGroupConditionIsCarried(self):
        self.assertEqual(
            self.refinements[0],
            {
                "module": "TEST-MIB",
                "object": "conditionalGroup",
                "kind": "group",
                "description": "Required only for implementations that do X.",
            },
        )

    def testTheObjectRefinementIsCarried(self):
        self.assertEqual(
            self.refinements[1],
            {
                "module": "TEST-MIB",
                "object": "testObject",
                "kind": "object",
                "syntax": {
                    "type": "INTEGER",
                    "class": "type",
                    "constraints": {"range": [{"min": 0, "max": 7}]},
                },
                "writesyntax": {
                    "type": "INTEGER",
                    "class": "type",
                    "constraints": {"range": [{"min": 0, "max": 3}]},
                },
                "minaccess": "read-only",
                "description": "Write support is not required.",
            },
        )

    def testARefinementOmitsWhatItDoesNotNarrow(self):
        self.assertEqual(
            self.refinements[2],
            {
                "module": "TEST-MIB",
                "object": "testOther",
                "kind": "object",
                "minaccess": "not-accessible",
                "description": "Need not be implemented at all.",
            },
        )

    def testTheTwoKindsAreDistinguishable(self):
        self.assertEqual([r["kind"] for r in self.refinements], ["group", "object", "object"])

    def testTheGeneratedSourceStillCarriesOnlyTheNames(self):
        # pysnmp's ModuleCompliance has no attribute for any of this, so the
        # pysnmp backend deliberately emits none of it. See pysnmp/pysnmp#133.
        self.assertIn(
            "testCompliance = ModuleCompliance((1, 3, 5)).setObjects("
            '("TEST-MIB", "testGroup"), ("TEST-MIB", "conditionalGroup"))',
            self.source,
        )
        for dropped in ("minaccess", "writesyntax", "setRefinements"):
            with self.subTest(clause=dropped):
                self.assertNotIn(dropped, self.source)


class WithoutRefinementsTestCase(unittest.TestCase):
    def testAComplianceThatRefinesNothingHasNoKey(self):
        doc = render_json(PLAIN_MIB)
        self.assertNotIn("refinements", doc["testCompliance"])
        self.assertEqual(
            doc["testCompliance"]["modulecompliance"],
            [{"object": "testGroup", "module": "TEST-MIB"}],
        )


class WithoutTextsTestCase(unittest.TestCase):
    def setUp(self):
        self.doc = render_json(MIB, genTexts=False)
        self.refinements = self.doc["testCompliance"]["refinements"]

    def testAGroupIsDroppedBecauseItsConditionIsAllItHas(self):
        self.assertEqual([r["kind"] for r in self.refinements], ["object", "object"])

    def testAnObjectSurvivesBecauseItsRefinementIsStructural(self):
        self.assertEqual(self.refinements[0]["object"], "testObject")
        self.assertEqual(self.refinements[0]["minaccess"], "read-only")
        self.assertEqual(self.refinements[0]["syntax"]["constraints"], {"range": [{"min": 0, "max": 7}]})

    def testNoDescriptionSurvives(self):
        for refinement in self.refinements:
            with self.subTest(object=refinement["object"]):
                self.assertNotIn("description", refinement)


if __name__ == "__main__":
    unittest.main()
