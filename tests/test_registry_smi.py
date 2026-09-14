#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""IANA's smi-numbers registry: what the arcs under 1.3.6.1 are called.

The OID index ranks modules to decide which owns an arc, and for the arcs
above the ones a module registers it has nothing good to choose from -- so it
picks whichever module mentioned the arc on its way past, and pysnmp/mibs ends
up attributing ``snmpModules`` to a Nortel enterprise MIB. The fact is not in
the MIB text. It is published, and this reads it. pysnmp/pysmi#288.

The file names arcs in three places and they disagree, so what is pinned here
is the order.
"""

import unittest

from pysmi import error
from pysmi.registry.smi import AUTHORITY, ArcName, parse_smi_numbers

#: The published shape, cut down: nested registries, a description naming the
#: arc it covers, and records under it. Both real disagreements are here --
#: 1.3.6.1.6.3's record carries IANA's own "smnpModules" typo, and a deeper
#: description spells 1.3.6.1.2.1.2 "interface" where its record says
#: "interfaces".
PUBLISHED = """<?xml version='1.0' encoding='UTF-8'?>
<registry xmlns="http://www.iana.org/assignments" id="smi-numbers">
  <title>Structure of Management Information (SMI) Numbers</title>
  <registry id="smi-numbers-2">
    <description>iso.org.dod.internet.mgmt (1.3.6.1.2.)</description>
    <record>
      <value>1</value>
      <name>mib-2</name>
    </record>
    <registry id="smi-numbers-3">
      <description>iso.org.dod.internet.mgmt.mib-2 (1.3.6.1.2.1)</description>
      <record>
        <value>2</value>
        <name>interfaces</name>
      </record>
      <record>
        <value>5-16</value>
        <name>a range, which registers no single arc</name>
      </record>
    </registry>
    <registry id="smi-numbers-5">
      <description>iso.org.dod.internet.mgmt.mib-2.interface.ifTable.ifEntry.ifType (1.3.6.1.2.1.2.2.1.3)</description>
    </registry>
  </registry>
  <registry id="smi-numbers-59">
    <description>iso.org.dod.internet.snmpv2 (1.3.6.1.6)</description>
    <record>
      <value>3</value>
      <name>smnpModules</name>
    </record>
    <registry id="smi-numbers-61">
      <description>iso.org.dod.internet.snmpv2.snmpModules (1.3.6.1.6.3) - No more registrations</description>
    </registry>
  </registry>
</registry>
"""


class ParseTestCase(unittest.TestCase):
    """Reading the registry."""

    @classmethod
    def setUpClass(cls):
        cls.found = parse_smi_numbers(PUBLISHED)

    def testARecordNamesItsArc(self):
        self.assertEqual("mib-2", self.found["1.3.6.1.2.1"].name)

    def testTheTopOfTheTreeIsNamedFromADescriptionPath(self):
        """Nothing in the file names 1 iso, 1.3 org, 1.3.6 dod or 1.3.6.1
        internet as a record. Every registry's description spells the whole
        path, and that is where those four come from."""
        self.assertEqual("iso", self.found["1"].name)
        self.assertEqual("org", self.found["1.3"].name)
        self.assertEqual("dod", self.found["1.3.6"].name)
        self.assertEqual("internet", self.found["1.3.6.1"].name)

    def testARegistrysOwnNameBeatsARecord(self):
        """1.3.6.1.6.3's record carries IANA's own "smnpModules" typo. The
        registry that arc actually is calls itself snmpModules, and naming a
        node from the registry it is beats naming it from a list entry."""
        self.assertEqual("snmpModules", self.found["1.3.6.1.6.3"].name)

    def testARecordBeatsAPathComponent(self):
        """1.3.6.1.2.1.2 has no registry of its own. Its record says
        "interfaces"; a deeper registry's description spells "interface" on
        its way past, and a path component is the weakest source."""
        self.assertEqual("interfaces", self.found["1.3.6.1.2.1.2"].name)

    def testATrailingDotInTheArcIsNotAnArc(self):
        """The file writes (1.3.6.1.2.) for the mgmt registry."""
        self.assertEqual("mgmt", self.found["1.3.6.1.2"].name)
        self.assertNotIn("1.3.6.1.2.", self.found)

    def testProseAfterTheArcIsNotPartOfIt(self):
        """smi-numbers-61's description runs on past the parenthesis."""
        self.assertIn("1.3.6.1.6.3", self.found)

    def testARangeRegistersNoSingleArc(self):
        """ "5-16" names no one arc, so there is nothing here to name."""
        self.assertNotIn("1.3.6.1.2.1.5-16", self.found)

    def testEveryNameCarriesItsAuthority(self):
        """A reader weighing one name against another needs to know which of
        them came from a registry."""
        for arc, named in self.found.items():
            with self.subTest(arc=arc):
                self.assertEqual(AUTHORITY, named.authority)

    def testTheArcIsCarriedOnTheRecord(self):
        self.assertEqual(ArcName("1", "iso", AUTHORITY), self.found["1"])

    def testSomethingThatIsNotTheRegistryIsRefused(self):
        """A build pointed at the wrong file should say so, not read it as
        a registry naming nothing."""
        with self.assertRaises(error.PySmiError):
            parse_smi_numbers("this is not XML at all <")

    def testAnEmptyRegistryNamesNothing(self):
        self.assertEqual({}, parse_smi_numbers("<registry/>"))


if __name__ == "__main__":
    unittest.main()
