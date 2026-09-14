#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The catalogue of defects, and the page it is published as.

:py:mod:`pysmi.defects` holds the identifiers a patch references;
``docs/source/mib-defects.rst`` is where a reader who followed the link in a
patch file arrives. The two are written by hand and would drift apart
silently, so they are held to the same set of identifiers here.

A patch naming a defect nothing documents is worse than a patch naming none:
the link is the whole point of the identifier. pysnmp/pysmi#279.
"""

import pathlib
import re
import unittest

from pysmi import defects

#: The page the identifiers resolve to.
PAGE = (
    pathlib.Path(__file__).resolve().parent.parent
    / "docs"
    / "source"
    / "mib-defects.rst"
)

#: A Sphinx label, which is what gives an entry the fragment a patch links to.
LABEL = re.compile(r"^\.\. _([a-z0-9-]+):$", re.MULTILINE)


class CatalogueTestCase(unittest.TestCase):
    """What the identifiers themselves have to hold to."""

    def testEveryEntryIsKeyedByItsOwnIdentifier(self):
        """Looking one up by a key that is not its id would be a trap."""
        for key, entry in defects.CATALOGUE.items():
            with self.subTest(defect=key):
                self.assertEqual(key, entry.id)

    def testEveryIdentifierIsShoutedAndHyphenated(self):
        """One spelling, so a patch file and a page anchor cannot disagree."""
        for key in defects.CATALOGUE:
            with self.subTest(defect=key):
                self.assertRegex(key, r"^[A-Z0-9]+(-[A-Z0-9]+)+$")

    def testEverySummaryReadsAsAPredicate(self):
        """A report prints "<MODULE> (<id>: ...)", so the summary is a phrase.

        Sentence case or a full stop would read wrongly wherever it is used.
        """
        for key, entry in defects.CATALOGUE.items():
            with self.subTest(defect=key):
                self.assertTrue(entry.summary)
                self.assertFalse(entry.summary.endswith("."))
                self.assertEqual(entry.summary[0], entry.summary[0].lower())

    def testEveryEntryCitesTheRuleItBreaks(self):
        """A defect is a defect against something, and says against what."""
        for key, entry in defects.CATALOGUE.items():
            with self.subTest(defect=key):
                self.assertRegex(entry.reference, r"^RFC \d+ section ")

    def testRefRefusesAnIdentifierNothingDocuments(self):
        """Writing a link to an empty page is worse than writing no link."""
        with self.assertRaises(KeyError):
            defects.ref("SMI-NO-SUCH-DEFECT")

    def testAnUnknownIdentifierStillHasASummaryLookup(self):
        """A downstream identifier is not an error, it is just not pysmi's."""
        self.assertEqual("", defects.summary("ACME-0001"))

    def testTheUrlIsVersionlessAndAnchored(self):
        """A patch written today has to still point somewhere in five years."""
        self.assertEqual(
            "https://pysnmp.github.io/pysmi/stable/mib-defects.html#smi-invalid-date",
            defects.url("SMI-INVALID-DATE"),
        )


class PublishedCatalogueTestCase(unittest.TestCase):
    """The page a patch's link arrives at."""

    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.labels = set(LABEL.findall(cls.page))

    def testEveryIdentifierHasAnEntryOnThePage(self):
        """Following the link in a patch file has to land somewhere."""
        for key in defects.CATALOGUE:
            with self.subTest(defect=key):
                self.assertIn(defects.anchor(key), self.labels)

    def testThePageDocumentsNothingTheCatalogueDoesNotName(self):
        """An entry no identifier resolves to is an entry nothing can cite."""
        described = {label for label in self.labels if label.startswith("smi-")}

        self.assertEqual({defects.anchor(key) for key in defects.CATALOGUE}, described)

    def testThePageCarriesEachSummaryAndReference(self):
        """The one-line summary is written in two places; keep them the same."""
        for key, entry in defects.CATALOGUE.items():
            with self.subTest(defect=key):
                self.assertIn(entry.summary, self.page)
                self.assertIn(entry.reference, self.page)

    def testThePageIsInTheDocumentationToctree(self):
        """A page nothing links to is a page nothing renders."""
        toctree = (PAGE.parent / "documentation.rst").read_text(encoding="utf-8")

        self.assertIn("/mib-defects", toctree)


if __name__ == "__main__":
    unittest.main()
