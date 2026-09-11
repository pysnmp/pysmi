#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The bundle manifest as consumers see it.

``scripts/update_bundled_mibs.py`` reads the manifest off the source tree
because it writes it. Everyone else reads it through :py:mod:`pysmi.mibs`,
out of package data, which is the copy an installed wheel has. These assert
the second path works and says the same thing as the first -- a manifest that
only resolves in a checkout would leave every consumer of ``successor_for``
answering ``None`` in production and passing in CI.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from pysmi import compiler as compiler_module
from pysmi import mibs
from pysmi.codegen import JsonCodeGen
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.writer import CallbackWriter
from scripts import update_bundled_mibs
from scripts.patches import APPLIED, bundled_patches


class ManifestShipsInThePackageTestCase(unittest.TestCase):
    def testTheRuntimeManifestIsTheMaintainerScriptsManifest(self):
        self.assertEqual(update_bundled_mibs.manifest(), mibs.manifest())

    def testEveryBundledModuleHasAManifestEntry(self):
        carried = {
            path.name
            for path in update_bundled_mibs.held_files(update_bundled_mibs.DEST)
        }

        self.assertEqual(carried, set(mibs.bundled()))

    def testEveryHeldModuleHasAManifestEntry(self):
        held = {
            path.name
            for path in update_bundled_mibs.held_files(update_bundled_mibs.FUTURE)
        }

        self.assertEqual(held, set(mibs.future()))

    def testTheTwoTiersPartitionTheManifest(self):
        """Every entry is in exactly one of them, and they cover the manifest."""
        self.assertEqual(set(), mibs.bundled() & mibs.future())
        self.assertEqual(set(mibs.manifest()), mibs.bundled() | mibs.future())

    def testTheTreeAgreesWithTheManifestAboutWhichTierEachModuleIsIn(self):
        """The check ``--check`` runs offline, run here so CI runs it too.

        A held module's file is never re-fetched and never compiled, so a
        misfiling would otherwise surface only when somebody promoted it --
        which is exactly when a maintainer has least appetite for it.
        """
        self.assertEqual([], update_bundled_mibs.misfiled(mibs.manifest()))

    def testAHeldModuleIsNotOnTheCompilersSearchPath(self):
        """``future/`` is held, so no compile may resolve against it."""
        searchable = compiler_module.bundled_mib_names("pysmi.mibs.asn1")

        self.assertEqual(set(), searchable & mibs.future())
        self.assertEqual(searchable, mibs.bundled())


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

    #: The ASN.1 the repository holds, both tiers. ``successors_reviewed`` is
    #: history and may name a module pysmi has no copy of at all -- RFC1284-MIB
    #: records RFC1398-MIB, which later RFCs replaced in turn -- so a name is
    #: checked against the sources before it is compiled, rather than compiled
    #: and the failure swallowed.
    #:
    #: Held modules are read here even though nothing else reads them: what
    #: this asserts is whether the manifest's supersession claims are true of
    #: the text, and that question does not change with the directory a module
    #: sits in. Deferring one must not quietly stop its claim being checked.
    BUNDLED = frozenset(
        path.name
        for directory in (update_bundled_mibs.DEST, update_bundled_mibs.FUTURE)
        for path in update_bundled_mibs.held_files(directory)
    )

    @classmethod
    def setUpClass(cls):
        """Stage both tiers with pysmi's repairs applied.

        The tree holds the publisher's text, and four of these modules do not
        parse as published -- that is what their patch is for. The repairs go
        on when a distribution is built, so a claim about "the text" is a claim
        about the repaired text, and that is what is compiled here.
        """
        cls.repaired = Path(tempfile.mkdtemp(prefix="pysmi-manifest-asn1-"))
        patches = bundled_patches()

        for directory in (update_bundled_mibs.DEST, update_bundled_mibs.FUTURE):
            for source in update_bundled_mibs.held_files(directory):
                text = source.read_text(encoding="utf-8", errors="replace")
                text, status = patches.apply(source.name, text)

                if status not in ("", APPLIED):
                    raise AssertionError(
                        f"{source.name}: patch did not apply ({status})"
                    )

                (cls.repaired / source.name).write_text(
                    text, encoding="utf-8", newline=""
                )

    @classmethod
    def tearDownClass(cls):
        """Drop the staging directory."""
        shutil.rmtree(cls.repaired, ignore_errors=True)

    @classmethod
    def _oids(cls, name, compiler, documents):
        """Every OID *name* declares, or ``None`` when the bundle has no source.

        The two answers have to stay distinguishable. A bundled module that
        compiles to nothing is a failure, not an empty module, and returning an
        empty set for it would make the assertion below pass without comparing
        anything: ``len(shared)`` would be 0, and so would ``len(mine)``, so the
        zero-overlap branch would accept it. Only a genuinely unbundled module
        is skippable, and it says so with ``None``.
        """
        if name not in cls.BUNDLED:
            return None

        if name not in documents:
            compiler.compile(name, noDeps=True, rebuild=True)

        if name not in documents:
            raise AssertionError(
                f"{name} is bundled but produced no document -- the compile "
                f"failed, and treating that as an empty module would make this "
                f"test pass without comparing anything"
            )

        document = documents[name]

        return {
            body["oid"]
            for symbol, body in document.items()
            if symbol not in ("meta", "imports")
            and isinstance(body, dict)
            and body.get("oid")
        }

    def testASuccessorCoversAllOfItsPredecessorsOidsOrNoneOfThem(self):
        """Compare each recorded pair by the OIDs each module declares."""
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
        compiler.add_sources(FileReader(str(self.repaired)))

        for name, entry in sorted(mibs.manifest().items()):
            for successor in sorted(set(entry.get("successors_reviewed", {}).values())):
                mine = self._oids(name, compiler, documents)
                theirs = self._oids(successor, compiler, documents)
                if theirs is None:
                    continue  # a successor the bundle does not carry

                with self.subTest(module=name, successor=successor):
                    self.assertIsNotNone(
                        mine, f"{name} is in the manifest but not in the bundle"
                    )
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
