#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""ExtUTCTime comes in two lengths and MIBs get both of them wrong.

RFC 2578 section 2 gives YYMMDDHHMMZ for 1900-1999 and YYYYMMDDHHMMZ for any
year. A REVISION is normalised to a readable date; LAST-UPDATED is passed
through as written. A date pysmi cannot read becomes the epoch rather than an
error, because rejecting it would break real MIBs.

See pysnmp/pysmi#94.
"""

import logging
import sys
import unittest

from tests.harness import render

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    LAST-UPDATED "%s"
    ORGANIZATION "Test"
    CONTACT-INFO "test@example.com"
    DESCRIPTION  "The module under test."
%s
    ::= { 1 3 1 }

END
"""

REVISION = """    REVISION     "%s"
    DESCRIPTION  "%s"
"""


def module(lastUpdated="202401011200Z", revisions=()):
    """Render a MODULE-IDENTITY carrying the given dates."""
    body = "".join(REVISION % r for r in revisions)
    doc, ctx = render(MIB % (lastUpdated, body), deps=())
    return doc["testModule"], ctx["testModule"]


class RevisionDateTestCase(unittest.TestCase):
    """A REVISION is normalised; both ExtUTCTime lengths are understood."""

    def testThirteenCharacterForm(self):
        doc, ctx = module(revisions=[("202401011200Z", "recent")])
        self.assertEqual(doc["revisions"], [{"revision": "2024-01-01 12:00", "description": "recent"}])
        self.assertEqual(ctx.getRevisions(), ("2024-01-01 12:00",))

    def testElevenCharacterFormExpandsToTheNineteenHundreds(self):
        doc, _ = module(revisions=[("9902012359Z", "old")])
        self.assertEqual(doc["revisions"][0]["revision"], "1999-02-01 23:59")

    def testEveryRevisionIsKeptInSourceOrder(self):
        doc, ctx = module(revisions=[("202401011200Z", "third"), ("200001010000Z", "second"), ("9901010000Z", "first")])
        self.assertEqual(
            [r["revision"] for r in doc["revisions"]],
            ["2024-01-01 12:00", "2000-01-01 00:00", "1999-01-01 00:00"],
        )
        self.assertEqual(len(ctx.getRevisions()), 3)

    def testDescriptionTravelsWithItsRevision(self):
        doc, _ = module(revisions=[("202401011200Z", "newer"), ("200001010000Z", "older")])
        self.assertEqual([r["description"] for r in doc["revisions"]], ["newer", "older"])


class MalformedDateTestCase(unittest.TestCase):
    """An unreadable REVISION becomes the epoch. Pinned, not endorsed."""

    def testWrongLengthBecomesTheEpoch(self):
        doc, _ = module(revisions=[("20230101120000Z", "fifteen characters")])
        self.assertEqual(doc["revisions"][0]["revision"], "1970-01-01 00:00")

    def testImpossibleDateBecomesTheEpoch(self):
        doc, _ = module(revisions=[("202302301200Z", "february the thirtieth")])
        self.assertEqual(doc["revisions"][0]["revision"], "1970-01-01 00:00")

    def testTheDescriptionStillSurvives(self):
        doc, _ = module(revisions=[("nonsense", "kept anyway")])
        self.assertEqual(doc["revisions"][0]["description"], "kept anyway")


class LastUpdatedTestCase(unittest.TestCase):
    """LAST-UPDATED is rendered the same way REVISION is.

    RFC 2578 section 2 gives both clauses the same type, so both are read the
    same way and written in one format. See pysnmp/pysmi#117.
    """

    def testThirteenCharacterFormIsReformatted(self):
        doc, ctx = module(lastUpdated="202401011200Z")
        self.assertEqual(doc["lastupdated"], "2024-01-01 12:00")
        self.assertEqual(ctx.getLastUpdated(), "2024-01-01 12:00")

    def testElevenCharacterFormExpandsToTheNineteenHundreds(self):
        doc, _ = module(lastUpdated="9912312359Z")
        self.assertEqual(doc["lastupdated"], "1999-12-31 23:59")

    def testAnUnreadableDateBecomesTheEpoch(self):
        doc, _ = module(lastUpdated="nonsense")
        self.assertEqual(doc["lastupdated"], "1970-01-01 00:00")

    def testItAgreesWithARevisionCarryingTheSameValue(self):
        doc, _ = module(lastUpdated="202401011200Z", revisions=[("202401011200Z", "same instant")])
        self.assertEqual(doc["lastupdated"], doc["revisions"][0]["revision"])


class MalformedDateIsReportedTestCase(unittest.TestCase):
    """An epoch substitution is logged, so it is not silent. See #114."""

    def testTheSubstitutionIsLogged(self):
        with self.assertLogs("pysmi.codegen", level="WARNING") as caught:
            module(revisions=[("202302301200Z", "february the thirtieth")])

        self.assertTrue(any("202302301200Z" in line for line in caught.output), caught.output)

    def testLastUpdatedIsReportedToo(self):
        with self.assertLogs("pysmi.codegen", level="WARNING") as caught:
            module(lastUpdated="nonsense")

        self.assertTrue(any("nonsense" in line for line in caught.output), caught.output)

    def testAReadableDateSaysNothing(self):
        logger = logging.getLogger("pysmi.codegen")
        with self.assertLogs(logger, level="WARNING") as caught:
            logger.warning("nothing to report")
            module(lastUpdated="202401011200Z", revisions=[("202401011200Z", "fine")])

        self.assertEqual(caught.output, ["WARNING:pysmi.codegen:nothing to report"])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
