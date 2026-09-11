#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Which enterprise arcs a corpus registers under, and who holds each.

The directory a module's file sits in is a filing convention, and it disagrees
with the registrations in practice. The registration is a published fact, and
this is the corpus projected onto it: 351 distinct arcs over pysnmp/mibs
against 290 vendor directories, which is the argument for driving navigation
from the registry rather than from the tree.

Two decisions are pinned here: an arc the registry does not name is reported as
unregistered rather than guessed at, and the grouping is by arc rather than by
company, because the registry does not model an acquisition and pysmi must not
infer one. pysnmp/pysmi#281.
"""

import json
import unittest

from pysmi.corpus.entity import (
    MODULE,
    REGISTRY,
    SCHEMA_VERSION,
    as_document,
    counts,
    enterprise_of,
    entities,
    module_contact,
    render_entities,
)
from pysmi.registry.pen import Registrant


def document(*oids, organization="", contactinfo="", lastupdated=""):
    """A jsondoc anchoring at each OID given.

    The identity carries ORGANIZATION and CONTACT-INFO only when asked, since
    JsonCodeGen gates both behind the texts switch and a corpus built without
    them has neither.
    """
    found = {
        f"anchor{index}": {
            "name": f"anchor{index}",
            "class": "moduleidentity" if index == 0 else "objectidentity",
            "oid": oid,
        }
        for index, oid in enumerate(oids)
    }

    if organization:
        found["anchor0"]["organization"] = organization

    if contactinfo:
        found["anchor0"]["contactinfo"] = contactinfo

    if lastupdated:
        found["anchor0"]["lastupdated"] = lastupdated

    return found


def corpus(**modules):
    """``(module, jsondoc, tier, rfc)`` rows, as read_documents yields them."""
    return [(name, doc, 0, 0) for name, doc in modules.items()]


class EnterpriseOfTestCase(unittest.TestCase):
    """Reading the registrant arc off an OID."""

    def testAnEnterpriseOidGivesItsNumber(self):
        self.assertEqual(9, enterprise_of("1.3.6.1.4.1.9.9.138"))

    def testTheArcItselfGivesItsNumber(self):
        self.assertEqual(9, enterprise_of("1.3.6.1.4.1.9"))

    def testAStandardOidHasNoRegistrant(self):
        """1.3.6.1.2.1 is the standard tree: nobody registered it privately."""
        self.assertIsNone(enterprise_of("1.3.6.1.2.1.2.2.1.8"))

    def testSomethingThatIsNotAnOidHasNoRegistrant(self):
        self.assertIsNone(enterprise_of("1.3.6.1.4.1.notanumber"))


class EntitiesTestCase(unittest.TestCase):
    """What the corpus registers, and who the registry says holds it."""

    REGISTRY = {
        9: Registrant(9, "Cisco Systems, Inc.", "Dave J", "davej&cisco.com"),
        3076: Registrant(3076, "Altiga Networks, Inc.", "A Person", "p&altiga.com"),
    }

    def testEachArcCarriesTheModulesUnderIt(self):
        found = entities(
            corpus(
                **{
                    "CISCO-A-MIB": document("1.3.6.1.4.1.9.1"),
                    "CISCO-B-MIB": document("1.3.6.1.4.1.9.2"),
                    "ALTIGA-MIB": document("1.3.6.1.4.1.3076.1"),
                }
            ),
            self.REGISTRY,
        )

        self.assertEqual(("CISCO-A-MIB", "CISCO-B-MIB"), found[9].modules)
        self.assertEqual(("ALTIGA-MIB",), found[3076].modules)

    def testTheRegistryNamesTheArc(self):
        found = entities(
            corpus(**{"A-MIB": document("1.3.6.1.4.1.9.1")}), self.REGISTRY
        )

        self.assertEqual("Cisco Systems, Inc.", found[9].organization)

    def testTheRegistrationIsCarriedAsAContact(self):
        """A registrant page is an accountability aid as well as navigation."""
        found = entities(
            corpus(**{"A-MIB": document("1.3.6.1.4.1.9.1")}), self.REGISTRY
        )

        self.assertEqual(1, len(found[9].contacts))

        contact = found[9].contacts[0]

        self.assertEqual(REGISTRY, contact.source)
        self.assertEqual("Dave J", contact.contact)
        self.assertEqual("davej&cisco.com", contact.email)
        self.assertIn("iana.org", contact.authority)

    def testAnArcWithNothingSayingAnythingHasNoContacts(self):
        """The page says nothing rather than showing blanks."""
        found = entities(corpus(**{"ODD-MIB": document("1.3.6.1.4.1.1004849.1")}))

        self.assertEqual((), found[1004849].contacts)

    def testAnArcTheRegistryDoesNotNameIsUnregistered(self):
        """pysnmp/mibs has exactly one, above anything IANA has allocated.

        The honest rendering is that nobody registered it. Guessing from the
        directory the file sits in would publish a convention as a fact.
        """
        found = entities(
            corpus(**{"ODD-MIB": document("1.3.6.1.4.1.1004849.1")}), self.REGISTRY
        )

        self.assertEqual("", found[1004849].organization)
        self.assertEqual(("ODD-MIB",), found[1004849].modules)

    def testGroupingIsByArcAndNotByCompany(self):
        """Cisco holds 9 and, from the Altiga acquisition, 3076 -- which IANA
        still lists as Altiga. Nothing in the registry models that, so two
        arcs stay two entries."""
        found = entities(
            corpus(
                **{
                    "CISCO-MIB": document("1.3.6.1.4.1.9.1"),
                    "ALTIGA-MIB": document("1.3.6.1.4.1.3076.1"),
                }
            ),
            self.REGISTRY,
        )

        self.assertEqual([9, 3076], sorted(found))
        self.assertEqual("Altiga Networks, Inc.", found[3076].organization)

    def testAModuleUnderTwoArcsAppearsUnderBoth(self):
        found = entities(
            corpus(**{"BOTH-MIB": document("1.3.6.1.4.1.9.1", "1.3.6.1.4.1.3076.1")}),
            self.REGISTRY,
        )

        self.assertEqual(("BOTH-MIB",), found[9].modules)
        self.assertEqual(("BOTH-MIB",), found[3076].modules)

    def testAStandardModuleRegistersUnderNoArc(self):
        found = entities(
            corpus(**{"IF-MIB": document("1.3.6.1.2.1.31")}), self.REGISTRY
        )

        self.assertEqual({}, found)

    def testWithoutARegistryTheArcsAreStillTheArcs(self):
        """The corpus knows what it registers under whether or not anybody
        told it whose that is."""
        found = entities(corpus(**{"A-MIB": document("1.3.6.1.4.1.9.1")}))

        self.assertEqual(("A-MIB",), found[9].modules)
        self.assertEqual("", found[9].organization)


class ContactTestCase(unittest.TestCase):
    """Who to report a problem with an arc to, and who says so.

    Two sources reach an enterprise arc. The module's own CONTACT-INFO is the
    publisher's current statement of where to report a problem; the IANA
    record is undated and often stale. So the module ranks first, and each
    carries its source so a reader can weigh them.
    """

    REGISTRY = {9: Registrant(9, "Cisco Systems, Inc.", "Dave J", "davej&cisco.com")}

    BLOCK = "Cisco Systems\n Customer Service\n cs-snmp@cisco.com"

    def testAModuleStatesItsOwnContact(self):
        found = module_contact(
            "A-MIB",
            document("1.3.6.1.4.1.9.1", organization="Cisco", contactinfo=self.BLOCK),
        )

        self.assertEqual(MODULE, found.source)
        self.assertEqual("Cisco", found.organization)
        self.assertEqual(self.BLOCK, found.contact)
        self.assertEqual("A-MIB", found.module)

    def testTheBlockIsRenderedAsPublishedRatherThanPickedApart(self):
        """A CONTACT-INFO block holds a company, an address, a phone and a
        mailbox. Picking one address out of it would be this module deciding
        which of several is the right one."""
        found = module_contact(
            "A-MIB", document("1.3.6.1.4.1.9.1", contactinfo=self.BLOCK)
        )

        self.assertEqual("", found.email)
        self.assertIn("cs-snmp@cisco.com", found.contact)

    def testACorpusWithoutTextsHasNoModuleContact(self):
        """JsonCodeGen gates organization and contactinfo behind the texts
        switch, so this source is unreachable until pysnmp/pysmi#277 lands."""
        self.assertIsNone(module_contact("A-MIB", document("1.3.6.1.4.1.9.1")))

    def testTheModuleOutranksTheRegistration(self):
        """The registry records who registered an arc when they registered it.
        A vendor's current support address is worth more."""
        found = entities(
            corpus(
                **{
                    "A-MIB": document(
                        "1.3.6.1.4.1.9.1",
                        organization="Cisco",
                        contactinfo=self.BLOCK,
                    )
                }
            ),
            self.REGISTRY,
        )

        self.assertEqual([MODULE, REGISTRY], [x.source for x in found[9].contacts])

    def testTheFreshestModuleSpeaksForTheArc(self):
        """Cisco has 1,289 modules under arc 9, so which one speaks has to be
        decided rather than left to iteration order."""
        found = entities(
            corpus(
                **{
                    "OLD-MIB": document(
                        "1.3.6.1.4.1.9.1",
                        contactinfo="old address",
                        lastupdated="1996-01-01 00:00",
                    ),
                    "NEW-MIB": document(
                        "1.3.6.1.4.1.9.2",
                        contactinfo="current address",
                        lastupdated="2019-01-01 00:00",
                    ),
                }
            ),
            self.REGISTRY,
        )

        self.assertEqual("current address", found[9].contacts[0].contact)
        self.assertEqual("NEW-MIB", found[9].contacts[0].module)

    def testTwoBuildsChooseTheSameSpeaker(self):
        """The module name breaks a tie on the date, so the artifact is stable."""
        modules = {
            "B-MIB": document("1.3.6.1.4.1.9.1", contactinfo="b"),
            "A-MIB": document("1.3.6.1.4.1.9.2", contactinfo="a"),
        }

        first = entities(corpus(**modules), self.REGISTRY)
        second = entities(
            corpus(**dict(reversed(list(modules.items())))), self.REGISTRY
        )

        self.assertEqual(first[9].contacts, second[9].contacts)

    def testTheRegistrationCarriesWhereToCorrectIt(self):
        """A correction to a registration belongs at IANA."""
        found = entities(
            corpus(**{"A-MIB": document("1.3.6.1.4.1.9.1")}), self.REGISTRY
        )

        self.assertEqual(
            "https://www.iana.org/assignments/enterprise-numbers#9",
            found[9].contacts[0].authority,
        )

    def testAModuleContactCarriesNoAuthorityLink(self):
        """The correction is a new revision of the MIB, not a form to fill in."""
        found = module_contact(
            "A-MIB", document("1.3.6.1.4.1.9.1", contactinfo=self.BLOCK)
        )

        self.assertEqual("", found.authority)

    def testEveryContactIsRenderedWithItsSource(self):
        """So a reader can weigh a current support address against an undated
        registration rather than being handed one answer."""
        found = entities(
            corpus(**{"A-MIB": document("1.3.6.1.4.1.9.1", contactinfo=self.BLOCK)}),
            self.REGISTRY,
        )

        for contact in found[9].contacts:
            with self.subTest(source=contact.source):
                self.assertIn(contact.source, (MODULE, REGISTRY))


class DocumentTestCase(unittest.TestCase):
    """The artifact as it is written."""

    def setUp(self):
        self.found = entities(
            corpus(
                **{
                    "A-MIB": document("1.3.6.1.4.1.9.1"),
                    "B-MIB": document("1.3.6.1.4.1.1004849.1"),
                }
            ),
            {9: Registrant(9, "Cisco Systems, Inc.", "Dave J", "davej&cisco.com")},
        )

    def testTheMetaBlockCountsWhatIsThere(self):
        written = as_document(self.found)

        self.assertEqual(SCHEMA_VERSION, written["meta"]["schema"])
        self.assertEqual(2, written["meta"]["arcs"])
        self.assertEqual(1, written["meta"]["named"])
        self.assertEqual(1, written["meta"]["unregistered"])

    def testItIsKeyedByTheFullArc(self):
        """So a consumer holding an OID looks it up without rebuilding a prefix."""
        self.assertEqual(
            ["1.3.6.1.4.1.1004849", "1.3.6.1.4.1.9"],
            sorted(as_document(self.found)["entity"]),
        )

    def testTheCountsAreWhatTheReportCarries(self):
        self.assertEqual({"arcs": 2, "named": 1, "unregistered": 1}, counts(self.found))

    def testItIsWrittenCompactlyOnOneLine(self):
        """A generated artifact, and nobody reads it by eye. pysnmp/pysmi#283.

        Asserted against a compact dump rather than by looking for ", ",
        because an organization's name has one in it.
        """
        text = render_entities(self.found)

        self.assertEqual(
            json.dumps(as_document(self.found), separators=(",", ":")) + "\n", text
        )
        self.assertEqual(1, text.count("\n"))

    def testTheSameCorpusRendersTheSameBytesTwice(self):
        self.assertEqual(render_entities(self.found), render_entities(self.found))

    def testTheRenderedArtifactReadsBackAsTheDocument(self):
        self.assertEqual(
            as_document(self.found), json.loads(render_entities(self.found))
        )


if __name__ == "__main__":
    unittest.main()
