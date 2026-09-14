#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Which files you need in order to load a module.

``core.db``'s ``import`` table holds the direct edges. The question consumers
arrive with is the closure, and three of them arrive with it: a page answering
"the files you need", anyone packaging a subset for an air-gapped install, and
pysnmp deciding what to preload. The build resolves every one of those edges in
order to compile, so it is the build that should write the answer down rather
than every reader re-walking a table for it.

These pin the two decisions the emitter makes rather than leaving to the
caller -- a module is in its own closure, and a dependency the corpus does not
hold is recorded rather than dropped -- and that a cycle terminates.
pysnmp/pysmi#280.
"""

import json
import unittest

from pysmi.corpus.closure import (
    SCHEMA_VERSION,
    Closure,
    as_document,
    closures,
    counts,
    imported,
    render_closure,
)


def document(*imports):
    """A jsondoc importing one symbol from each module named."""
    return {
        "imports": {
            "class": "imports",
            **{source: [f"sym{index}"] for index, source in enumerate(imports)},
        },
        "anchor": {"class": "moduleidentity", "oid": "1.3.6.1.4.1.99"},
    }


def corpus(**modules):
    """``(module, jsondoc, tier, rfc)`` rows, as read_documents yields them."""
    return [(name, doc, 0, 0) for name, doc in modules.items()]


class ImportedTestCase(unittest.TestCase):
    """Reading the IMPORTS clause of one document."""

    def testTheClassKeyIsNotAModule(self):
        """It says what kind of clause it is, not where a symbol came from."""
        self.assertEqual(["SNMPv2-SMI"], list(imported(document("SNMPv2-SMI"))))

    def testADocumentWithNoImportsImportsNothing(self):
        self.assertEqual([], list(imported({"anchor": {}})))

    def testAMalformedImportsBlockIsNotRead(self):
        """A document that will not parse is skipped upstream; be quiet here."""
        self.assertEqual([], list(imported({"imports": "not a mapping"})))


class ClosureTestCase(unittest.TestCase):
    """What one module needs."""

    def testAModuleIsInItsOwnClosure(self):
        """Which makes the artifact directly usable as a file list."""
        found = closures(corpus(**{"A-MIB": document()}))

        self.assertEqual(Closure(("A-MIB",), ()), found["A-MIB"])

    def testTheClosureIsTransitive(self):
        """The point of it: the edges are already published, the walk is not."""
        found = closures(
            corpus(
                **{
                    "A-MIB": document("B-MIB"),
                    "B-MIB": document("C-MIB"),
                    "C-MIB": document(),
                }
            )
        )

        self.assertEqual(("A-MIB", "B-MIB", "C-MIB"), found["A-MIB"].files)
        self.assertEqual(("B-MIB", "C-MIB"), found["B-MIB"].files)
        self.assertEqual(("C-MIB",), found["C-MIB"].files)

    def testFilesAreSorted(self):
        """A published artifact that reordered between builds would churn."""
        found = closures(
            corpus(
                **{
                    "Z-MIB": document("M-MIB", "A-MIB"),
                    "M-MIB": document(),
                    "A-MIB": document(),
                }
            )
        )

        self.assertEqual(("A-MIB", "M-MIB", "Z-MIB"), found["Z-MIB"].files)

    def testACycleTerminates(self):
        """SNMPv2-SMI and SNMPv2-TC import each other in the real bundle.

        A closure under a cycle is a fixpoint rather than something one
        post-order pass computes, which is why the walk is breadth-first from
        each module rather than a memoised recursion.
        """
        found = closures(
            corpus(**{"A-MIB": document("B-MIB"), "B-MIB": document("A-MIB")})
        )

        self.assertEqual(("A-MIB", "B-MIB"), found["A-MIB"].files)
        self.assertEqual(("A-MIB", "B-MIB"), found["B-MIB"].files)

    def testAModuleImportingItselfIsNotCountedTwice(self):
        found = closures(corpus(**{"A-MIB": document("A-MIB")}))

        self.assertEqual(("A-MIB",), found["A-MIB"].files)


class MissingTestCase(unittest.TestCase):
    """A dependency the corpus does not hold is recorded, not dropped."""

    def testAnAbsentDependencyIsNamed(self):
        """ "Needs nothing else" and "something it needs is not here" differ."""
        found = closures(corpus(**{"A-MIB": document("GONE-MIB")}))

        self.assertEqual(("A-MIB",), found["A-MIB"].files)
        self.assertEqual(("GONE-MIB",), found["A-MIB"].missing)

    def testAnAbsentDependencyIsNamedHoweverDeepItIs(self):
        """A hole below a module is a hole for it: it still cannot be loaded."""
        found = closures(
            corpus(**{"A-MIB": document("B-MIB"), "B-MIB": document("GONE-MIB")})
        )

        self.assertEqual(("GONE-MIB",), found["A-MIB"].missing)

    def testAnAbsentDependencyIsNotInTheFileList(self):
        """The file list is files; naming one that is not there would be a lie."""
        found = closures(corpus(**{"A-MIB": document("GONE-MIB")}))

        self.assertNotIn("GONE-MIB", found["A-MIB"].files)

    def testACompleteClosureNamesNothingMissing(self):
        found = closures(corpus(**{"A-MIB": document()}))

        self.assertEqual((), found["A-MIB"].missing)


class DocumentTestCase(unittest.TestCase):
    """The artifact as it is written."""

    def testTheMetaBlockCountsWhatIsThere(self):
        written = as_document(
            closures(corpus(**{"A-MIB": document("GONE-MIB"), "B-MIB": document()}))
        )

        self.assertEqual(SCHEMA_VERSION, written["meta"]["schema"])
        self.assertEqual(2, written["meta"]["modules"])
        self.assertEqual(1, written["meta"]["incomplete"])

    def testEveryModuleCarriesBothLists(self):
        """A consumer reading it never has to ask whether a key is there."""
        written = as_document(closures(corpus(**{"A-MIB": document()})))

        self.assertEqual(
            {"files": ["A-MIB"], "missing": []}, written["closure"]["A-MIB"]
        )


class RenderTestCase(unittest.TestCase):
    """The bytes the driver writes, and what the build report is told."""

    def testTheArtifactIsWrittenCompactly(self):
        """Generated, and nobody reads it by eye. pysnmp/pysmi#283."""
        text = render_closure(closures(corpus(**{"A-MIB": document()})))

        self.assertNotIn(", ", text)
        self.assertEqual(1, text.count("\n"))
        self.assertTrue(text.endswith("\n"))

    def testTheRenderedArtifactReadsBackAsTheDocument(self):
        found = closures(corpus(**{"A-MIB": document("GONE-MIB")}))

        self.assertEqual(as_document(found), json.loads(render_closure(found)))

    def testTheSameCorpusRendersTheSameBytesTwice(self):
        """Every corpus artifact but the report is byte-reproducible."""
        rows = corpus(**{"A-MIB": document("B-MIB"), "B-MIB": document()})

        self.assertEqual(render_closure(closures(rows)), render_closure(closures(rows)))

    def testTheCountsAreWhatTheReportCarries(self):
        found = closures(corpus(**{"A-MIB": document("GONE-MIB"), "B-MIB": document()}))

        self.assertEqual({"modules": 2, "incomplete": 1}, counts(found))


if __name__ == "__main__":
    unittest.main()
