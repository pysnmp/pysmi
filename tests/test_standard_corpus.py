#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Compile the standard modules and assert what they exercise.

Every other test here hands the codegens a module a few clauses long, written to
isolate one rule. Those catch a clause read wrongly. They cannot catch a module
that fails once its imports, textual conventions, tables and conformance
statements are all real, and they cannot catch generated code that is valid
Python but will not load.

``tests/data/asn1/`` holds the standard modules for that, taken from the org's
own ``pysnmp/mibs``. Between them they reach most of the SMI surface: AUGMENTS,
multi-column and IMPLIED indices, Counter64, the generic traps, conformance
macros, and a large enumeration. See pysnmp/pysmi#92.
"""

import functools
import json
import pathlib
import sys
import unittest

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiStarParser
from pysmi.reader import FileReader
from pysmi.searcher import StubSearcher
from pysmi.writer import CallbackWriter

ASN1 = pathlib.Path(__file__).parent / "data" / "asn1"

#: The modules asked for by name. Their dependencies are pulled in as well.
TARGETS = (
    "SNMPv2-MIB",
    "IF-MIB",
    "INET-ADDRESS-MIB",
    "IANAifType-MIB",
    "SNMP-TARGET-MIB",
    "RFC1269-MIB",
)

#: Load order for the generated pysnmp modules, dependencies first.
LOAD_ORDER = (
    "SNMPv2-MIB",
    "IANAifType-MIB",
    "INET-ADDRESS-MIB",
    "SNMP-FRAMEWORK-MIB",
    "IF-MIB",
    "SNMP-TARGET-MIB",
    "RFC1269-MIB",
)


@functools.cache
def compiled(backend):
    """Compile the corpus once per backend and hand back what was written.

    Both backends are stubbed with ``JsonCodeGen.baseMibs`` rather than with
    their own. The extra entries in ``PySnmpCodeGen.baseMibs`` name modules
    pysnmp already ships, not modules pysmi cannot compile, and stubbing those
    would skip most of this corpus.

    Args:
        backend: a code generator class

    Returns:
        A tuple of the per-module compilation status and the artifact each
        module produced, both keyed by module name.
    """
    written = {}
    compiler = MibCompiler(
        SmiStarParser(),
        backend(),
        CallbackWriter(lambda name, data, ctx: written.__setitem__(name, data)),
    )
    compiler.add_sources(FileReader(str(ASN1)))
    compiler.add_searchers(StubSearcher(*JsonCodeGen.baseMibs))
    return compiler.compile(*TARGETS), written


def documents():
    """The corpus as decoded JSON documents, keyed by module name."""
    _, written = compiled(JsonCodeGen)
    return {name: json.loads(doc) for name, doc in written.items()}


class CorpusCompilesTestCase(unittest.TestCase):
    """Every module in the corpus survives both backends."""

    def testTheJsonBackendCompilesEveryTarget(self):
        status, _ = compiled(JsonCodeGen)
        for name in TARGETS:
            with self.subTest(module=name):
                self.assertEqual(status[name], "compiled")

    def testThePySnmpBackendCompilesEveryTarget(self):
        status, _ = compiled(PySnmpCodeGen)
        for name in TARGETS:
            with self.subTest(module=name):
                self.assertEqual(status[name], "compiled")

    def testTheDependenciesArePulledInAndCompiledToo(self):
        """SNMP-TARGET-MIB names SNMP-FRAMEWORK-MIB, which nothing asked for."""
        status, _ = compiled(JsonCodeGen)
        self.assertEqual(status["SNMP-FRAMEWORK-MIB"], "compiled")

    def testTheModulesPysmiRefusesAreLeftAlone(self):
        """SNMPv2-SMI and friends define MACROs; the stub searcher skips them."""
        status, _ = compiled(JsonCodeGen)
        for name in ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF"):
            with self.subTest(module=name):
                self.assertEqual(status[name], "untouched")

    def testCompilingTwiceGivesTheSameBytes(self):
        """The corpus is only a regression baseline if it renders repeatably."""
        for backend in (JsonCodeGen, PySnmpCodeGen):
            _, first = compiled(backend)
            compiled.cache_clear()
            _, second = compiled(backend)
            with self.subTest(backend=backend.__name__):
                self.assertEqual(first, second)


class CorpusSurfaceTestCase(unittest.TestCase):
    """The SMI constructs these modules carry that short fixtures do not."""

    @classmethod
    def setUpClass(cls):
        cls.docs = documents()

    def testAugmentsNamesTheRowItExtends(self):
        self.assertEqual(
            self.docs["IF-MIB"]["ifXEntry"]["augmentation"],
            {"name": "ifXEntry", "module": "IF-MIB", "object": "ifEntry"},
        )

    def testAMultiColumnIndexKeepsItsOrder(self):
        self.assertEqual(
            [i["object"] for i in self.docs["IF-MIB"]["ifRcvAddressEntry"]["indices"]],
            ["ifIndex", "ifRcvAddressAddress"],
        )

    def testAnImpliedIndexIsMarkedAsOne(self):
        entry = self.docs["SNMP-TARGET-MIB"]["snmpTargetAddrEntry"]
        self.assertEqual(
            entry["indices"],
            [{"module": "SNMP-TARGET-MIB", "object": "snmpTargetAddrName", "implied": 1}],
        )

    def testAPlainIndexIsNotMarkedImplied(self):
        for index in self.docs["IF-MIB"]["ifEntry"]["indices"]:
            with self.subTest(object=index["object"]):
                self.assertEqual(index["implied"], 0)

    def testCounter64SurvivesAsItself(self):
        self.assertEqual(self.docs["IF-MIB"]["ifHCInOctets"]["syntax"]["type"], "Counter64")

    def testTheGenericTrapsSitWhereRfc3584PointsAtThem(self):
        """SNMPv2-MIB declares these directly, so this pins the mapping target.

        ``coldStart`` here is a NOTIFICATION-TYPE with an OID of its own, not a
        converted TRAP-TYPE. It is the address RFC 3584 Section 3.1 sends the
        generic traps to, which is what makes it worth pinning beside
        ``testAnSmiV1TrapIsGivenItsNotificationOid``. The conversion itself is
        exercised by RFC1269-MIB below, and by the unit tests for
        ``trap_type_oid``.
        """
        snmpv2 = self.docs["SNMPv2-MIB"]
        self.assertEqual(snmpv2["coldStart"]["oid"], "1.3.6.1.6.3.1.1.5.1")
        self.assertEqual(snmpv2["coldStart"]["class"], "notificationtype")

    def testAnSmiV1TrapIsGivenItsNotificationOid(self):
        """RFC 3584 Section 2.1.2 (5): enterprise, a zero, then the trap number.

        RFC1269-MIB is SMIv1 and its ENTERPRISE is ``bgp``, so these take the
        enterprise-specific form rather than the ``snmpTraps`` one.
        """
        bgp = self.docs["RFC1269-MIB"]
        self.assertEqual(bgp["bgpEstablished"]["class"], "notificationtype")
        self.assertEqual(bgp["bgpEstablished"]["oid"], "1.3.6.1.2.1.15.0.1")
        self.assertEqual(bgp["bgpBackwardTransition"]["oid"], "1.3.6.1.2.1.15.0.2")

    def testTheConformanceMacrosAreRecognised(self):
        snmpv2 = self.docs["SNMPv2-MIB"]
        self.assertEqual(snmpv2["snmpBasicCompliance"]["class"], "modulecompliance")
        self.assertEqual(snmpv2["snmpGroup"]["class"], "objectgroup")

    def testATextualConventionKeepsItsSizeConstraint(self):
        inet = self.docs["INET-ADDRESS-MIB"]["InetAddress"]
        self.assertEqual(inet["class"], "textualconvention")
        self.assertEqual(inet["type"]["constraints"]["size"], [{"min": 0, "max": 255}])

    def testALargeEnumerationIsKeptWhole(self):
        enumeration = self.docs["IANAifType-MIB"]["IANAifType"]["type"]["constraints"]["enumeration"]
        self.assertEqual(len(enumeration), 286)
        self.assertEqual(enumeration["ethernetCsmacd"], 6)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
