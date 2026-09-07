#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A module's hash follows its model, not its formatting or its producer.

Duplicate detection, shadow warnings and subset-build stability all compare
module hashes, so the properties asserted here are what those features rest on:

* reformatting a MIB does not change its hash
* changing anything the model carries does change it
* a subset filtered from a full build matches that build, module for module
* the pysmi version that produced a document does not enter the hash

The last is why ``meta`` is excluded, and it is the difference between this and
the source digest in ``meta.comments``, which covers raw ASN.1 bytes and moves
whenever whitespace does.

See pysnmp/pysmi#180.
"""

import json
import sys
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.codegen.normalized import (
    NORMALIZATION_VERSION,
    TEXT_FIELDS,
    canonical_form,
    content_hash,
    module_hashes,
    structure_hash,
)
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
from tests.harness import render_json

#: Hashes pinned for a fixed module set, so a change to the normalization rule
#: or to what the model carries fails here rather than silently moving every
#: hash a consumer has stored. Regenerating these is a deliberate act: it means
#: NORMALIZATION_VERSION should be bumped, or a model change was made.
PINNED = {
    "SNMPv2-MIB": (
        "614f6b29c2c409da42540b59e2706b13271ceb64880acf819ae2ce47e1d7f106",
        "f74515e6e030f4014d3873ac2412cff35920f2f0d52f0e14058d8946afc91727",
    ),
    "IF-MIB": (
        "8e0892c6d87fcdfee9b9fd4ca7f03277af6883316f54c54d56ee5c631fee38de",
        "13a46fcf5562f33c9f7df44d169da0a439ee3e97208a623f96f38b2849040e43",
    ),
    "SNMPv2-TC": (
        "bc44ccc946853c9e887d1a10cf8c91688d757b7c476f9d651a43649aa50fe82b",
        "2d6887ae34e6787c72e8e5fa702514b20838ebc14fa8b69205b2434893f53cff",
    ),
    "RFC1213-MIB": (
        "0789d0679036e9253148c2d811a0c4f54c96985e7de0496e698b7c093289e4a2",
        "300822da21ecc8ec044a2c1ac6ce457d5d42521263fa12d9c3c054e4489f9d6d",
    ),
    "HOST-RESOURCES-MIB": (
        "3e701da9149f1e488323abe7f9268b672608b91b3f5196e72eb37d4d53472c8a",
        "92ea97a58b3323546685bc895b66813ab6c0cf16c9fc84536e03985ef0582621",
    ),
    "DISMAN-EVENT-MIB": (
        "d781256af8adce81bd2d4536f4890164133243f202c422dbc76401aad0e4806c",
        "d706a1703ce865b07c871d5d0528329c248db07cd4e3fcdd693ea1a3e976538c",
    ),
}

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32, MODULE-IDENTITY
        FROM SNMPv2-SMI;

testMib MODULE-IDENTITY
    LAST-UPDATED "200001010000Z"
    ORGANIZATION "Test"
    CONTACT-INFO "test@example.com"
    DESCRIPTION  "A module."
    ::= { 1 3 1 }

testObject OBJECT-TYPE
    SYNTAX      Integer32 (1..100)
    UNITS       "packets"
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { testMib 1 }

END
"""


def build(*modules, genTexts=True):
    """Compile *modules* from the bundled ASN.1 into decoded documents."""
    documents = {}

    compiler = MibCompiler(
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
    compiler.compile(*modules, noDeps=False, genTexts=genTexts, rebuild=True)

    return documents


class FormattingInsensitivityTestCase(unittest.TestCase):
    """How the source was written must not reach the hash."""

    def testReindentingDoesNotChangeTheHash(self):
        reindented = MIB.replace("    ", "        ")

        self.assertEqual(
            content_hash(render_json(MIB, genTexts=True)),
            content_hash(render_json(reindented, genTexts=True)),
        )

    def testCommentsDoNotChangeTheHash(self):
        commented = MIB.replace(
            "testObject OBJECT-TYPE",
            "-- a comment the model does not carry\ntestObject OBJECT-TYPE",
        )

        self.assertEqual(
            content_hash(render_json(MIB, genTexts=True)),
            content_hash(render_json(commented, genTexts=True)),
        )

    def testWhitespaceInsideAClauseDoesNotChangeTheHash(self):
        """A space the parser discards is not a model difference."""
        spaced = MIB.replace("Integer32 (1..100)", "Integer32 (1..100) ")

        self.assertEqual(
            content_hash(render_json(MIB, genTexts=True)),
            content_hash(render_json(spaced, genTexts=True)),
        )

    def testLineEndingsDoNotChangeTheHash(self):
        crlf = MIB.replace("\n", "\r\n")

        self.assertEqual(
            content_hash(render_json(MIB, genTexts=True)),
            content_hash(render_json(crlf, genTexts=True)),
        )


class ModelSensitivityTestCase(unittest.TestCase):
    """Anything the model carries must reach the hash."""

    def setUp(self):
        self.baseline = content_hash(render_json(MIB, genTexts=True))

    def assertChangesHash(self, mutated):
        self.assertNotEqual(
            self.baseline, content_hash(render_json(mutated, genTexts=True))
        )

    def testAConstraintChangeIsVisible(self):
        self.assertChangesHash(MIB.replace("(1..100)", "(1..200)"))

    def testAMaxAccessChangeIsVisible(self):
        self.assertChangesHash(MIB.replace("read-only", "read-write"))

    def testAStatusChangeIsVisible(self):
        self.assertChangesHash(
            MIB.replace("STATUS      current", "STATUS      obsolete")
        )

    def testAUnitsChangeIsVisible(self):
        """UNITS is machine-readable, so it is structure rather than prose."""
        self.assertChangesHash(MIB.replace('"packets"', '"octets"'))

    def testAnOidChangeIsVisible(self):
        self.assertChangesHash(MIB.replace("::= { testMib 1 }", "::= { testMib 2 }"))

    def testDroppingAConstraintIsVisible(self):
        self.assertChangesHash(
            MIB.replace("SYNTAX      Integer32 (1..100)", "SYNTAX      Integer32")
        )

    def testADescriptionChangeIsVisibleInContentOnly(self):
        """Prose moves the content hash and not the structural one."""
        mutated = render_json(
            MIB.replace('"An object."', '"Another object."'), genTexts=True
        )
        original = render_json(MIB, genTexts=True)

        self.assertNotEqual(content_hash(original), content_hash(mutated))
        self.assertEqual(structure_hash(original), structure_hash(mutated))


class CanonicalFormTestCase(unittest.TestCase):
    """The serialization rules a non-pysmi implementation has to match."""

    def testMetaIsExcluded(self):
        """The producing pysmi version must not reach the hash."""
        document = render_json(MIB, genTexts=True)
        altered = dict(document)
        altered["meta"] = {"schema": 1, "comments": ["Produced by pysmi-99.0.0"]}

        self.assertEqual(content_hash(document), content_hash(altered))

    def testKeyOrderIsNotSignificant(self):
        """Two documents differing only in key order hash the same."""
        document = render_json(MIB, genTexts=True)
        reordered = dict(reversed(list(document.items())))

        self.assertEqual(content_hash(document), content_hash(reordered))

    def testArrayOrderIsSignificant(self):
        """INDEX and revision order mean something, so they are not sorted."""
        document = render_json(MIB, genTexts=True)
        mutated = json.loads(json.dumps(document))
        mutated["imports"]["SNMPv2-SMI"] = list(
            reversed(mutated["imports"]["SNMPv2-SMI"])
        )

        self.assertNotEqual(content_hash(document), content_hash(mutated))

    def testTheAlgorithmVersionIsInTheHashedBytes(self):
        form = canonical_form(render_json(MIB, genTexts=True))

        self.assertTrue(
            form.startswith(f"pysmi-normalized-v{NORMALIZATION_VERSION}\n".encode())
        )

    def testCanonicalFormHasNoInsignificantWhitespace(self):
        form = canonical_form(render_json(MIB, genTexts=True))
        body = form.split(b"\n", 1)[1]

        self.assertNotIn(b", ", body)
        self.assertNotIn(b": ", body)

    def testStructuralFormDropsEveryTextField(self):
        body = canonical_form(render_json(MIB, genTexts=True), includeTexts=False)

        for field in TEXT_FIELDS:
            self.assertNotIn(f'"{field}":'.encode(), body)

    def testModuleHashesCarryTheAlgorithmVersion(self):
        """A hash without the algorithm that produced it compares to nothing."""
        hashes = module_hashes(render_json(MIB, genTexts=True))

        self.assertEqual(hashes["normalization"], NORMALIZATION_VERSION)
        self.assertEqual(
            hashes["content"], content_hash(render_json(MIB, genTexts=True))
        )
        self.assertEqual(
            hashes["structure"], structure_hash(render_json(MIB, genTexts=True))
        )


class SubsetStabilityTestCase(unittest.TestCase):
    """A module's hash does not depend on what was compiled beside it.

    This is what makes a slim corpus a filter over a full one rather than a
    rebuild: the same module in both must carry the same hash, or every subset
    registers as a shadow of the full corpus.
    """

    def testAModuleHashesTheSameAloneAndInABatch(self):
        alone = build("IF-MIB")
        batch = build("IF-MIB", "SNMPv2-MIB", "HOST-RESOURCES-MIB", "DISMAN-EVENT-MIB")

        for name in sorted(set(alone) & set(batch)):
            with self.subTest(module=name):
                self.assertEqual(
                    content_hash(alone[name]),
                    content_hash(batch[name]),
                )

    def testRecompilingIsStable(self):
        first = build("IF-MIB", "SNMPv2-MIB")
        second = build("IF-MIB", "SNMPv2-MIB")

        for name in sorted(first):
            with self.subTest(module=name):
                self.assertEqual(content_hash(first[name]), content_hash(second[name]))


class PinnedHashTestCase(unittest.TestCase):
    """Hashes for a fixed module set do not move without a deliberate change."""

    @classmethod
    def setUpClass(cls):
        cls.documents = build(*PINNED, genTexts=True)

    def testPinnedHashesHaveNotMoved(self):
        for name, (content, structure) in sorted(PINNED.items()):
            with self.subTest(module=name):
                self.assertEqual(content_hash(self.documents[name]), content)
                self.assertEqual(structure_hash(self.documents[name]), structure)


class TextModeTestCase(unittest.TestCase):
    """The structural hash is not yet mode-independent, and this records why."""

    def testStructuralHashDiffersBetweenTextModes(self):
        """Two open defects make a no-texts document structurally lossy.

        The structural hash is *defined* to be equal across text modes -- prose
        is the only thing that should differ. It is not, because a no-texts
        document loses MODULE-COMPLIANCE refinement entries entirely
        (pysnmp/pysmi#190) and loses ``lastupdated`` (pysnmp/pysmi#191), both of
        which are structure rather than prose.

        This test asserts the current, wrong behaviour deliberately. When either
        defect is fixed it fails, which is the signal to check whether the
        remaining difference is gone and to invert this into an equality.
        """
        with_texts = build("SNMPv2-MIB", genTexts=True)["SNMPv2-MIB"]
        without_texts = build("SNMPv2-MIB", genTexts=False)["SNMPv2-MIB"]

        self.assertNotEqual(
            structure_hash(with_texts),
            structure_hash(without_texts),
            "structural hashes now agree across text modes -- if pysnmp/pysmi#190 "
            "and pysnmp/pysmi#191 are fixed, invert this assertion",
        )

    def testContentHashDiffersBetweenTextModes(self):
        """Expected and permanent: prose is content, so omitting it changes it."""
        with_texts = build("IF-MIB", genTexts=True)["IF-MIB"]
        without_texts = build("IF-MIB", genTexts=False)["IF-MIB"]

        self.assertNotEqual(content_hash(with_texts), content_hash(without_texts))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
