#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The precedence vectors, checked against the implementations they constrain.

pysnmp runs :py:data:`~pysmi.corpus.precedence.VECTORS` against its own three
copies of the rule. These tests check this side: that pysmi answers the same
vectors, so a failure over there is a drift in pysnmp rather than a vector
that was never right here.
"""

import json
import os
import tempfile
import unittest

from pysmi.compiler import (
    PRECEDENCE_EQUAL_REVISIONS,
    PRECEDENCE_NEWEST_REVISION,
    PRECEDENCE_NO_REVISION,
    rank_by_revision,
)
from pysmi.corpus.index import rank_index
from pysmi.corpus.precedence import (
    CONTESTED,
    VECTORS,
    run_vectors,
    vectors_as_json,
    write_vectors,
)


class PrecedenceVectorsTestCase(unittest.TestCase):
    """pysmi answers the vectors it publishes."""

    def testEveryVectorPasses(self):
        self.assertEqual(run_vectors(), [])

    def testVectorIdsAreUnique(self):
        identifiers = [x["id"] for x in VECTORS]

        self.assertEqual(len(identifiers), len(set(identifiers)))

    def testEveryVectorSaysWhy(self):
        # A vector that fails has to say what broke without its reader's
        # author reconstructing the intent from a rank tuple.
        for vector in VECTORS:
            self.assertTrue(vector.get("why"), vector["id"])

    def testVectorsRenderAsJson(self):
        # The contract is data, so an implementation that is not written in
        # Python can run the same vectors.
        self.assertEqual(
            [x["id"] for x in json.loads(vectors_as_json())],
            [x["id"] for x in VECTORS],
        )

    def testWriteVectorsLandsTheFile(self):
        path = write_vectors(os.path.join(tempfile.mkdtemp(), "out"))

        with open(path, encoding="utf-8") as fileObj:
            written = json.load(fileObj)

        self.assertEqual([x["id"] for x in written], [x["id"] for x in VECTORS])

    def testVectorsCoverEveryOperation(self):
        # An operation with no vector is a part of the rule nothing checks,
        # which is how the second implementation drifts unnoticed.
        self.assertEqual(
            {x["op"] for x in VECTORS},
            {"normalise_revision", "module_precedence", "oid_precedence"},
        )

    def testEveryPrecedenceRuleIsExercised(self):
        # All three PRECEDENCE_* constants reach MibStatus.precedence and get
        # logged, so all three have to be pinned.
        self.assertEqual(
            {x["expect"]["rule"] for x in VECTORS if x["op"] == "module_precedence"},
            {
                "",
                PRECEDENCE_NO_REVISION,
                PRECEDENCE_EQUAL_REVISIONS,
                PRECEDENCE_NEWEST_REVISION,
            },
        )

    def testEveryOidCandidateContendsForTheArc(self):
        # A candidate that does not define CONTESTED wins or loses by not
        # being there, which makes the vector pass whatever the rule does.
        # oids_of reads a module off its anchors alone when it has any, so
        # this is easy to get wrong while writing a fixture that looks right.
        for vector in VECTORS:
            if vector["op"] != "oid_precedence":
                continue

            for module in vector["modules"]:
                self.assertEqual(
                    rank_index([(module["module"], module["document"], 0, 0)]).get(
                        CONTESTED
                    ),
                    module["module"],
                    f"{vector['id']}: {module['module']} does not define {CONTESTED}",
                )

    def testOidRankingIgnoresTheOrderItIsGivenIn(self):
        # The rule is what makes a corpus rebuild reproducible, so it cannot
        # depend on the order the corpus happened to walk its modules in.
        for vector in VECTORS:
            if vector["op"] != "oid_precedence":
                continue

            modules = [
                (x["module"], x["document"], x["tier"], x["rfc"])
                for x in vector["modules"]
            ]

            self.assertEqual(
                rank_index(reversed(modules)).get(CONTESTED),
                vector["expect"],
                vector["id"],
            )


class RankByRevisionTestCase(unittest.TestCase):
    """The rule the vectors are published for, at its edges."""

    def testNoCandidatesIsNotAContest(self):
        self.assertEqual(rank_by_revision([]), ([], ""))

    def testUndatedAmongDatedDisablesTheComparison(self):
        # The case that has to be a rule rather than a fallthrough: the dated
        # candidate is not simply better than the undated one, because an
        # undated module may well be the newer of the two.
        order, rule = rank_by_revision(["202406010000Z", None, "202001010000Z"])

        self.assertEqual(order, [0, 1, 2])
        self.assertEqual(rule, PRECEDENCE_NO_REVISION)

    def testOrderIsAPermutationOfTheInput(self):
        # Every candidate is reported, winner and losers alike -- the losers
        # are what MibStatus.shadowed names.
        revisions = ["202001010000Z", "202406010000Z", "201501010000Z"]
        order, _ = rank_by_revision(revisions)

        self.assertEqual(sorted(order), list(range(len(revisions))))


class VectorsConstrainThisSideTestCase(unittest.TestCase):
    """A vector that cannot fail here constrains only the other project."""

    def testABrokenRuleFailsTheVectors(self):
        # Ranking undated candidates as though they were the oldest, rather
        # than declining to rank at all, is the plausible way to reimplement
        # this. It has to be caught.
        import pysmi.corpus.precedence as module

        original = module.rank_by_revision

        def oldest_first(revisions):
            order = sorted(
                range(len(revisions)),
                key=lambda i: revisions[i] or "",
                reverse=True,
            )

            return order, PRECEDENCE_NEWEST_REVISION

        try:
            module.rank_by_revision = oldest_first
            failures = run_vectors()

        finally:
            module.rank_by_revision = original

        self.assertIn("module-one-undated-candidate-disables-the-comparison", failures)
        self.assertEqual(run_vectors(), [])


if __name__ == "__main__":
    unittest.main()
