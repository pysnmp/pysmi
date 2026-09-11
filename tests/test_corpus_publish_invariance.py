#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Unpublishing a namespace changes the output set and nothing else.

``"publish": false`` -- ``--resolve-namespace`` on the command line -- lets a
corpus resolve imports against modules it does not carry, so a publisher can
build a compact corpus for a runtime that already holds the standard modules.
The feature rests on a claim: a module carried by both a full and a compact
build compiles *identically* in both. If it does not, the compact corpus is
quietly a different corpus and the runtime reading it gets different answers
from the one reading the published tree.

That claim was regression-tested downstream, in pysnmp/mibs, against one
specific corpus and on a schedule pysmi does not control. Here it is pinned
where the guarantee is made. See pysnmp/pysmi#261.
"""

import csv
import json
import os
import shutil
import sqlite3
import tempfile
import textwrap
import unittest

from pysmi.codegen.normalized import content_hash
from pysmi.corpus.driver import CorpusDriver, CorpusOutputs
from pysmi.corpus.namespace import Namespace

#: The textual convention the vendor modules resolve against.
TC_MIB = """\
TEST-TC-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, enterprises
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

testTcMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "the namespace a compact corpus resolves against"
    ::= { enterprises 40000 }

TestString ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "a string carrying a display hint"
    SYNTAX       OCTET STRING (SIZE (0..255))
END
"""

#: Imports a textual convention from across the published/unpublished
#: boundary, which is the case the invariance is about.
VENDOR_A_MIB = """\
VENDOR-A-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, enterprises
        FROM SNMPv2-SMI
    TestString
        FROM TEST-TC-MIB;

vendorAMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "imports across the published boundary"
    ::= { enterprises 40001 }

vendorAName OBJECT-TYPE
    SYNTAX      TestString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "syntax resolved from a namespace the compact corpus drops"
    ::= { vendorAMib 1 }
END
"""

#: Imports from a namespace both builds publish, so the intersection covers
#: an ordinary dependency as well as a boundary-crossing one.
VENDOR_B_MIB = """\
VENDOR-B-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    vendorAMib
        FROM VENDOR-A-MIB;

vendorBMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "imports from a published namespace"
    ::= { vendorAMib 9 }

vendorBCount OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "a counter"
    ::= { vendorBMib 1 }
END
"""

#: Anchors on the same arcs TEST-TC-MIB defines. With the standard namespace
#: published it loses them to the higher tier; with it unpublished there is
#: nothing to lose to.
VENDOR_C_MIB = """\
VENDOR-C-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, enterprises
        FROM SNMPv2-SMI;

vendorCMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "registers the arc the standard namespace registers"
    ::= { enterprises 40000 }
END
"""

#: The arc both TEST-TC-MIB and VENDOR-C-MIB register a MODULE-IDENTITY on.
#: The index carries a module's anchors, so this is where the two meet.
COLLIDING_OID = "1.3.6.1.4.1.40000"

VENDOR_MODULES = ("VENDOR-A-MIB", "VENDOR-B-MIB", "VENDOR-C-MIB")


class PublishInvarianceTestCase(unittest.TestCase):
    """The same sources built twice, published and unpublished."""

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()

        base = os.path.join(cls.root, "src", "base")
        vendor = os.path.join(cls.root, "src", "vendor")
        os.makedirs(base)
        os.makedirs(vendor)

        _write(os.path.join(base, "TEST-TC-MIB"), TC_MIB)
        _write(os.path.join(vendor, "VENDOR-A-MIB"), VENDOR_A_MIB)
        _write(os.path.join(vendor, "VENDOR-B-MIB"), VENDOR_B_MIB)
        _write(os.path.join(vendor, "VENDOR-C-MIB"), VENDOR_C_MIB)

        cls.base = base
        cls.vendor = vendor

        cls.full = _build(cls.root, "full", base, vendor, publishBase=True)
        cls.compact = _build(cls.root, "compact", base, vendor, publishBase=False)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def testEveryModuleInBothBuildsHasTheSameContentHash(self):
        # The whole claim, stated over the identity the corpus records per
        # module: unpublishing a namespace subtracts modules from the output
        # and changes nothing about the ones that remain.
        full = _hashes(self.full)
        compact = _hashes(self.compact)

        shared = sorted(set(full) & set(compact))

        self.assertEqual(sorted(VENDOR_MODULES), shared)

        for module in shared:
            self.assertEqual(full[module], compact[module], module)

    def testTheCompactBuildCarriesExactlyWhatItPublishes(self):
        self.assertEqual(
            sorted(VENDOR_MODULES), sorted(os.listdir(_path(self.compact, "asn1")))
        )
        self.assertEqual(
            sorted(f"{x}.json" for x in VENDOR_MODULES),
            sorted(os.listdir(_path(self.compact, "json"))),
        )

    def testTheFullBuildCarriesTheUnpublishedNamespaceToo(self):
        # The other half of the pair: the module is absent from the compact
        # build because the manifest unpublished it, not because it failed.
        self.assertIn("TEST-TC-MIB", os.listdir(_path(self.full, "asn1")))
        self.assertIn("TEST-TC-MIB", _hashes(self.full))

    def testNoUnpublishedModuleLeaksIntoAnyArtifact(self):
        for artifact in ("index.csv", "index-v2.csv", "standard.txt"):
            with open(_path(self.compact, artifact), encoding="utf-8") as fileObj:
                self.assertNotIn("TEST-TC-MIB", fileObj.read(), artifact)

        connection = sqlite3.connect(_path(self.compact, "core.db"))

        try:
            names = {x[0] for x in connection.execute("SELECT name FROM module")}

        finally:
            connection.close()

        self.assertEqual(set(VENDOR_MODULES), names)

    def testStandardTxtNamesOnlyPublishedStandardModules(self):
        # standard.txt is built from the standard-tier namespaces, and the
        # unpublished one is the only standard tier this corpus has.
        with open(_path(self.compact, "standard.txt"), encoding="utf-8") as fileObj:
            self.assertEqual("", fileObj.read())

    def testAnUnpublishedNamespaceNeitherWinsNorLosesTheIndex(self):
        # It is not in the index at all. With the standard namespace
        # published the higher tier owns the colliding OID; without it the
        # vendor module owns it, because nothing else claims it.
        self.assertEqual("TEST-TC-MIB", _index(self.full)[COLLIDING_OID])
        self.assertEqual("VENDOR-C-MIB", _index(self.compact)[COLLIDING_OID])

    def testTheReportRecordsWhichNamespacesWerePublished(self):
        with open(_path(self.compact, "report.json"), encoding="utf-8") as fileObj:
            report = json.load(fileObj)

        published = {x["name"]: x["publish"] for x in report["namespaces"]}

        self.assertFalse(published["base"])
        self.assertTrue(published["vendor"])


def _write(path, text):
    """One fixture module on disk."""
    with open(path, "w", encoding="utf-8", newline="") as fileObj:
        fileObj.write(textwrap.dedent(text))


def _build(root, name, base, vendor, *, publishBase):
    """One corpus build over the fixture sources.

    The bundled modules are a resolution source in both builds, so the only
    thing that differs between them is whether the fixture's own standard
    namespace is published.
    """
    directory = os.path.join(root, name)

    outputs = CorpusOutputs(
        asn1=os.path.join(directory, "asn1"),
        json=os.path.join(directory, "json"),
        index=os.path.join(directory, "index.csv"),
        ranked_index=os.path.join(directory, "index-v2.csv"),
        standard=os.path.join(directory, "standard.txt"),
        core_db=os.path.join(directory, "core.db"),
        report=os.path.join(directory, "report.json"),
    )

    CorpusDriver(
        [
            Namespace(
                name="bundle",
                source="package:pysmi.mibs.asn1",
                tier="standard",
                publish=False,
            ),
            Namespace(name="base", source=base, tier="standard", publish=publishBase),
            Namespace(name="vendor", source=vendor, tier="vendor"),
        ],
        outputs,
    ).run()

    return directory


def _path(directory, artifact):
    """One artifact of a build."""
    return os.path.join(directory, artifact)


def _hashes(directory):
    """Module name to content hash, for every document a build wrote."""
    tree = _path(directory, "json")

    hashes = {}

    for filename in sorted(os.listdir(tree)):
        with open(os.path.join(tree, filename), encoding="utf-8") as fileObj:
            hashes[filename[: -len(".json")]] = content_hash(json.load(fileObj))

    return hashes


def _index(directory):
    """The ranked index as OID to module."""
    with open(_path(directory, "index-v2.csv"), encoding="utf-8") as fileObj:
        return {oid: module for module, oid in csv.reader(fileObj)}


if __name__ == "__main__":
    unittest.main()
