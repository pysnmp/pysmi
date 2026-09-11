#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Which arcs of the registration tree get a page, and where the rest resolve.

A page per OID any module defines is 95,603 pages and roughly 654 MB over
pysnmp/mibs' corpus, against a 1 GB limit -- the OID tree seventeen times the
module pages it exists to lead to, and a hundred thousand URLs for a crawler
to spend its budget on.

What is pinned here is the cut: a leaf arc is an object inside a module, an
arc at a module's anchor is the module, and what is left is the tree above
them. pysnmp/pysmi#292.
"""

import unittest

from pysmi.corpus.pages import (
    MODULE,
    OBJECT,
    Target,
    counts,
    resolve,
    structural_arcs,
)

#: An index over two modules under one vendor arc, plus a standard one. The
#: shape that matters: arcs above the anchors, and anchors themselves.
RANKED = {
    "1.3.6.1.4.1.9.9.138": "CISCO-ENTITY-ALARM-MIB",
    "1.3.6.1.4.1.9.9.42": "CISCO-PING-MIB",
    "1.3.6.1.2.1.31": "IF-MIB",
}

DESCRIPTORS = {
    "1.3.6.1.4.1.9.9.138.1.2.5.1.2": ("ceAlarmSeverity", "CISCO-ENTITY-ALARM-MIB"),
}


class StructuralTestCase(unittest.TestCase):
    """The arcs that get a page."""

    def setUp(self):
        self.structural = structural_arcs(RANKED)

    def testThePathDownToAnAnchorIsStructural(self):
        """The tree's job is to lead a reader from the root to a module."""
        for arc in ("1", "1.3", "1.3.6", "1.3.6.1", "1.3.6.1.4", "1.3.6.1.4.1"):
            with self.subTest(arc=arc):
                self.assertIn(arc, self.structural)

    def testAModulesOwnAnchorIsNotStructural(self):
        """That arc is the module, and the module page answers for it."""
        self.assertNotIn("1.3.6.1.4.1.9.9.138", self.structural)

    def testAVendorsSubdivisionsAreStructural(self):
        """Where a vendor subdivides its arc before hanging modules off it --
        depths 7 to 11 are the bulk of the real tree, and exactly the nodes a
        reader browses through."""
        self.assertIn("1.3.6.1.4.1.9", self.structural)
        self.assertIn("1.3.6.1.4.1.9.9", self.structural)

    def testALeafArcIsNotStructural(self):
        """It is an object inside a module, which the module page renders."""
        self.assertNotIn("1.3.6.1.4.1.9.9.138.1.2.5.1.2", self.structural)

    def testTheArcsAreInTreeOrder(self):
        """1.3.10 below 1.3.9 would be string order."""
        ranked = {"1.3.10.1": "A-MIB", "1.3.9.1": "B-MIB"}

        self.assertEqual(["1", "1.3", "1.3.9", "1.3.10"], list(structural_arcs(ranked)))

    def testAnArcThatIsBothAPrefixAndAnAnchorIsNotStructural(self):
        """A module registered above another one is still a module, and its
        page is the module page rather than a node of the tree."""
        ranked = {"1.3.6.1.4.1.9": "CISCO-SMI", "1.3.6.1.4.1.9.9.138": "OTHER-MIB"}

        structural = structural_arcs(ranked)

        self.assertNotIn("1.3.6.1.4.1.9", structural)
        self.assertIn("1.3.6.1.4.1.9.9", structural)

    def testAnEmptyCorpusHasNoTree(self):
        self.assertEqual((), structural_arcs({}))


class ResolveTestCase(unittest.TestCase):
    """Where an arc with no page of its own goes."""

    def testALeafArcResolvesToItsModuleAtAnAnchor(self):
        """The issue's own example."""
        self.assertEqual(
            Target("CISCO-ENTITY-ALARM-MIB", "ceAlarmSeverity", OBJECT),
            resolve("1.3.6.1.4.1.9.9.138.1.2.5.1.2", RANKED, DESCRIPTORS),
        )

    def testAModulesAnchorResolvesToTheModule(self):
        """That arc is the module, so there is no fragment to land on."""
        self.assertEqual(
            Target("CISCO-ENTITY-ALARM-MIB", "", MODULE),
            resolve("1.3.6.1.4.1.9.9.138", RANKED, DESCRIPTORS),
        )

    def testTheLongestPrefixWins(self):
        """The same lookup a trap receiver already runs against the index."""
        ranked = {"1.3.6.1.4.1.9": "CISCO-SMI", "1.3.6.1.4.1.9.9.138": "ALARM-MIB"}

        self.assertEqual("ALARM-MIB", resolve("1.3.6.1.4.1.9.9.138.1.2", ranked).module)

    def testAnUnknownDescriptorStillResolvesToTheModule(self):
        """Landing on the module page without a fragment beats not landing."""
        found = resolve("1.3.6.1.4.1.9.9.138.1.9.9", RANKED)

        self.assertEqual("CISCO-ENTITY-ALARM-MIB", found.module)
        self.assertEqual("", found.anchor)
        self.assertEqual(OBJECT, found.reason)

    def testAnOidTheCorpusCannotAnswerForResolvesToNothing(self):
        """Better than handing back the nearest module it happens to hold."""
        self.assertIsNone(resolve("2.999.1", RANKED))

    def testAStructuralArcIsNotResolvedAway(self):
        """It has a page of its own, so nothing should be redirecting it."""
        self.assertIsNone(resolve("1.3.6.1.4.1.9.9", RANKED))


class CountsTestCase(unittest.TestCase):
    """What the build report is told."""

    def testTheTwoHalvesAddUpToTheArcInventory(self):
        """structural + anchors is the arc set pysmi.corpus.arcs names, which
        is the same arithmetic as the issue's 1,347 + 5,347 = 6,694."""
        structural = structural_arcs(RANKED)
        tally = counts(RANKED, structural)

        self.assertEqual(len(structural), tally["structural"])
        self.assertEqual(len(RANKED), tally["anchors"])
        self.assertEqual(tally["structural"] + tally["anchors"], tally["arcs"])


if __name__ == "__main__":
    unittest.main()
