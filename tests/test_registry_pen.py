#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The IANA Private Enterprise Numbers registry, read and reduced.

A corpus knows that a module registers under ``1.3.6.1.4.1.9``. It does not
know that ``1.3.6.1.4.1.9`` is Cisco -- nothing in the MIB text says so, and
the directory a file sits in is a filing convention. The registration is a
published fact, and this is what reads it.

Two properties matter more than the parsing. It is **taken as an input**, never
fetched and never bundled, so a build stays reproducible with the network
unplugged. And what the reducer keeps is **the caller's decision**: a downstream
repository commits the snapshot, so which fields leave IANA's copy is that
repository's to choose rather than this module's to assume.

Nothing is normalised either way. An email comes out as ``davej&cisco.com``
because that is what the registry says, and the output is a rendering of IANA's
record rather than a corrected version of it. pysnmp/pysmi#281.
"""

import contextlib
import io
import os
import shutil
import tempfile
import textwrap
import unittest

from pysmi.registry import __main__ as cli
from pysmi.registry.pen import (
    AUTHORITY,
    ENTERPRISES,
    FIELDS,
    Registrant,
    authority_url,
    load_registry,
    parse_registry,
    reduce_registry,
)

#: The published shape: a prose preamble, the legend, then four-line records.
PUBLISHED = textwrap.dedent("""\


    PRIVATE ENTERPRISE NUMBERS

    (last updated 2026-09-10)

    SMI Network Management Private Enterprise Codes:

    Prefix: iso.org.dod.internet.private.enterprise (1.3.6.1.4.1)

    Decimal
    | Organization
    | | Contact
    | | | Email
    | | | |
    0
      Reserved
        Internet Assigned Numbers Authority
          iana&iana.org
    9
      Cisco Systems, Inc.
        A Person
          person&cisco.com
    3076
      Altiga Networks, Inc.
        Another Person
          other&altiga.com
    42
      ---none---
        Nobody
          nobody&example.com
    """)


class ParseTestCase(unittest.TestCase):
    """Reading the registry as IANA publishes it."""

    def setUp(self):
        self.found = list(parse_registry(PUBLISHED))

    def testEveryRecordIsRead(self):
        self.assertEqual([0, 9, 3076, 42], [x.number for x in self.found])

    def testTheOrganizationIsRead(self):
        self.assertEqual("Cisco Systems, Inc.", self.found[1].organization)

    def testTheContactIsRead(self):
        """The registrant page is an accountability aid, not only navigation."""
        self.assertEqual("A Person", self.found[1].contact)

    def testTheEmailIsReadAsTheRegistryWritesIt(self):
        """IANA writes & rather than @. That is reproduced, not corrected.

        The output is a rendering of IANA's record, and a corpus site is not a
        system of record for MIB ownership.
        """
        self.assertEqual("person&cisco.com", self.found[1].email)

    def testARecordThatStopsShortIsReadAsFarAsItRuns(self):
        """The number and the organization are the load-bearing part."""
        found = list(parse_registry("1\n  Acme\n"))

        self.assertEqual([Registrant(1, "Acme", "", "")], found)

    def testARegistrationCarriesItsAuthority(self):
        """A correction to a registration belongs at IANA, so say where."""
        self.assertEqual(authority_url(9), self.found[1].authority)
        self.assertTrue(self.found[1].authority.startswith(AUTHORITY))

    def testThePreambleIsNotRead(self):
        """ "2026" and "1.3.6.1.4.1" appear above the records; neither is one.

        A record is a bare number followed by an indented line, and nothing in
        the preamble is shaped that way.
        """
        self.assertNotIn(2026, [x.number for x in self.found])

    def testNoneOnRecordReadsAsNoName(self):
        """IANA writes ---none---, which is not an organization's name.

        A consumer has to render it as unregistered rather than printing the
        marker at a reader.
        """
        self.assertEqual("", self.found[3].organization)

    def testARegistrantKnowsItsArc(self):
        self.assertEqual(f"{ENTERPRISES}.9", self.found[1].arc)

    def testATrailingNumberWithNothingUnderItIsNotARecord(self):
        """Which is what a truncated download looks like."""
        self.assertEqual([], list(parse_registry("PRIVATE ENTERPRISE NUMBERS\n99\n")))

    def testAnEmptyRegistryReadsAsEmpty(self):
        self.assertEqual([], list(parse_registry("")))


class ReduceTestCase(unittest.TestCase):
    """What a downstream repository commits, and who decides."""

    def testTheDefaultKeepsTheWholeRecord(self):
        """The field set is an argument, and its default is everything.

        A corpus wanting less names less; the reducer does not assume for it.
        """
        reduced = reduce_registry(PUBLISHED)

        self.assertEqual(",".join(FIELDS), reduced.split("\n")[0])
        self.assertIn("person&cisco.com", reduced)

    def testAFieldSetNarrowsIt(self):
        reduced = reduce_registry(PUBLISHED, ["number", "organization"])

        self.assertEqual("number,organization", reduced.split("\n")[0])
        self.assertNotIn("person&cisco.com", reduced)

    def testTheNumberIsKeptWhetherOrNotItIsNamed(self):
        """A row that does not say which arc it is about is not a registration."""
        reduced = reduce_registry(PUBLISHED, ["organization"])

        self.assertEqual("number,organization", reduced.split("\n")[0])

    def testAFieldNoRecordHasIsRefused(self):
        """Silently dropping it would write a snapshot missing what was asked."""
        with self.assertRaises(ValueError) as caught:
            reduce_registry(PUBLISHED, ["number", "telephone"])

        self.assertIn("telephone", str(caught.exception))

    def testTheEmailIsNotNormalised(self):
        """IANA writes & rather than @, and this renders IANA's record."""
        self.assertIn("person&cisco.com", reduce_registry(PUBLISHED))
        self.assertNotIn("person@cisco.com", reduce_registry(PUBLISHED))

    def testNumberAndOrganizationSurvive(self):
        self.assertIn('9,"Cisco Systems, Inc."', reduce_registry(PUBLISHED))

    def testItIsInNumericOrder(self):
        """3076 above 42 would be string order, and a refresh would churn."""
        numbers = [
            int(line.split(",")[0])
            for line in reduce_registry(PUBLISHED).strip().split("\n")[1:]
        ]

        self.assertEqual(sorted(numbers), numbers)

    def testReducingTwiceProducesTheSameBytes(self):
        self.assertEqual(reduce_registry(PUBLISHED), reduce_registry(PUBLISHED))


class ReduceRowsTestCase(unittest.TestCase):
    """Which registrants a downstream repository commits.

    IANA revises 66,807 registrations daily, so committing the whole registry
    is a large file and a large monthly diff. A corpus may instead commit the
    registrants its own arcs use. pysnmp/mibs#407.
    """

    def testTheDefaultKeepsEveryRegistration(self):
        """Like the field set: the reducer does not assume for the caller."""
        self.assertEqual(
            len(reduce_registry(PUBLISHED).split("\n")),
            len(reduce_registry(PUBLISHED, None, None).split("\n")),
        )
        self.assertIn("Altiga", reduce_registry(PUBLISHED))

    def testAnArcListNarrowsIt(self):
        reduced = reduce_registry(PUBLISHED, None, [9])

        self.assertIn("Cisco Systems, Inc.", reduced)
        self.assertNotIn("Altiga", reduced)

    def testTheHeaderSurvivesTheNarrowing(self):
        """A snapshot of one registrant is still read back by load_registry,
        which needs the header to know what the columns are."""
        reduced = reduce_registry(PUBLISHED, None, [9])

        self.assertEqual(",".join(FIELDS), reduced.split("\n")[0])

    def testKeepingNothingIsARegistryWithNoRows(self):
        reduced = reduce_registry(PUBLISHED, None, [])

        self.assertEqual(",".join(FIELDS), reduced.strip())

    def testANumberTheRegistryDoesNotHaveIsNotAnError(self):
        """The registry's own gaps are a fact about the registry. Refusing
        would make a corpus's arc list unusable as input, since a corpus can
        perfectly well reach an arc nobody registered."""
        reduced = reduce_registry(PUBLISHED, None, [9, 4294967295])

        self.assertIn("Cisco Systems, Inc.", reduced)
        self.assertEqual(2, len(reduced.strip().split("\n")))

    def testItComposesWithTheFieldSet(self):
        reduced = reduce_registry(PUBLISHED, ["number", "organization"], [9])

        self.assertEqual('number,organization\n9,"Cisco Systems, Inc."\n', reduced)

    def testTheRowsAreStillInNumericOrder(self):
        numbers = [
            line.split(",")[0]
            for line in reduce_registry(PUBLISHED, None, [3076, 9, 42])
            .strip()
            .split("\n")[1:]
        ]

        self.assertEqual(["9", "42", "3076"], numbers)

    def testANarrowedSnapshotReducesToItself(self):
        """A refresh that changes nothing produces no diff, which is the whole
        reason a repository can commit one of these."""
        once = reduce_registry(PUBLISHED, None, [9, 42])

        self.assertEqual(once, reduce_registry(PUBLISHED, None, [9, 42]))


class LoadTestCase(unittest.TestCase):
    """Both forms are read, because a caller may hold either."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(text)

        return path

    def testThePublishedFormIsRead(self):
        found = load_registry(self.write("enterprise-numbers.txt", PUBLISHED))

        self.assertEqual("Cisco Systems, Inc.", found[9].organization)
        self.assertEqual("person&cisco.com", found[9].email)

    def testTheReducedFormIsRead(self):
        found = load_registry(self.write("pen.csv", reduce_registry(PUBLISHED)))

        self.assertEqual("Cisco Systems, Inc.", found[9].organization)
        self.assertEqual("person&cisco.com", found[9].email)

    def testANarrowedSnapshotReadsBackWithWhatItKept(self):
        """What a snapshot does not carry is empty, which is the same answer as
        a registration that has no contact on record: nothing to render."""
        found = load_registry(
            self.write(
                "lean.csv", reduce_registry(PUBLISHED, ["number", "organization"])
            )
        )

        self.assertEqual("Cisco Systems, Inc.", found[9].organization)
        self.assertEqual("", found[9].email)

    def testBothFormsAgree(self):
        """A caller should not get a different corpus for having reduced first."""
        self.assertEqual(
            load_registry(self.write("a.txt", PUBLISHED)),
            load_registry(self.write("b.csv", reduce_registry(PUBLISHED))),
        )

    def testAMissingFileRaises(self):
        """A build pointed at a registry that is not there is misconfigured.

        Reading it as empty would emit an index naming nobody, which looks
        exactly like a corpus registering under unallocated arcs.
        """
        with self.assertRaises(OSError):
            load_registry(os.path.join(self.tmp, "nope.csv"))


class ReducerCliTestCase(unittest.TestCase):
    """``python -m pysmi.registry``, which is how a snapshot is refreshed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def testItRefusesWithoutAFile(self):
        self.assertEqual(cli.EX_USAGE, cli.main(["pen"]))

    def testItRefusesAFieldNoRecordHas(self):
        path = os.path.join(self.tmp, "pen.txt")

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(PUBLISHED)

        self.assertEqual(cli.EX_USAGE, cli.main(["pen", "--fields=nope", path]))

    def testItReportsAFileItCannotRead(self):
        self.assertEqual(
            cli.EX_NOINPUT, cli.main(["pen", os.path.join(self.tmp, "nope")])
        )

    def published(self, name="pen.txt", text=PUBLISHED):
        path = os.path.join(self.tmp, name)

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(text)

        return path

    def captured(self, *arguments):
        out = io.StringIO()

        with contextlib.redirect_stdout(out):
            code = cli.main(["pen", *arguments])

        return code, out.getvalue()

    def testOnlyNarrowsTheRows(self):
        code, written = self.captured("--only=9", self.published())

        self.assertEqual(cli.EX_OK, code)
        self.assertIn("Cisco Systems, Inc.", written)
        self.assertNotIn("Altiga", written)

    def testOnlyFromReadsThemFromAFile(self):
        """What a corpus writes out of its own arcs: one number per line."""
        arcs = self.published("arcs.txt", "# the arcs this corpus uses\n9\n\n42\n")

        code, written = self.captured(f"--only-from={arcs}", self.published())

        self.assertEqual(cli.EX_OK, code)
        self.assertIn("Cisco", written)
        self.assertIn("42,,Nobody", written)
        self.assertNotIn("Altiga", written)

    def testItRefusesSomethingThatIsNotANumber(self):
        code, _ = self.captured("--only=9,cisco", self.published())

        self.assertEqual(cli.EX_USAGE, code)

    def testItReportsAnArcListItCannotRead(self):
        code, _ = self.captured(
            f"--only-from={os.path.join(self.tmp, 'nope')}", self.published()
        )

        self.assertEqual(cli.EX_NOINPUT, code)


class NotBundledTestCase(unittest.TestCase):
    """The registry is an input. It is not shipped and it is not fetched."""

    def testNoRegistryIsBundled(self):
        """5.1 MB of other people's contact details, changing daily, is not a
        thing to vendor into a compiler."""
        package = os.path.dirname(os.path.dirname(os.path.abspath(cli.__file__)))

        self.assertEqual(
            [],
            [
                name
                for _, _, files in os.walk(package)
                for name in files
                if "enterprise-number" in name.lower() or name == "pen-snapshot.csv"
            ],
        )

    def testTheParserFetchesNothing(self):
        """A corpus build resolves nothing over the network, and this is part
        of a corpus build."""
        from pysmi.registry import pen

        with open(pen.__file__, encoding="utf-8") as fileObj:
            source = fileObj.read()

        for forbidden in ("requests", "urllib", "http"):
            with self.subTest(name=forbidden):
                self.assertNotIn(f"import {forbidden}", source)


class RegistrantTestCase(unittest.TestCase):
    def testTheArcIsUnderTheEnterprisesNode(self):
        """RFC 2578 section 8.4 assigns it, and everything here hangs off it."""
        self.assertEqual("1.3.6.1.4.1", ENTERPRISES)
        self.assertEqual("1.3.6.1.4.1.9", Registrant(9, "Cisco").arc)

    def testTheContactFieldsDefaultToEmpty(self):
        """A snapshot that kept fewer fields still reads back as a record."""
        self.assertEqual(("", ""), Registrant(9, "Cisco")[2:])


if __name__ == "__main__":
    unittest.main()
