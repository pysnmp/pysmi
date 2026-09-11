#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""A long list page splits into buckets named for the range they cover.

Two properties matter more than any particular label. A key has to round-trip,
because the generator writes it and the browser parses it back. And a key has
to stay put under corpus growth, because #284 makes crawlability a requirement
and a numbered page renumbers everything after an insertion.

See pysnmp/pysmi#287.
"""

import itertools
import unittest

from pysmi.corpus.buckets import (
    MINIMUM,
    SEPARATOR,
    Bucket,
    abbreviate,
    buckets,
    counts,
    locate,
    parse_key,
    retired,
    successors,
)

#: Cisco-shaped: nearly every name shares a prefix, which is what defeats a
#: fixed prefix length and what the derived label handles.
CISCO = [
    "ATM-RMON-MIB",
    "CISCO-AAA-CLIENT-MIB",
    "CISCO-AAA-SERVER-MIB",
    "CISCO-ATM-IF-MIB",
    "CISCO-ATM-PVCTRAP-EXTN-MIB",
    "CISCO-BGP4-MIB",
    "CISCO-BULK-FILE-MIB",
    "CISCO-CDP-MIB",
    "CISCO-ENTITY-ALARM-MIB",
    "CISCO-ENTITY-FRU-CONTROL-MIB",
    "RPHY-NDF-NDR-MIB",
]


def numeric(text):
    """The ordering an OID node's children take, where 10 follows 9."""
    return int(text)


class PartitionTestCase(unittest.TestCase):
    """Equal-count runs, every entry in exactly one."""

    def testEveryEntryIsInExactlyOneBucket(self):
        found = buckets(CISCO, 3)
        held = [x for bucket in found for x in bucket.entries]

        self.assertEqual(sorted(CISCO), held)

    def testNoBucketIsLargerThanThePageSize(self):
        for bucket in buckets(CISCO, 3):
            with self.subTest(key=bucket.key):
                self.assertLessEqual(len(bucket.entries), 3)

    def testTheLastBucketTakesTheRemainder(self):
        found = buckets(CISCO, 3)

        self.assertEqual(4, len(found))
        self.assertEqual(2, len(found[-1].entries))

    def testAShortListIsOneUnkeyedBucket(self):
        """Single-bucket lists emit no key strip and keep the unbucketed URL,
        so the generator has to be able to tell one from a bucketed list."""
        found = buckets(CISCO, 50)

        self.assertEqual(1, len(found))
        self.assertEqual("", found[0].key)
        self.assertEqual(tuple(sorted(CISCO)), found[0].entries)

    def testAListExactlyThePageSizeIsNotBucketed(self):
        found = buckets(CISCO, len(CISCO))

        self.assertEqual(1, len(found))
        self.assertEqual("", found[0].key)

    def testAnEmptyListHasNoBuckets(self):
        self.assertEqual((), buckets([], 10))

    def testItSortsRatherThanTrustingTheCaller(self):
        """The labels are computed from the order, so an unsorted input that
        was taken as sorted would put entries in buckets that exclude them."""
        self.assertEqual(buckets(CISCO, 3), buckets(reversed(CISCO), 3))

    def testADuplicateEntryIsHeldOnce(self):
        """Two runs sharing a boundary value would give two buckets one key."""
        found = buckets([*CISCO, "CISCO-CDP-MIB"], 3)
        held = [x for bucket in found for x in bucket.entries]

        self.assertEqual(sorted(CISCO), held)

    def testAPageSizeOfZeroIsRefused(self):
        with self.assertRaises(ValueError):
            buckets(CISCO, 0)


class LabelTestCase(unittest.TestCase):
    """The label length falls out of the local density."""

    def testALabelDistinguishesItFromTheNeighbouringRun(self):
        """The whole point: a dense region gets a long label, because a short
        one would not say which of the two buckets a name is in."""
        keys = [x.key for x in buckets(CISCO, 2)]

        self.assertIn("AT..CISCO-AAA-C", keys)
        self.assertIn("CISCO-AAA-S..CISCO-ATM-I", keys)

    def testTheHighEndNeverSortsBelowTheLow(self):
        """A run whose two ends are far apart, next to a neighbour further
        still, took its high label from the neighbour alone and got
        `CISCO-E..CI` -- a range that sorts backwards and says nothing."""
        for size in (2, 3, 4, 5):
            for bucket in buckets(CISCO, size):
                with self.subTest(size=size, key=bucket.key):
                    self.assertLessEqual(bucket.low, bucket.high)

    def testALabelSaysWhereItsOwnRunEnds(self):
        found = buckets(CISCO, 2)

        self.assertIn("CISCO-E..CISCO-ENTITY-F", [x.key for x in found])

    def testASparseRegionGetsTheMinimum(self):
        found = buckets(CISCO, 3)

        self.assertEqual(MINIMUM, len(found[0].low))
        self.assertEqual("AT", found[0].low)

    def testTheOuterEdgesHaveNothingToDistinguishFrom(self):
        """First low and last high, where the minimum decides the length."""
        found = buckets(CISCO, 3)

        self.assertEqual("AT", found[0].low)
        self.assertEqual("RP", found[-1].high)

    def testEveryLabelIsAPrefixOfTheEntryItNames(self):
        for bucket in buckets(CISCO, 2):
            with self.subTest(key=bucket.key):
                self.assertTrue(bucket.entries[0].startswith(bucket.low))
                self.assertTrue(bucket.entries[-1].startswith(bucket.high))

    def testTheKeysAreStrictlyIncreasing(self):
        """Which is what makes locate's longest-prefix scan correct, and what
        keeps two buckets from claiming one URL."""
        lows = [x.low for x in buckets(CISCO, 2)]

        self.assertEqual(sorted(lows), lows)
        self.assertEqual(len(set(lows)), len(lows))

    def testABucketsHighEndSortsBelowTheNextBucketsLow(self):
        found = buckets(CISCO, 2)

        for before, after in itertools.pairwise(found):
            with self.subTest(key=before.key):
                self.assertLess(before.high, after.low)

    def testTheSortIsCaseSensitiveByteOrder(self):
        """Module names are mixed case, and a display sort that differed from
        the sort the labels imply would put entries outside their range."""
        mixed = ["A3Com-MIB", "A10-MIB", "aCC-MIB", "ZYXEL-MIB"]

        self.assertEqual(
            ("A10-MIB", "A3Com-MIB", "ZYXEL-MIB", "aCC-MIB"),
            buckets(mixed, 10)[0].entries,
        )


class KeyTestCase(unittest.TestCase):
    """The separator, and reading a key back."""

    def testTheSeparatorIsAscii(self):
        """An en dash percent-encodes to %E2%80%93 in a URL, which works and
        is a needless hazard in a string that crawlers, server logs, shell
        history, spreadsheets and copy-paste all handle."""
        self.assertEqual("..", SEPARATOR)
        self.assertTrue(SEPARATOR.isascii())

    def testEveryKeyRoundTrips(self):
        """The generator writes these and the browser parses them back. Worth
        a test rather than a convention."""
        for bucket in buckets(CISCO, 2):
            with self.subTest(key=bucket.key):
                self.assertEqual((bucket.low, bucket.high), parse_key(bucket.key))

    def testAKeyIsUrlSafeUnescaped(self):
        for bucket in buckets(CISCO, 2):
            with self.subTest(key=bucket.key):
                self.assertTrue(
                    all(x.isalnum() or x in "-._~" for x in bucket.key),
                    f"{bucket.key} needs escaping",
                )

    def testAnUnbucketedListHasNoKeyToParse(self):
        self.assertIsNone(parse_key(""))

    def testSomethingThatIsNotAKeyIsRefused(self):
        for text in ("CISCO-MIB", "..", "..CISCO", "CISCO.."):
            with self.subTest(text=text):
                self.assertIsNone(parse_key(text))

    def testASeparatorCannotOccurInAModuleName(self):
        """RFC 2578 names are letters, digits and hyphens, so the split is
        unambiguous and a plain hyphen would not have been."""
        for name in CISCO:
            with self.subTest(name=name):
                self.assertNotIn(SEPARATOR, name)


class LocateTestCase(unittest.TestCase):
    """Which bucket an entry is in."""

    def setUp(self):
        self.found = buckets(CISCO, 3)

    def testAnEntryLandsInTheBucketThatHoldsIt(self):
        for bucket in self.found:
            for entry in bucket.entries:
                with self.subTest(entry=entry):
                    self.assertEqual(bucket, locate(entry, self.found))

    def testAnEntryTheListNeverHadStillResolves(self):
        """A browser resolving a name typed at it, or one added since the
        buckets were built, needs an answer rather than a miss."""
        placed = locate("CISCO-BGP4-V2-MIB", self.found)

        self.assertIsNotNone(placed)
        self.assertLessEqual(placed.low, "CISCO-BGP4-V2-MIB")

    def testANameBelowEveryBucketHasNoAnswer(self):
        """Distinguishable from the first bucket, which would otherwise be a
        silent wrong answer."""
        self.assertIsNone(locate("AAA-MIB", self.found))

    def testANameAboveEveryBucketLandsInTheLast(self):
        self.assertEqual(self.found[-1], locate("ZZZ-MIB", self.found))

    def testAnUnbucketedListAnswersForEverything(self):
        found = buckets(CISCO, 50)

        self.assertEqual(found[0], locate("ZZZ-MIB", found))


class SuccessorTestCase(unittest.TestCase):
    """A bucket that outgrows the page size splits, which renames a key.

    The one case where a range URL moves. Static hosting serves no redirects,
    so the generator emits the retired key as a page carrying a canonical link
    and a meta refresh to whatever now covers it.
    """

    def testASplitBucketNamesBothHalves(self):
        before = buckets(CISCO, 6)
        after = buckets(CISCO, 3)

        heirs = successors(before[0].key, after)

        self.assertEqual(2, len(heirs))
        self.assertEqual(after[:2], heirs)

    def testTheSuccessorsCoverWhatTheKeyCovered(self):
        before = buckets(CISCO, 6)
        after = buckets(CISCO, 3)

        for bucket in before:
            with self.subTest(key=bucket.key):
                held = [
                    x for heir in successors(bucket.key, after) for x in heir.entries
                ]

                self.assertTrue(set(bucket.entries) <= set(held))

    def testAKeyThatStillExistsIsItsOwnSuccessor(self):
        found = buckets(CISCO, 3)

        self.assertEqual((found[1],), successors(found[1].key, found))

    def testAListThatStoppedBeingBucketedFoldsIntoTheOneBucket(self):
        """The corpus shrank, or the page size grew. The old keys still get
        crawled and still have to answer something."""
        before = buckets(CISCO, 3)
        after = buckets(CISCO, 50)

        for bucket in before:
            with self.subTest(key=bucket.key):
                self.assertEqual((after[0],), successors(bucket.key, after))

    def testSomethingThatIsNotAKeyHasNoSuccessors(self):
        self.assertEqual((), successors("CISCO-MIB", buckets(CISCO, 3)))

    def testRetiredNamesOnlyTheKeysThatWent(self):
        before = buckets(CISCO, 6)
        after = buckets(CISCO, 3)

        gone = retired([x.key for x in before], after)
        current = {x.key for x in after}

        self.assertNotEqual({}, gone)

        for key in gone:
            with self.subTest(key=key):
                self.assertNotIn(key, current)

    def testAKeyThatSurvivedIsNotRetired(self):
        found = buckets(CISCO, 3)

        self.assertEqual({}, retired([x.key for x in found], found))

    def testARetiredKeyWithNoSuccessorIsStillReported(self):
        """Empty rather than absent: the URL is crawled, so the generator has
        to decide what it serves. This is a key from below the whole list --
        everything it covered is gone."""
        gone = retired(["AA..AB"], buckets(CISCO, 3))

        self.assertEqual({"AA..AB": ()}, gone)

    def testAKeyFromAboveTheListFallsToTheLastBucket(self):
        """Not empty: the same answer locate gives for a name above every
        bucket, so the stub page refreshes somewhere real."""
        found = buckets(CISCO, 3)

        self.assertEqual({"ZZ..ZZZ": (found[-1].key,)}, retired(["ZZ..ZZZ"], found))


class NumericTestCase(unittest.TestCase):
    """A wide OID node takes the same mechanism keyed on arc number.

    In pysnmp/mibs' corpus ``1.3.6.1.4.1`` is the only wide one, at 356
    registrants. Numbers sort numerically, and the shortest distinguishing
    prefix of a decimal number is not a number, so labels are whole.
    """

    ARCS = ["9", "11", "171", "2011", "311", "43", "4491", "52"]

    def found(self, size=3):
        return buckets(self.ARCS, size, order=numeric)

    def testTheyAreInNumericOrder(self):
        held = [x for bucket in self.found() for x in bucket.entries]

        self.assertEqual(["9", "11", "43", "52", "171", "311", "2011", "4491"], held)

    def testTheLabelsAreWholeNumbers(self):
        """Not "1" for 171 and "1" for 11, which is what a shortest prefix
        would give and which is not a number."""
        for bucket in self.found():
            with self.subTest(key=bucket.key):
                self.assertIn(bucket.low, self.ARCS)
                self.assertIn(bucket.high, self.ARCS)

    def testTheKeyReadsAsTheRangeItIs(self):
        self.assertEqual("9..43", self.found()[0].key)

    def testItRoundTrips(self):
        for bucket in self.found():
            with self.subTest(key=bucket.key):
                self.assertEqual((bucket.low, bucket.high), parse_key(bucket.key))

    def testLocateUsesTheSameOrdering(self):
        """Byte order would put 10 before 9 and answer with the wrong page."""
        found = self.found()

        for bucket in found:
            for entry in bucket.entries:
                with self.subTest(entry=entry):
                    self.assertEqual(bucket, locate(entry, found, numeric))

    def testAnArcTheCorpusGainsResolves(self):
        found = self.found()
        placed = locate("300", found, numeric)

        self.assertIsNotNone(placed)
        self.assertLessEqual(int(placed.low), 300)

    def testSuccessorsUseTheSameOrdering(self):
        before = buckets(self.ARCS, 4, order=numeric)
        after = buckets(self.ARCS, 2, order=numeric)

        for bucket in before:
            with self.subTest(key=bucket.key):
                held = [
                    x
                    for heir in successors(bucket.key, after, numeric)
                    for x in heir.entries
                ]

                self.assertTrue(set(bucket.entries) <= set(held))

    def testShorteningCanStillBeAskedForExplicitly(self):
        found = buckets(["aa", "ab", "ba", "bb"], 2, order=None, shorten=True)

        self.assertEqual("aa..ab", found[0].key)
        self.assertEqual("ba..bb", found[1].key)


class RenderingTestCase(unittest.TestCase):
    """The key strip lists every bucket on every bucket page."""

    def testAShortKeyIsRenderedWhole(self):
        self.assertEqual("AT..CI", abbreviate(Bucket("AT..CI", "AT", "CI", ())))

    def testALongLabelIsClipped(self):
        bucket = Bucket(
            "CISCO-LICENSE-MI..CISCO-PRI", "CISCO-LICENSE-MI", "CISCO-PRI", ()
        )

        rendered = abbreviate(bucket, 12)

        self.assertEqual("CISCO-LICEN…..CISCO-PRI", rendered)

    def testTheUrlKeepsTheWholeLabel(self):
        """Only the rendering is clipped. A clipped URL would not resolve."""
        bucket = Bucket(
            "CISCO-LICENSE-MI..CISCO-PRI", "CISCO-LICENSE-MI", "CISCO-PRI", ()
        )

        self.assertNotEqual(abbreviate(bucket, 12), bucket.key)
        self.assertEqual(("CISCO-LICENSE-MI", "CISCO-PRI"), parse_key(bucket.key))

    def testAnUnbucketedListRendersNoKey(self):
        self.assertEqual("", abbreviate(buckets(CISCO, 50)[0]))


class CountTestCase(unittest.TestCase):
    """What a build report carries."""

    def testTheTallyDescribesTheSplit(self):
        tally = counts(buckets(CISCO, 3))

        self.assertEqual(4, tally["buckets"])
        self.assertEqual(len(CISCO), tally["entries"])
        self.assertEqual(3, tally["largest"])
        self.assertEqual(2, tally["smallest"])

    def testAnEmptyListTalliesZero(self):
        self.assertEqual(
            {"buckets": 0, "entries": 0, "largest": 0, "smallest": 0},
            counts(buckets([], 10)),
        )
