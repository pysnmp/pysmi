#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The bundle manifest as consumers see it.

``scripts/update_bundled_mibs.py`` reads the manifest off the source tree
because it writes it. Everyone else reads it through :py:mod:`pysmi.mibs`,
out of package data, which is the copy an installed wheel has. These assert
the second path works and says the same thing as the first -- a manifest that
only resolves in a checkout would leave every consumer of ``successor_for``
answering ``None`` in production and passing in CI.
"""

import importlib.resources
import json
import unittest

from pysmi import compiler as compiler_module
from pysmi import mibs
from pysmi.codegen import JsonCodeGen
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
from scripts import update_bundled_mibs


class ManifestShipsInThePackageTestCase(unittest.TestCase):
    def testTheRuntimeManifestIsTheMaintainerScriptsManifest(self):
        self.assertEqual(update_bundled_mibs.manifest(), mibs.manifest())

    def testEveryBundledModuleHasAManifestEntry(self):
        bundled = {
            entry.name
            for entry in (update_bundled_mibs.DEST).iterdir()
            if entry.is_file() and not entry.name.startswith("__")
        }

        self.assertEqual(bundled, set(mibs.manifest()))


class SupersessionTestCase(unittest.TestCase):
    def testAModuleReplacedWholeAnswersForAnyOid(self):
        self.assertEqual("VRRPV3-MIB", mibs.successor_for("VRRP-MIB"))
        self.assertEqual(
            "VRRPV3-MIB", mibs.successor_for("VRRP-MIB", "1.3.6.1.2.1.68.1")
        )

    def testASplitModuleAnswersPerSubtree(self):
        for oid, expected in (
            ("1.3.6.1.2.1.1.1.0", "SNMPv2-MIB"),
            ("1.3.6.1.2.1.2.2.1.2", "IF-MIB"),
            ("1.3.6.1.2.1.4.20.1.1", "IP-MIB"),
            ("1.3.6.1.2.1.5.1.0", "IP-MIB"),
            ("1.3.6.1.2.1.6.13.1.1", "TCP-MIB"),
            ("1.3.6.1.2.1.7.1.0", "UDP-MIB"),
            ("1.3.6.1.2.1.11.1.0", "SNMPv2-MIB"),
        ):
            with self.subTest(oid=oid):
                self.assertEqual(expected, mibs.successor_for("RFC1213-MIB", oid))
                self.assertEqual(expected, mibs.successor_for("RFC1158-MIB", oid))

    def testASubtreeNothingReplacedAnswersNone(self):
        """egp and transmission were not taken over by anything to name."""
        self.assertIsNone(mibs.successor_for("RFC1213-MIB", "1.3.6.1.2.1.8.1.0"))
        self.assertIsNone(mibs.successor_for("RFC1213-MIB", "1.3.6.1.2.1.10.7.2.1.1"))

    def testAPrefixDoesNotClaimALongerArc(self):
        """1.3.6.1.2.1.2 is interfaces; 1.3.6.1.2.1.22 is nothing of the sort."""
        self.assertIsNone(mibs.successor_for("RFC1213-MIB", "1.3.6.1.2.1.22.1.1"))

    def testASplitModuleWithoutAnOidCannotBeAnswered(self):
        self.assertIsNone(mibs.successor_for("RFC1213-MIB"))

    def testAModuleThatIsNotBundledAnswersNone(self):
        self.assertIsNone(mibs.successor_for("CISCO-SMI", "1.3.6.1.4.1.9"))
        self.assertEqual({}, mibs.successors("CISCO-SMI"))

    def testEverySubtreeSuccessorIsAModuleTheBundleHas(self):
        """The per-subtree map is what answers a lookup, so it has to land.

        ``successors_reviewed`` is history and may name a module the bundle
        does not carry -- RFC1284-MIB records RFC1398-MIB, which RFC 1643 and
        then EtherLike-MIB went on to replace, so the bundle has the end of
        that chain and not its middle. A subtree entry is not history: it is
        the answer handed to a caller resolving an OID, and naming a module
        pysmi does not ship would make it unusable.
        """
        known = set(mibs.manifest())

        for name, entry in sorted(mibs.manifest().items()):
            for successor in sorted(set(entry.get("successors_by_oid", {}).values())):
                with self.subTest(module=name, successor=successor):
                    self.assertIn(successor, known)

    def testEverySubtreeSuccessorIsKeyedByADottedOid(self):
        for name, entry in sorted(mibs.manifest().items()):
            for prefix in sorted(entry.get("successors_by_oid", {})):
                with self.subTest(module=name, prefix=prefix):
                    self.assertTrue(
                        all(arc.isdigit() for arc in prefix.split(".")),
                        f"{prefix} is not a dotted OID",
                    )


class SupersessionIsNotPerOidTestCase(unittest.TestCase):
    """The property :py:func:`pysmi.mibs.successors` documents, asserted.

    ``successors_reviewed`` says a later RFC replaced a module. It does not say
    the successor took over the module's OIDs, and for six of the sixteen
    recorded relations it did not -- the successor republished the material on
    a new arc and the superseded module is still the only definition of the old
    one. A consumer that reads supersession as "demote this module for this
    OID" gets those six wrong.

    What makes a safe per-OID rule possible is that the split is clean: a
    successor redefines *all* of its predecessor's OIDs or *none* of them. So
    "demote only if the successor also claims this OID" is exact rather than a
    heuristic. If a partial overlap ever appeared, that rule would start
    silently dropping definitions -- which is what this test is here to catch.
    """

    #: The ASN.1 the bundle actually carries. ``successors_reviewed`` is
    #: history and may name a module pysmi does not ship -- RFC1284-MIB records
    #: RFC1398-MIB, which later RFCs replaced in turn -- so a name is checked
    #: against the sources before it is compiled, rather than compiled and the
    #: failure swallowed.
    BUNDLED = frozenset(
        path.name
        for path in importlib.resources.files("pysmi.mibs.asn1").iterdir()
        if path.is_file()
    )

    @classmethod
    def _oids(cls, name, compiler, documents):
        if name not in cls.BUNDLED:
            return set()

        if name not in documents:
            compiler.compile(name, noDeps=True, rebuild=True)

        document = documents.get(name, {})

        return {
            body["oid"]
            for symbol, body in document.items()
            if symbol not in ("meta", "imports")
            and isinstance(body, dict)
            and body.get("oid")
        }

    def testASuccessorCoversAllOfItsPredecessorsOidsOrNoneOfThem(self):
        documents = {}
        compiler = compiler_module.MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(
                lambda mibname, data, cbCtx: documents.__setitem__(
                    mibname, json.loads(data)
                )
            ),
            useBundledMibs=False,
        )
        compiler.add_sources(PackageReader("pysmi.mibs.asn1"))

        for name, entry in sorted(mibs.manifest().items()):
            for successor in sorted(set(entry.get("successors_reviewed", {}).values())):
                mine = self._oids(name, compiler, documents)
                theirs = self._oids(successor, compiler, documents)
                if not theirs:
                    continue  # a successor the bundle does not carry

                with self.subTest(module=name, successor=successor):
                    shared = mine & theirs
                    self.assertIn(
                        len(shared),
                        (0, len(mine)),
                        f"{successor} redefines {len(shared)} of {name}'s "
                        f"{len(mine)} OIDs -- supersession is no longer all "
                        f"or nothing, and a per-OID demotion rule built on it "
                        f"would drop the rest",
                    )


if __name__ == "__main__":
    unittest.main()
