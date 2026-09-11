#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""What every arc in a corpus is called, and who says so.

The OID index picks whichever module mentioned an arc on its way past, which
is how ``snmpModules`` came to be attributed to a Nortel enterprise MIB and
``1.3`` to ``OCCAM-ETHERLIKE-MIB``. No ranking over MIB text can fix that,
because the fact is not in the MIB text.

What is pinned here is the order the sources are consulted in, that every name
says which source named it, and that an arc nothing names says so rather than
borrowing one. pysnmp/pysmi#288.
"""

import json
import unittest

from pysmi.corpus.arcs import (
    MODULE,
    REGISTRY,
    SCHEMA_VERSION,
    STANDARD,
    Arc,
    arcs,
    as_document,
    counts,
    prefixes,
    render_arcs,
)
from pysmi.registry.pen import Registrant
from pysmi.registry.smi import ArcName


def document(**nodes):
    """A jsondoc defining each named node at the OID given."""
    return {
        name: {"name": name, "class": "objectidentity", "oid": oid}
        for name, oid in nodes.items()
    }


def corpus(**modules):
    """``(module, jsondoc, tier, rfc)`` rows, as read_documents yields them."""
    return [(name, doc, 0, 0) for name, doc in modules.items()]


class PrefixTestCase(unittest.TestCase):
    """A tree renders the path to a node, not only the node."""

    def testEveryPrefixIsAnArc(self):
        self.assertEqual(["1", "1.3", "1.3.6"], prefixes("1.3.6"))

    def testAnArcIsItsOwnLastPrefix(self):
        self.assertEqual(["1"], prefixes("1"))


class SourceTestCase(unittest.TestCase):
    """Which source names an arc, when more than one could."""

    SMI = {
        "1.3.6.1.6.3": ArcName("1.3.6.1.6.3", "snmpModules", "https://iana/smi"),
    }

    ENTERPRISES = {9: Registrant(9, "Cisco Systems, Inc.")}

    def name(self, arc, ranked, **kwargs):
        found = arcs(
            corpus(**kwargs.pop("modules", {})),
            ranked,
            self.SMI,
            self.ENTERPRISES,
            **kwargs,
        )

        return found[arc]

    def testARegistryBeatsAModuleDescriptor(self):
        """This is the defect: RAPID-CITY mentions 1.3.6.1.6.3 and the index
        hands the arc to it. IANA says what the arc is."""
        found = self.name(
            "1.3.6.1.6.3",
            {"1.3.6.1.6.3.1": "RAPID-CITY"},
            modules={
                "RAPID-CITY": document(
                    somethingElse="1.3.6.1.6.3", anAnchor="1.3.6.1.6.3.1"
                )
            },
        )

        self.assertEqual("snmpModules", found.name)
        self.assertEqual(REGISTRY, found.source)

    def testTheEnterpriseRegistryNamesABareEnterpriseArc(self):
        """No module registers Cisco's bare arc, only what hangs beneath it."""
        found = self.name("1.3.6.1.4.1.9", {"1.3.6.1.4.1.9.9.138": "CISCO-MIB"})

        self.assertEqual("Cisco Systems, Inc.", found.name)
        self.assertEqual(REGISTRY, found.source)

    def testAStandardNamesWhatNoRegistryPublishes(self):
        """ITU-T's OID registry does not answer and IEEE publishes PDFs, so
        these arcs are cited rather than fetched."""
        found = self.name("1.0.8802", {"1.0.8802.1.1.2": "LLDP-MIB"})

        self.assertEqual("iso8802", found.name)
        self.assertEqual(STANDARD, found.source)
        self.assertIn("8802", found.reference)

    def testAModuleDescriptorNamesWhatNothingElseDoes(self):
        """The weakest source, and now labelled as what it is."""
        found = self.name(
            "1.3.6.1.4.1.9.9.138",
            {"1.3.6.1.4.1.9.9.138": "CISCO-ENTITY-ALARM-MIB"},
            modules={
                "CISCO-ENTITY-ALARM-MIB": document(
                    ciscoEntityAlarmMIB="1.3.6.1.4.1.9.9.138"
                )
            },
        )

        self.assertEqual("ciscoEntityAlarmMIB", found.name)
        self.assertEqual(MODULE, found.source)
        self.assertEqual("CISCO-ENTITY-ALARM-MIB", found.reference)

    def testAnArcNothingNamesSaysSo(self):
        """Better than borrowing a name, and the honest rendering of an arc
        registered to nobody."""
        found = self.name("1.3.6.1.4.1.1004849", {"1.3.6.1.4.1.1004849.1": "ODD-MIB"})

        self.assertEqual("", found.name)
        self.assertEqual("", found.source)

    def testTwoModulesNamingOneArcAgreeBetweenBuilds(self):
        """A descriptor is the weakest source and two builds must still agree."""
        modules = {
            "B-MIB": document(fromB="1.3.6.1.4.1.99"),
            "A-MIB": document(fromA="1.3.6.1.4.1.99"),
        }
        ranked = {"1.3.6.1.4.1.99": "A-MIB"}

        first = arcs(corpus(**modules), ranked)
        second = arcs(corpus(**dict(reversed(list(modules.items())))), ranked)

        self.assertEqual(first["1.3.6.1.4.1.99"], second["1.3.6.1.4.1.99"])


class ScopeTestCase(unittest.TestCase):
    """Which arcs are in the inventory at all."""

    def testThePathToAnArcIsInTheInventory(self):
        """A tree renders the path down to a node, so its ancestors are as
        much a part of the inventory as the node is."""
        found = arcs(corpus(), {"1.3.6.1.4.1.9": "CISCO-MIB"})

        self.assertEqual(
            [
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.9",
            ],
            list(found),
        )

    def testItIsNotFilteredToOneSubtree(self):
        """IEEE publishes its 802.1 MIBs under 1.3.111.2.802.1 and LLDP-MIB
        registers under 1.0.8802.1.1.2. A 1.3.6.1 filter drops both, and LLDP
        is among the most widely polled MIBs there is."""
        found = arcs(
            corpus(), {"1.0.8802.1.1.2": "LLDP-MIB", "1.3.111.2.802.1": "IEEE-MIB"}
        )

        self.assertIn("1.0.8802.1.1.2", found)
        self.assertIn("1.3.111.2.802.1", found)

    def testTheArcsAreInTreeOrder(self):
        """1.3.10 below 1.3.9 would be string order."""
        found = arcs(corpus(), {"1.3.10": "A-MIB", "1.3.9": "B-MIB"})

        self.assertEqual(["1", "1.3", "1.3.9", "1.3.10"], list(found))

    def testAnObjectsOwnArcIsNotANodeOfTheTree(self):
        """The set is the registration tree rather than every OID a module
        defines -- about 6,700 arcs over pysnmp/mibs instead of 95,000. An
        object is a thing inside a module, which the module page renders in
        context."""
        found = arcs(
            corpus(
                **{
                    "A-MIB": document(
                        anchor="1.3.6.1.4.1.99", anObject="1.3.6.1.4.1.99.1.2.3"
                    )
                }
            ),
            {"1.3.6.1.4.1.99": "A-MIB"},
        )

        self.assertNotIn("1.3.6.1.4.1.99.1.2.3", found)


class DocumentTestCase(unittest.TestCase):
    """The artifact as it is written."""

    def setUp(self):
        self.found = arcs(
            corpus(),
            {"1.3.6.1.4.1.9": "CISCO-MIB"},
            {"1": ArcName("1", "iso", "https://iana/smi")},
            {9: Registrant(9, "Cisco Systems, Inc.")},
        )

    def testTheMetaBlockCountsBySource(self):
        written = as_document(self.found)

        self.assertEqual(SCHEMA_VERSION, written["meta"]["schema"])
        self.assertEqual(len(self.found), written["meta"]["arcs"])
        self.assertEqual(2, written["meta"]["by-source"]["registry"])

    def testAnUnnamedArcIsCountedAsUnnamed(self):
        """It is a gap in the inventory rather than a failure: a corpus can
        perfectly well reach an arc registered to nobody."""
        self.assertIn("unnamed", as_document(self.found)["meta"]["by-source"])

    def testEveryArcCarriesItsSourceAndReference(self):
        written = as_document(self.found)

        for arc, data in written["arc"].items():
            with self.subTest(arc=arc):
                self.assertEqual({"name", "source", "reference"}, set(data))

    def testTheCountsAreWhatTheReportCarries(self):
        tally = counts(self.found)

        self.assertEqual(len(self.found), tally["arcs"])
        self.assertEqual(2, tally["registry"])

    def testItIsWrittenCompactlyOnOneLine(self):
        text = render_arcs(self.found)

        self.assertEqual(
            json.dumps(as_document(self.found), separators=(",", ":")) + "\n", text
        )

    def testTheSameCorpusRendersTheSameBytesTwice(self):
        self.assertEqual(render_arcs(self.found), render_arcs(self.found))

    def testAnArcKnowsItsOwnName(self):
        self.assertEqual("1.3", Arc("1.3", "org", REGISTRY).arc)


if __name__ == "__main__":
    unittest.main()
