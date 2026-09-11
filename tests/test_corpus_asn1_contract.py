#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The shape of the ASN.1 tree ``--emit=asn1`` writes.

The names in that tree are a live contract, not an implementation detail.
pysnmp resolves a dependency by substituting a module name into a source
template, and splunk-connect-for-snmp runs exactly that path in production:
``addMibCompiler()`` against ``https://.../asn1/@mib@``, compiling ASN.1 per
MIB on demand. A file named for the source it came from rather than for the
module it defines, or one carrying an extension, is a 404 in that runtime.

pysmi asserts what a jsondoc holds, what ``core.db`` holds and what an index
answers. It did not assert the shape of this tree -- pysnmp/mibs did, in
``tests/artifact-contract.sh``, downstream of the tool that writes it. See
pysnmp/pysmi#264. The round trip that runs the substitution for real lives in
the consumer layer, which is the only file allowed to reach the runtime.
"""

import csv
import os
import shutil
import sqlite3
import tempfile
import unittest

from pysmi.corpus.driver import CorpusDriver, CorpusOutputs
from pysmi.corpus.namespace import Namespace

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
    DESCRIPTION  "conventions the vendor modules import"
    ::= { enterprises 40000 }

TestString ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "a string carrying a display hint"
    SYNTAX       OCTET STRING (SIZE (0..255))
END
"""

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
    DESCRIPTION  "imports a convention from another module in the tree"
    ::= { enterprises 40001 }

vendorAName OBJECT-TYPE
    SYNTAX      TestString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "a name"
    ::= { vendorAMib 1 }
END
"""

VENDOR_B_MIB = """\
VENDOR-B-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, enterprises
        FROM SNMPv2-SMI;

vendorBMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "held in a file named a different case, with an extension"
    ::= { enterprises 40002 }
END
"""

#: Two modules in one file, which the tree has to carry as two names.
PAIR_MIBS = """\
PAIR-ONE-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, enterprises
        FROM SNMPv2-SMI;

pairOneMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "the first module in a file holding two"
    ::= { enterprises 40003 }
END

PAIR-TWO-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, enterprises
        FROM SNMPv2-SMI;

pairTwoMib MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "the second module in a file holding two"
    ::= { enterprises 40004 }
END
"""

BROKEN_MIB = """\
BROKEN-MIB DEFINITIONS ::= BEGIN
    this is not SMI
END
"""

#: Every module the fixture publishes, as the tree must name them: the SMI
#: name, upper case, no extension, whatever the file holding it was called.
PUBLISHED = (
    "PAIR-ONE-MIB",
    "PAIR-TWO-MIB",
    "TEST-TC-MIB",
    "VENDOR-A-MIB",
    "VENDOR-B-MIB",
)


def sources(root):
    """The fixture source tree, with file names that are not module names."""
    base = os.path.join(root, "src", "base")
    vendor = os.path.join(root, "src", "vendor")
    os.makedirs(base)
    os.makedirs(vendor)

    # Named for nothing in particular.
    _write(os.path.join(base, "tc.mib"), TC_MIB)
    # Named for the module it holds, which is the ordinary case.
    _write(os.path.join(vendor, "VENDOR-A-MIB"), VENDOR_A_MIB)
    # A case variant of the module name, with an extension.
    _write(os.path.join(vendor, "vendor-b-mib.txt"), VENDOR_B_MIB)
    # Two modules, neither of which the file is named for.
    _write(os.path.join(vendor, "pair.txt"), PAIR_MIBS)

    return base, vendor


class Asn1TreeTestCase(unittest.TestCase):
    """What a build writes into ``asn1/``.

    The corpus here compiles clean, which is what lets the trees be compared
    for equality. A corpus carrying a module that does not compile is the
    other case, and :py:class:`DefectiveModuleTestCase` states it.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        base, vendor = sources(cls.root)
        cls.out = _build(cls.root, base, vendor)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def testEveryFileIsNamedForTheModuleItDefines(self):
        self.assertEqual(sorted(PUBLISHED), sorted(os.listdir(self.tree)))

    def testNoFileCarriesAnExtension(self):
        # ``@mib@`` is substituted with a bare module name, so a suffix of
        # any kind makes the file unreachable through the template.
        for name in os.listdir(self.tree):
            with self.subTest(file=name):
                self.assertNotIn(".", name)

    def testAFileNameIsNotWhatNamesTheModule(self):
        # tc.mib holds TEST-TC-MIB and vendor-b-mib.txt holds VENDOR-B-MIB.
        # Neither file name reaches the tree, in its own case or any other.
        self.assertIn("TEST-TC-MIB", os.listdir(self.tree))
        self.assertIn("VENDOR-B-MIB", os.listdir(self.tree))

        for name in os.listdir(self.tree):
            with self.subTest(file=name):
                self.assertEqual(name.upper(), name)

    def testASourceFileHoldingTwoModulesIsPublishedUnderBothNames(self):
        # One file per module name, and each one resolves to text defining
        # the module asked for -- which for a file holding two means the
        # same text under two names, not one name for both modules.
        for module in ("PAIR-ONE-MIB", "PAIR-TWO-MIB"):
            with (
                self.subTest(module=module),
                open(os.path.join(self.tree, module), encoding="utf-8") as fileObj,
            ):
                self.assertIn(f"{module} DEFINITIONS ::= BEGIN", fileObj.read())

    def testTheTreeCarriesTheTextTheModuleWasCompiledFrom(self):
        with open(os.path.join(self.tree, "VENDOR-A-MIB"), encoding="utf-8") as fileObj:
            self.assertEqual(VENDOR_A_MIB, fileObj.read())

    def testTheIndexNamesNothingTheTreeDoesNotCarry(self):
        self.assertEqual(sorted(PUBLISHED), sorted(self._indexed("index-v2.csv")))
        self.assertEqual(sorted(PUBLISHED), sorted(self._indexed("index.csv")))

    def testTheDatabaseNamesNothingTheTreeDoesNotCarry(self):
        connection = sqlite3.connect(os.path.join(self.out, "core.db"))

        try:
            names = sorted(x[0] for x in connection.execute("SELECT name FROM module"))

        finally:
            connection.close()

        self.assertEqual(sorted(PUBLISHED), names)

    def testAModuleReachedOnlyThroughResolutionIsInNoTreeAtAll(self):
        # The bundled modules are declared unpublished, so the corpus
        # resolves SNMPv2-SMI and carries nothing of it.
        self.assertNotIn("SNMPv2-SMI", os.listdir(self.tree))
        self.assertNotIn("SNMPv2-SMI", self._indexed("index-v2.csv"))

    @property
    def tree(self):
        """The emitted ASN.1 tree."""
        return os.path.join(self.out, "asn1")

    def _indexed(self, artifact):
        """The modules an emitted index names."""
        with open(os.path.join(self.out, artifact), encoding="utf-8") as fileObj:
            return {module for module, _oid in csv.reader(fileObj)}


class DefectiveModuleTestCase(unittest.TestCase):
    """A module the corpus holds but cannot compile.

    It is staged, because the tree is what the corpus publishes its sources
    as and a consumer asking for it should get the text rather than a 404.
    It is not indexed, because the index is a projection of what compiled.
    The trees therefore agree for a clean corpus and the ASN.1 tree is the
    larger of the two for one carrying a defective module.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = tempfile.mkdtemp()
        base, vendor = sources(cls.root)
        _write(os.path.join(vendor, "BROKEN-MIB"), BROKEN_MIB)
        cls.out = _build(cls.root, base, vendor)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.root, ignore_errors=True)

    def testItIsPublishedAsAsn1(self):
        self.assertIn("BROKEN-MIB", os.listdir(os.path.join(self.out, "asn1")))

    def testItIsTheOnlyThingTheIndexDoesNotName(self):
        with open(os.path.join(self.out, "index-v2.csv"), encoding="utf-8") as fileObj:
            indexed = {module for module, _oid in csv.reader(fileObj)}

        staged = set(os.listdir(os.path.join(self.out, "asn1")))

        self.assertEqual({"BROKEN-MIB"}, staged - indexed)
        self.assertEqual(set(), indexed - staged)


def _write(path, text):
    """One fixture file on disk."""
    with open(path, "w", encoding="utf-8", newline="") as fileObj:
        fileObj.write(text)


def _build(root, base, vendor):
    """A corpus over the fixture sources, returning the output directory."""
    directory = os.path.join(root, "output")

    outputs = CorpusOutputs(
        asn1=os.path.join(directory, "asn1"),
        json=os.path.join(directory, "json"),
        index=os.path.join(directory, "index.csv"),
        ranked_index=os.path.join(directory, "index-v2.csv"),
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
            Namespace(name="base", source=base, tier="standard"),
            Namespace(name="vendor", source=vendor, tier="vendor"),
        ],
        outputs,
    ).run()

    return directory


if __name__ == "__main__":
    unittest.main()
