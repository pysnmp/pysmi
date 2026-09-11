#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The corpus JSON is compact, and the same bytes whatever wrote it.

:py:mod:`pysmi.jsonio` writes ``json/`` and the JSON index compactly, and
takes a faster implementation when one is installed. A corpus build is
fingerprinted byte for byte, so the second of those must not be visible in the
first: a build with ``pysmi[fast]`` and one without have to produce identical
output, or the reproducibility :py:mod:`pysmi.corpus.driver` opens on is gone
and a downstream agreement check starts reporting differences that are not
differences.

That is a property to assert rather than to intend, so it is asserted here
over every document the bundled corpus produces -- 200-odd real modules --
rather than over a fixture chosen to agree. pysnmp/pysmi#283.
"""

import json
import pathlib
import shutil
import sys
import unittest

from hatch_build import patch_asn1
from pysmi import jsonio
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.writer import CallbackWriter
from scripts.update_bundled_mibs import bundled

ROOT = pathlib.Path(__file__).resolve().parent.parent

#: Every document a compile of the bundle emits, by module name. Built once:
#: it is the whole bundled corpus, and nothing here writes to it.
DOCUMENTS: dict[str, str] = {}

REPAIRED: pathlib.Path


def setUpModule():
    """Compile the bundle the distribution ships and keep every document."""
    global REPAIRED

    REPAIRED = patch_asn1(ROOT)

    compiler = MibCompiler(
        SmiV1CompatParser(),
        JsonCodeGen(),
        CallbackWriter(lambda mibname, data, *_: DOCUMENTS.__setitem__(mibname, data)),
        useBundledMibs=False,
    )
    compiler.add_sources(FileReader(str(REPAIRED)))

    limit = sys.getrecursionlimit()
    sys.setrecursionlimit(20000)

    try:
        compiler.compile(*sorted(bundled()), ignoreErrors=True, genTexts=True)

    finally:
        sys.setrecursionlimit(limit)


def tearDownModule():
    """Drop the staging directory."""
    shutil.rmtree(REPAIRED, ignore_errors=True)


class ImplementationAgreementTestCase(unittest.TestCase):
    """Which implementation is installed must not change a published byte."""

    def testTheBundleProducedDocumentsToCompare(self):
        """A silently empty corpus would make every test below vacuous."""
        self.assertGreater(len(DOCUMENTS), 150)

    def testEveryImplementationWritesTheSameBytes(self):
        """The reproducibility property, over a real corpus.

        Every encoder pysmi knows about is compared against the standard
        library, which is the reference. An implementation that is not
        installed is not in ENCODERS and is not compared -- the dev
        dependencies carry both so that this is not quietly a no-op in CI.
        """
        for mibname, document in sorted(DOCUMENTS.items()):
            value = json.loads(document)
            reference = jsonio.ENCODERS["json"](value)

            for name, encoder in sorted(jsonio.ENCODERS.items()):
                with self.subTest(mib=mibname, implementation=name):
                    self.assertEqual(reference, encoder(value))

    def testTheDocumentsAsWrittenAreTheReferenceBytes(self):
        """Not merely that the encoders agree -- that the build wrote those bytes.

        This is the assertion that fails if dumps() ever starts choosing by
        something other than what every implementation would have written.
        """
        for mibname, document in sorted(DOCUMENTS.items()):
            with self.subTest(mib=mibname):
                self.assertEqual(
                    jsonio.ENCODERS["json"](json.loads(document)), document
                )

    def testEveryImplementationReadsWhatAnyOfThemWrote(self):
        """A document is a document, whoever is installed to read it."""
        for mibname, document in sorted(DOCUMENTS.items()):
            expected = json.loads(document)

            for name, decoder in sorted(jsonio.DECODERS.items()):
                with self.subTest(mib=mibname, implementation=name):
                    self.assertEqual(expected, decoder(document))

    def testMoreThanTheStandardLibraryIsBeingCompared(self):
        """The dev dependencies carry orjson and msgspec, so both are here.

        Without this the two tests above pass on a machine with neither
        installed while asserting nothing at all, which is the failure mode
        worth naming out loud.
        """
        self.assertEqual({"json", "msgspec", "orjson"}, set(jsonio.ENCODERS))
        self.assertEqual(set(jsonio.ENCODERS), set(jsonio.DECODERS))

    def testTheCorpusCarriesNonAsciiForThemToDisagreeOver(self):
        """ensure_ascii=False is the setting all three can agree on.

        Neither orjson nor msgspec can escape a non-ASCII character, so the
        agreement above is only meaningful if some document has one in it.
        """
        self.assertTrue(
            any(not document.isascii() for document in DOCUMENTS.values()),
            "no bundled document carries a non-ASCII character",
        )


class CompactTestCase(unittest.TestCase):
    """The published tree is generated, and nobody reads it by eye."""

    def testDocumentsAreWrittenOnOneLine(self):
        """Indentation is about 30% of json/ on disk, and buys nothing here."""
        for mibname, document in sorted(DOCUMENTS.items()):
            with self.subTest(mib=mibname):
                self.assertNotIn("\n", document)

    def testSeparatorsCarryNoSpaces(self):
        """The other half of compact, and the half json.dumps does by default."""
        self.assertEqual('{"a":1,"b":[1,2]}', jsonio.dumps({"a": 1, "b": [1, 2]}))

    def testNonAsciiIsWrittenAsItself(self):
        self.assertEqual('{"a":"café"}', jsonio.dumps({"a": "café"}))

    def testAValueAFastEncoderRefusesIsStillWritten(self):
        """A non-string key is the usual one, and the stdlib coerces it.

        An installed extra must not turn a document into an error, so dumps()
        falls back rather than propagating what orjson thinks of the value.
        """
        self.assertEqual('{"1":"a"}', jsonio.dumps({1: "a"}))

    def testTheImplementationInUseIsOneItKnowsAbout(self):
        self.assertIn(jsonio.IMPLEMENTATION, jsonio.PREFERENCE)
        self.assertIn(jsonio.IMPLEMENTATION, jsonio.ENCODERS)


class HumanFacingJsonTestCase(unittest.TestCase):
    """What a person reads stays indented; this is about generated artifacts."""

    def testTheBuildReportIsIndented(self):
        """report.json is read by somebody looking at a failed build."""
        source = (ROOT / "pysmi" / "corpus" / "driver.py").read_text()

        self.assertIn("indent=2", source)

    def testTheConformanceAndPrecedenceVectorsAreIndented(self):
        """Fixtures reviewed in diffs, so a compact one would be unreadable."""
        for module in ("conformance.py", "precedence.py"):
            with self.subTest(module=module):
                source = (ROOT / "pysmi" / "corpus" / module).read_text()

                self.assertIn("indent=2", source)


if __name__ == "__main__":
    unittest.main()
