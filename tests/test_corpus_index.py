#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Which module owns an OID two of them define, and why.

The published index answers one question -- given an OID, which module do I
load -- and splunk-connect-for-snmp asks it on every trap. Where two modules
define the same arc there is one answer and it has to come from a rule, not
from whichever module the build happened to read last.

These tests pin the rule term by term, and pin the frozen-snapshot replay
that keeps the legacy index answering what it has always answered.
"""

import unittest

from pysmi.corpus.arcs import prefixes
from pysmi.corpus.index import (
    anchor_index,
    arcs,
    merge_frozen,
    newest_revision,
    oids_of,
    rank_index,
    read_index,
    read_stamp,
    render_index,
    revision_rank,
)


def document(oid, *, cls="moduleidentity", revisions=(), objects=()):
    """A jsondoc carrying one anchor, and whatever objects were asked for."""
    doc = {
        "anchor": {
            "class": cls,
            "oid": oid,
            "revisions": [{"revision": x} for x in revisions],
        }
    }

    for name, status in objects:
        doc[name] = {"class": "objecttype", "oid": f"{oid}.1", "status": status}

    return doc


class RevisionTestCase(unittest.TestCase):
    """Revisions are read as dates, or not read at all."""

    def testShortFormWidens(self):
        self.assertEqual(
            "199908190000Z", newest_revision(document("1.3", revisions=["9908190000Z"]))
        )

    def testNewestOfSeveralWins(self):
        self.assertEqual(
            "200210160000Z",
            newest_revision(
                document("1.3", revisions=["9908190000Z", "200210160000Z"])
            ),
        )

    def testAStampThatIsNotADateIsRefused(self):
        # HPR-MIB is published with LAST-UPDATED "970514000000Z" -- thirteen
        # characters, so it rides a length check, but month 14 of year 9705.
        # Ranked as written it sorts above every date there will ever be, and
        # the module carrying it wins every collision it takes part in, for
        # good. This is the digit-strip defect that pysnmp/mibs' index.py
        # carries and pysnmp/pysmi#209 removed from the compiler.
        self.assertEqual(
            "", newest_revision(document("1.3", revisions=["970514000000Z"]))
        )

    def testARealDateOutranksAnUnreadableOne(self):
        real = revision_rank(document("1.3", revisions=["200502010000Z"]))
        bogus = revision_rank(document("1.3", revisions=["970514000000Z"]))

        self.assertLess(real, bogus)

    def testNoRevisionRanksLast(self):
        self.assertEqual(0, revision_rank(document("1.3")))


class StampTestCase(unittest.TestCase):
    """Both spellings a revision reaches the ranking in."""

    def testTheJsondocSpellingIsRead(self):
        # JsonCodeGen renders a revision as YYYY-MM-DD HH:MM, so a ranking
        # that only understood raw ExtUTCTime would read every module in the
        # corpus as undated and fall through to the module name.
        self.assertEqual("201703100000Z", read_stamp("2017-03-10 00:00"))

    def testTheRawSpellingIsRead(self):
        self.assertEqual("200210160000Z", read_stamp("200210160000Z"))

    def testLastUpdatedCountsAsARevision(self):
        doc = {
            "anchor": {
                "class": "moduleidentity",
                "oid": "1.3.6",
                "lastupdated": "2020-01-01 00:00",
            }
        }

        self.assertEqual("202001010000Z", newest_revision(doc))

    def testAJsondocStampThatIsNotADateIsRefused(self):
        # format_ext_utc_time cannot read 970514000000Z either; what reaches
        # the ranking is whatever it substituted, and a digit-strip would
        # take year 9705 at face value.
        self.assertIsNone(read_stamp("9705-14-00 00:00"))

    def testSomethingElseEntirelyIsRefused(self):
        self.assertIsNone(read_stamp("last thursday"))


class RankTestCase(unittest.TestCase):
    """The five terms, each on its own."""

    def _winner(self, first, second):
        return rank_index([first, second])["1.3.6.1.4.1.99"]

    def testLiveBeatsObsolete(self):
        oid = "1.3.6.1.4.1.99"
        obsolete = document(oid, objects=[("a", "obsolete")])
        current = document(oid, objects=[("a", "current")])

        self.assertEqual(
            "LIVE",
            self._winner(("OBSOLETE", obsolete, 0, 0), ("LIVE", current, 0, 0)),
        )

    def testStandardBeatsVendor(self):
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "STANDARD",
            self._winner(
                ("VENDOR", document(oid), 2, 0), ("STANDARD", document(oid), 0, 0)
            ),
        )

    def testTierOutranksRevision(self):
        # A vendor module refreshed last week does not take an arc from the
        # standard module that defines it.
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "STANDARD",
            self._winner(
                ("VENDOR", document(oid, revisions=["202401010000Z"]), 2, 0),
                ("STANDARD", document(oid, revisions=["199001010000Z"]), 0, 0),
            ),
        )

    def testOwnerBeatsMention(self):
        # CLAB-DEF-MIB registers clabTopoMib with an OBJECT-IDENTITY so its
        # siblings can hang objects off it; CLAB-TOPO-MIB is the module that
        # arc belongs to.
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "OWNER",
            self._winner(
                ("MENTION", document(oid, cls="objectidentity"), 0, 0),
                ("OWNER", document(oid), 0, 0),
            ),
        )

    def testNewestRevisionBreaksATie(self):
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "NEW",
            self._winner(
                ("OLD", document(oid, revisions=["199001010000Z"]), 0, 0),
                ("NEW", document(oid, revisions=["202401010000Z"]), 0, 0),
            ),
        )

    def testTheLaterRfcBreaksARevisionlessTie(self):
        # RFC1065-SMI, RFC1155-SMI and SNMPv2-SMI define the SMI root arcs
        # identically and none of them carries a MODULE-IDENTITY at all, so
        # without this term the winner is whichever name sorts first
        # alphabetically -- which is how RFC1065-SMI came to own ten arcs
        # that RFC 2578 defines. Supersession cannot decide it either: RFC
        # 1155 is STD 16 and still an Internet Standard. Publication order
        # can, and the RFC number is exactly that.
        oid = "1.3.6.1"

        self.assertEqual(
            "SNMPv2-SMI",
            rank_index(
                [
                    ("SNMPv2-SMI", document(oid), 0, 2578),
                    ("RFC1065-SMI", document(oid), 0, 1065),
                ]
            )[oid],
        )

    def testAModuleNoRfcPublishesRanksBelowOneThatIs(self):
        oid = "1.3.6.1"

        self.assertEqual(
            "SNMPv2-SMI",
            rank_index(
                [
                    ("A-VENDOR-SMI", document(oid), 0, 0),
                    ("SNMPv2-SMI", document(oid), 0, 2578),
                ]
            )[oid],
        )

    def testTheModuleNameMakesTheRuleTotal(self):
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "AAA",
            self._winner(("ZZZ", document(oid), 0, 0), ("AAA", document(oid), 0, 0)),
        )

    def testTheResultDoesNotDependOnInputOrder(self):
        oid = "1.3.6.1.4.1.99"
        modules = [
            ("VENDOR", document(oid, revisions=["202401010000Z"]), 2, 0),
            ("STANDARD", document(oid), 0, 0),
            ("DRAFT", document(oid), 1, 0),
        ]

        forwards = rank_index(modules)
        backwards = rank_index(list(reversed(modules)))

        self.assertEqual(forwards, backwards)
        self.assertEqual("STANDARD", forwards[oid])


class AnchorTestCase(unittest.TestCase):
    """What a module claims, and how strongly."""

    def testAnchorsAreWhatIsIndexed(self):
        doc = document("1.3.6.1.4.1.99", objects=[("a", "current")])

        self.assertEqual([("1.3.6.1.4.1.99", 0)], oids_of(doc))

    def testAModuleWithNoAnchorFallsBackToItsDefinitions(self):
        doc = {"a": {"class": "objecttype", "oid": "1.3.6.1.4.1.99.1"}}

        self.assertEqual([("1.3.6.1.4.1.99.1", 2)], oids_of(doc))

    def testAnAnchorOutranksAFallback(self):
        oid = "1.3.6.1.4.1.99"

        self.assertEqual(
            "ANCHORED",
            rank_index(
                [
                    ("BARE", {"a": {"class": "objecttype", "oid": oid}}, 0, 0),
                    ("ANCHORED", document(oid), 0, 0),
                ]
            )[oid],
        )


class AnchorIndexTestCase(unittest.TestCase):
    """The arcs modules register at, which is the OID index less its objects.

    rank_index answers for every OID any module defines. Handing that to the
    arc index made it the object tree: 98,903 arcs and an 11 MB artifact over
    pysnmp/mibs, 98% of it objects. See pysnmp/pysmi#301.
    """

    RANKED = {
        "1.3.6.1.2.1.2": "IF-MIB",
        "1.3.6.1.2.1.2.1": "IF-MIB",
        "1.3.6.1.2.1.2.2.1.8": "IF-MIB",
        "1.3.6.1.2.1.31": "IF-MIB",
        "1.3.6.1.2.1.31.1.1.1.1": "IF-MIB",
        "1.3.6.1.2.1.1": "SNMPv2-MIB",
        "1.3.6.1.2.1.1.1": "SNMPv2-MIB",
    }

    def testAnArcUnderTheSameModuleIsNotAnAnchor(self):
        found = anchor_index(self.RANKED)

        self.assertNotIn("1.3.6.1.2.1.2.1", found)
        self.assertNotIn("1.3.6.1.2.1.2.2.1.8", found)

    def testWhereAModulesSubtreeBeginsIsAnAnchor(self):
        found = anchor_index(self.RANKED)

        self.assertEqual("IF-MIB", found["1.3.6.1.2.1.2"])
        self.assertEqual("SNMPv2-MIB", found["1.3.6.1.2.1.1"])

    def testAModuleHasAsManyAnchorsAsDisjointRegistrations(self):
        """Taking one arc per module instead would be a smaller set and a
        broken one: IF-MIB's MODULE-IDENTITY is at 1.3.6.1.2.1.31 and its
        objects hang off 1.3.6.1.2.1.2."""
        found = anchor_index(self.RANKED)

        self.assertEqual(
            ["1.3.6.1.2.1.2", "1.3.6.1.2.1.31"],
            sorted(x for x, module in found.items() if module == "IF-MIB"),
        )

    def testAnArcUnderAnotherModuleIsStillAnAnchor(self):
        """mib-2 belongs to SNMPv2-SMI and everything hangs off it. An arc is
        a registration against its own module, not against the tree."""
        ranked = {**self.RANKED, "1.3.6.1.2.1": "SNMPv2-SMI"}

        found = anchor_index(ranked)

        self.assertIn("1.3.6.1.2.1.2", found)
        self.assertIn("1.3.6.1.2.1", found)

    def testTheValuesAreUnchanged(self):
        found = anchor_index(self.RANKED)

        for oid, module in found.items():
            with self.subTest(oid=oid):
                self.assertEqual(self.RANKED[oid], module)

    def testItIsASubsetOfWhatItWasGiven(self):
        found = anchor_index(self.RANKED)

        self.assertLessEqual(set(found), set(self.RANKED))
        self.assertLess(len(found), len(self.RANKED))

    def testEveryIndexedOidIsUnderSomeAnchor(self):
        """Which is what makes a longest-prefix walk over the anchors answer
        for any OID the corpus indexes -- the lookup pages.resolve does."""
        found = anchor_index(self.RANKED)

        for oid in self.RANKED:
            with self.subTest(oid=oid):
                self.assertTrue(
                    any(x in found for x in prefixes(oid)),
                    f"{oid} is under no anchor",
                )

    def testAnEmptyIndexHasNoAnchors(self):
        self.assertEqual({}, anchor_index({}))

    def testItIsIdempotent(self):
        found = anchor_index(self.RANKED)

        self.assertEqual(found, anchor_index(found))


class RenderTestCase(unittest.TestCase):
    """The published shape: MODULE,OID, ordered by OID numerically."""

    def testArcsSortNumericallyNotLexically(self):
        self.assertLess(arcs("1.3.6.1.2"), arcs("1.3.6.1.10"))

    def testAnOidComesAfterEveryPrefixOfIt(self):
        self.assertLess(arcs("1.3.6"), arcs("1.3.6.1"))

    def testRowsAreModuleThenOid(self):
        self.assertEqual("A-MIB,1.3.6\n", render_index({"1.3.6": "A-MIB"}))

    def testOutputIsOrderedByOid(self):
        text = render_index({"1.3.6.1.10": "TEN", "1.3.6.1.2": "TWO", "1.3.6.1": "ONE"})

        self.assertEqual("ONE,1.3.6.1\nTWO,1.3.6.1.2\nTEN,1.3.6.1.10\n", text)

    def testRoundTrip(self):
        index = {"1.3.6.1": "A-MIB", "1.3.6.2": "B-MIB"}

        self.assertEqual(
            index, {oid: module for module, oid in read_index(render_index(index))}
        )

    def testAMalformedRowCostsOnlyItself(self):
        self.assertEqual(
            [("A-MIB", "1.3.6")], list(read_index("A-MIB,1.3.6\nnonsense\n"))
        )


class FrozenTestCase(unittest.TestCase):
    """The legacy index replays a snapshot rather than being regenerated."""

    def testAFrozenAnswerSurvivesACorrection(self):
        # index-frozen.csv carries RAPID-CITY for 1.3.6.1.6.3.1 on purpose:
        # consumers keying on the module an OID resolves to keep the answer
        # they already have, and the correction lands in the ranked index.
        merged, dropped, added = merge_frozen(
            [("RAPID-CITY", "1.3.6.1.6.3.1")],
            {"1.3.6.1.6.3.1": "SNMPv2-MIB"},
            ["RAPID-CITY", "SNMPv2-MIB"],
        )

        self.assertEqual("RAPID-CITY", merged["1.3.6.1.6.3.1"])
        self.assertEqual((0, 0), (dropped, added))

    def testARowNamingAnUncompiledModuleIsDropped(self):
        merged, dropped, added = merge_frozen(
            [("GONE-MIB", "1.3.6.1.4.1.1")], {}, ["STILL-HERE-MIB"]
        )

        self.assertEqual({}, merged)
        self.assertEqual((1, 0), (dropped, added))

    def testAnOidTheSnapshotNeverCarriedIsAdded(self):
        # Without this a module added to the corpus would never reach the
        # legacy index, and a consumer that has not moved to the ranked one
        # would keep resolving nothing for it.
        merged, dropped, added = merge_frozen(
            [], {"1.3.6.1.4.1.2": "NEW-MIB"}, ["NEW-MIB"]
        )

        self.assertEqual({"1.3.6.1.4.1.2": "NEW-MIB"}, merged)
        self.assertEqual((0, 1), (dropped, added))
