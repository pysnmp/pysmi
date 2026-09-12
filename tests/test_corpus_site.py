#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The corpus rendered as a browsable site (pysnmp/pysmi#276).

Two properties carry the weight. **Nothing on a page arrives by fetch**, since
the AI crawlers this exists to reach do not run JavaScript. And **nothing
reaches a page unescaped**, since every MIB in a corpus is third-party text.

The rest is inventory: the page set has to be bounded, every link has to
resolve, and nothing may be unreachable -- an orphan page is a page that is
not published, whatever is on disk.

See pysnmp/pysmi#284 for the crawl requirements these serve.
"""

import os
import re
import shutil
import tempfile
import unittest

from pysmi.corpus.arcs import Arc
from pysmi.corpus.buckets import buckets
from pysmi.corpus.site import Theme, build_site, load_theme, module_page
from pysmi.corpus.site.html import attributes, paragraphs, table, tag, text
from pysmi.corpus.site.model import children_of, entity_page, imported_by
from pysmi.corpus.site.render import module_html
from pysmi.corpus.site.theme import PAGE, PLACEHOLDERS

#: A module as JsonCodeGen emits it, with prose, so a page has something to
#: render in every section.
ALPHA = {
    "meta": {"module": "ALPHA-MIB"},
    "imports": {
        "class": "imports",
        "SNMPv2-SMI": ["MODULE-IDENTITY", "OBJECT-TYPE", "enterprises"],
    },
    "alphaMI": {
        "name": "alphaMI",
        "oid": "1.3.6.1.4.1.41",
        "class": "moduleidentity",
        "lastupdated": "2024-01-01 00:00",
        "organization": "Acme <Networks> & Co",
        "contactinfo": "someone@example.com",
        "description": "First paragraph.\n\nSecond paragraph.",
        "revisions": [{"revision": "2024-01-01 00:00"}],
    },
    "alphaThing": {
        "name": "alphaThing",
        "oid": "1.3.6.1.4.1.41.1",
        "class": "objecttype",
        "syntax": {
            "type": "INTEGER",
            "class": "type",
            "constraints": {"enumeration": {"up": 1, "down": 2}},
        },
        "maxaccess": "read-only",
        "status": "current",
        "description": "A thing with <angle> brackets & an ampersand.",
    },
    "alphaTrap": {
        "name": "alphaTrap",
        "oid": "1.3.6.1.4.1.41.0.1",
        "class": "notificationtype",
        "status": "current",
    },
    "AlphaTC": {
        "name": "AlphaTC",
        "class": "textualconvention",
        "syntax": {
            "type": "OCTET STRING",
            "class": "type",
            "constraints": {"size": [{"min": 0, "max": 8}]},
        },
        "status": "current",
    },
}

BETA = {
    "meta": {"module": "BETA-MIB"},
    "imports": {"class": "imports", "ALPHA-MIB": ["AlphaTC"]},
    "betaMI": {
        "name": "betaMI",
        "oid": "1.3.6.1.4.1.42",
        "class": "moduleidentity",
        "lastupdated": "2024-01-01 00:00",
    },
}


def corpus(**modules):
    """``(module, jsondoc, tier, rfc)`` rows, as read_documents yields them."""
    return [(name, doc, 0, 0) for name, doc in modules.items()]


def arcs_for(*paths):
    """An arc index over the given arcs, each named after itself."""
    return {x: Arc(x, f"arc{x.replace('.', '')}", "module", "TEST-MIB") for x in paths}


class EscapingTestCase(unittest.TestCase):
    """Every MIB in a corpus is third-party text.

    A DESCRIPTION is whatever a vendor typed, and vendors have typed ``<`` into
    one. The rule is that nothing becomes markup except through ``text()``.
    """

    def testTextEscapesMarkup(self):
        self.assertEqual("&lt;b&gt;", text("<b>"))

    def testTextEscapesQuotes(self):
        self.assertEqual("&quot;x&quot;", text('"x"'))

    def testNoneIsAbsentRatherThanTheWord(self):
        """A fact the corpus does not hold is absent, not the string None."""
        self.assertEqual("", text(None))

    def testAnAttributeValueIsEscaped(self):
        self.assertIn("&quot;", attributes({"title": 'a "quoted" thing'}))

    def testAKeywordAttributeReachesThePageSpelledProperly(self):
        """class_ and for_ cannot be written as keyword arguments; a page that
        carried class_="facts" would be styled by nothing."""
        self.assertEqual('<div class="facts">x</div>', tag("div", "x", class_="facts"))

    def testAnUnderscoreInsideANameBecomesAHyphen(self):
        self.assertEqual(' data-oid="1.3"', attributes({"data_oid": "1.3"}))

    def testAnAbsentAttributeIsLeftOut(self):
        self.assertEqual("", attributes({"id": None, "hidden": False}))

    def testProseIsEscapedParagraphByParagraph(self):
        written = paragraphs("a <b> one\n\ntwo & three")

        self.assertIn("<p>a &lt;b&gt; one</p>", written)
        self.assertIn("<p>two &amp; three</p>", written)

    def testAnEmptyTableIsNoTableAtAll(self):
        """A heading over an empty table reads as a fact being withheld."""
        self.assertEqual("", table(["A"], []))


class ModulePageTestCase(unittest.TestCase):
    """What a module page says, before it is rendered."""

    def page(self, **kwargs):
        return module_page("ALPHA-MIB", ALPHA, **kwargs)

    def testItReadsTheIdentity(self):
        page = self.page()

        self.assertEqual("Acme <Networks> & Co", page.organization)
        self.assertEqual("2024-01-01 00:00", page.lastupdated)
        self.assertEqual(("2024-01-01 00:00",), page.revisions)

    def testItSeparatesWhatAModuleDefines(self):
        page = self.page()

        self.assertEqual(["alphaThing"], [x.name for x in page.objects])
        self.assertEqual(["alphaTrap"], [x.name for x in page.notifications])
        self.assertEqual(["AlphaTC"], [x.name for x in page.types])

    def testEnumeratedSyntaxIsRenderedFlat(self):
        """A table cell wants one line, and a reader wants to find a number."""
        thing = self.page().objects[0]

        self.assertEqual("INTEGER {up(1), down(2)}", thing.syntax)

    def testASizeConstraintIsSpelledAsAMibSpellsIt(self):
        self.assertEqual("OCTET STRING (SIZE(0..8))", self.page().types[0].syntax)

    def testDefinitionsComeOutInOidOrder(self):
        """Numerically: a document lists them however it lists them, and two
        builds of one module have to agree."""
        page = module_page(
            "ORDER-MIB",
            {
                "b": {"name": "b", "oid": "1.3.10", "class": "objecttype"},
                "a": {"name": "a", "oid": "1.3.2", "class": "objecttype"},
            },
        )

        self.assertEqual(["a", "b"], [x.name for x in page.objects])

    def testTheImportsAreReadFromTheModule(self):
        self.assertIn("SNMPv2-SMI", self.page().imports)

    def testReverseDependenciesAreComputedOnce(self):
        found = imported_by([("ALPHA-MIB", ALPHA), ("BETA-MIB", BETA)])

        self.assertEqual(("BETA-MIB",), found["ALPHA-MIB"])
        self.assertNotIn("BETA-MIB", found.get("BETA-MIB", ()))


class RenderTestCase(unittest.TestCase):
    """What reaches the page."""

    def rendered(self, **kwargs):
        return module_html(module_page("ALPHA-MIB", ALPHA, **kwargs), Theme())

    def testEveryFactIsInTheBytes(self):
        """pysnmp/pysmi#284: AI crawlers do not run JavaScript, so a
        client-rendered object table is a page about a MIB module that does
        not say what the module defines."""
        written = self.rendered()

        self.assertIn("alphaThing", written)
        self.assertIn("INTEGER {up(1), down(2)}", written)
        self.assertIn("read-only", written)
        self.assertIn("1.3.6.1.4.1.41.1", written)

    def testTheProseIsThere(self):
        written = self.rendered()

        self.assertIn("First paragraph.", written)
        self.assertIn("Second paragraph.", written)

    def testNothingIsFetched(self):
        """No script, and no reference to anything off this site."""
        written = self.rendered()

        self.assertNotIn("<script", written)
        self.assertNotIn("http://", written)

        for href in re.findall(r'(?:href|src)="([^"]+)"', written):
            with self.subTest(href=href):
                self.assertFalse(href.startswith("https://"), href)

    def testVendorTextCannotInjectMarkup(self):
        written = self.rendered()

        self.assertNotIn("<angle>", written)
        self.assertIn("&lt;angle&gt;", written)
        self.assertNotIn("Acme <Networks>", written)

    def testASectionWithNothingToSayIsNotWritten(self):
        """A heading over an empty table reads as a fact being withheld."""
        written = self.rendered()

        self.assertNotIn("<h2>Repairs</h2>", written)

    def testARepairIsRenderedBesideItsReason(self):
        """A reader has a right to know why the text served here differs from
        the publisher's (pysnmp/pysmi#279)."""
        written = self.rendered(
            defects=[("SMI-MISSING-IMPORT", "https://pysnmp.example/defects")],
            patch="--- a/ALPHA-MIB\n+++ b/ALPHA-MIB\n",
        )

        self.assertIn("SMI-MISSING-IMPORT", written)
        self.assertIn("a/ALPHA-MIB", written)

    def testReverseDependenciesAreBounded(self):
        """1,461 modules import IF-MIB and 5,400 import SNMPv2-SMI, which is
        400 KB of links on a page whose own content is 40 KB."""
        written = self.rendered(importedBy=[f"M{x:04}-MIB" for x in range(500)])

        self.assertIn("500 module(s) in this corpus import this one", written)
        self.assertIn("M0000-MIB", written)
        self.assertNotIn("M0499-MIB", written)

    def testNothingImportingItIsWorthSaying(self):
        self.assertIn("Nothing in this corpus imports this module", self.rendered())

    def testTheLinksAreRelativeToTheSiteRoot(self):
        """So a site published under /mibs/ on a project host works without
        being told where it lives, and so does one opened from a directory."""
        written = self.rendered()

        self.assertIn('href="../../style.css"', written)
        self.assertIn('href="../../browse/"', written)


class ThemeTestCase(unittest.TestCase):
    """A distribution themes this without forking the generator."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)

    def write(self, name, text):
        path = os.path.join(self.root, name)

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(text)

        return path

    def testEveryPlaceholderIsInTheDefaultTemplate(self):
        for name in PLACEHOLDERS:
            with self.subTest(placeholder=name):
                self.assertIn(f"${name}", PAGE.replace("${root}", "$root"))

    def testAReplacedTemplateIsUsed(self):
        theme = load_theme(page=self.write("page.html", "<p>$heading</p>"))

        self.assertIn(
            "<p>ALPHA-MIB</p>", module_html(module_page("ALPHA-MIB", ALPHA), theme)
        )

    def testAReplacedStylesheetIsWritten(self):
        theme = load_theme(stylesheet=self.write("x.css", "body{color:red}"))
        out = os.path.join(self.root, "site")

        build_site(out, corpus(**{"ALPHA-MIB": ALPHA}), theme=theme)

        with open(os.path.join(out, "style.css"), encoding="utf-8") as fileObj:
            self.assertEqual("body{color:red}", fileObj.read())

    def testAMissingThemeFileIsRefusedRatherThanIgnored(self):
        """Falling back would publish a whole site in the wrong skin and say
        nothing about it."""
        from pysmi import error

        with self.assertRaises(error.PySmiError):
            load_theme(page=os.path.join(self.root, "nope.html"))

    def testATypoInAnOverriddenTemplateDoesNotStopTheBuild(self):
        """A page with $oops on it is something somebody sees. Raising 3,000
        pages into a build is not."""
        theme = load_theme(page=self.write("page.html", "$heading $oops"))

        self.assertIn("$oops", module_html(module_page("ALPHA-MIB", ALPHA), theme))

    def testTheCorpusNameReachesTheHeader(self):
        theme = Theme(corpus="pysnmp/mibs")

        self.assertIn(
            "pysnmp/mibs", module_html(module_page("ALPHA-MIB", ALPHA), theme)
        )


class BuildTestCase(unittest.TestCase):
    """The whole tree, and the properties the crawl surface needs of it."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "site")

    def build(self, **kwargs):
        return build_site(
            self.out, corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA}), **kwargs
        )

    def pages(self):
        """Every page written, by its path relative to the site root."""
        found = {}

        for base, _dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith(".html"):
                    path = os.path.relpath(os.path.join(base, name), self.out)
                    with open(os.path.join(base, name), encoding="utf-8") as fileObj:
                        found[path.replace(os.sep, "/")] = fileObj.read()

        return found

    def testOnePagePerModule(self):
        report = self.build()

        self.assertEqual(2, report.modules)
        self.assertIn("mib/ALPHA-MIB/index.html", self.pages())

    def testAPageIsADirectoryIndex(self):
        """So a link is mib/IF-MIB/ and stays that whether the host serves an
        index file or rewrites for one."""
        self.build()

        self.assertTrue(
            os.path.isfile(os.path.join(self.out, "mib", "ALPHA-MIB", "index.html"))
        )

    def testTheModuleSetIsTheCorpusAndNothingElse(self):
        """The site renders what the manifest declared. A directory beside the
        sources -- pysnmp/mibs keeps a broken/ tree -- is not a namespace and
        so is not in the corpus and so gets no pages."""
        self.build()
        written = {x for x in self.pages() if x.startswith("mib/")}

        self.assertEqual(
            {"mib/ALPHA-MIB/index.html", "mib/BETA-MIB/index.html"}, written
        )

    def testEveryRelativeLinkResolves(self):
        self.build(
            anchors={"1.3.6.1.4.1.41": "ALPHA-MIB", "1.3.6.1.4.1.42": "BETA-MIB"},
            arcs=arcs_for(
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.41",
                "1.3.6.1.4.1.42",
            ),
        )

        for path, body in self.pages().items():
            base = os.path.dirname(os.path.join(self.out, path))

            for href in re.findall(r'(?:href|src)="([^"]+)"', body):
                if href.startswith(("http://", "https://", "#", "mailto:")):
                    continue

                target = os.path.normpath(os.path.join(base, href.split("#")[0]))

                with self.subTest(page=path, href=href):
                    self.assertTrue(
                        os.path.isfile(target)
                        or os.path.isfile(os.path.join(target, "index.html")),
                        f"{path} links to {href}",
                    )

    def testNoPageIsAnOrphan(self):
        """A page nothing links to is a page that is not published, whatever
        is on disk. pysnmp/pysmi#284 requires no orphans, and the case that
        breaks it is a structural arc whose parent is a module anchor: that
        parent has no arc page, so only the module page can link down."""
        self.build(
            anchors={"1.3.6.1.4.1.41.5": "ALPHA-MIB", "1.3.6.1.4.1.41": "BETA-MIB"},
            arcs=arcs_for(
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.41",
                "1.3.6.1.4.1.41.5",
            ),
        )

        written = self.pages()
        linked = set()

        for path, body in written.items():
            base = os.path.dirname(os.path.join(self.out, path))

            for href in re.findall(r'href="([^"]+)"', body):
                if href.startswith(("http://", "https://", "#", "mailto:")):
                    continue

                target = os.path.normpath(os.path.join(base, href.split("#")[0]))
                linked.add(
                    os.path.relpath(
                        os.path.join(target, "index.html")
                        if os.path.isdir(target)
                        else target,
                        self.out,
                    ).replace(os.sep, "/")
                )

        for path in written:
            if path == "browse/index.html":
                continue

            with self.subTest(page=path):
                self.assertIn(path, linked)

    def testTheOidTreeStopsAtTheModules(self):
        """An arc at a module's anchor gets no page: that arc is the module.
        See pysnmp/pysmi#292."""
        self.build(
            anchors={"1.3.6.1.4.1.41": "ALPHA-MIB"},
            arcs=arcs_for(
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.41",
            ),
        )

        written = self.pages()

        self.assertIn("oid/1.3.6.1.4.1/index.html", written)
        self.assertNotIn("oid/1.3.6.1.4.1.41/index.html", written)

    def testAnArcThatIsAModuleLinksToTheModulePage(self):
        self.build(
            anchors={"1.3.6.1.4.1.41": "ALPHA-MIB"},
            arcs=arcs_for(
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.41",
            ),
        )

        written = self.pages()["oid/1.3.6.1.4.1/index.html"]

        self.assertIn("../../mib/ALPHA-MIB/", written)

    def testWithoutArcNamesNoTreeIsWritten(self):
        """A tree whose nodes cannot say which module registered them is a
        tree of numbers."""
        report = self.build()

        self.assertEqual(0, report.arcs)
        self.assertNotIn("oid/1/index.html", self.pages())

    def testARegistrantGetsAPage(self):
        report = self.build(
            entities={
                "1.3.6.1.4.1.41": {
                    "number": 41,
                    "organization": "Acme",
                    "modules": ["ALPHA-MIB"],
                    "contacts": [
                        {
                            "source": "registry",
                            "organization": "Acme",
                            "contact": "A Person",
                            "email": "a&example.com",
                            "module": "",
                            "authority": "https://iana.example/41",
                        }
                    ],
                }
            }
        )

        written = self.pages()

        self.assertEqual(1, report.entities)
        self.assertIn("entity/41/index.html", written)
        self.assertIn("a&amp;example.com", written["entity/41/index.html"])

    def testAnEmailKeepsTheRegistrysOwnForm(self):
        """IANA writes davej&cisco.com and the corpus renders IANA's record
        rather than a corrected version of it."""
        self.build(
            entities={
                "1.3.6.1.4.1.41": {
                    "number": 41,
                    "organization": "Acme",
                    "modules": [],
                    "contacts": [{"email": "a&example.com", "source": "registry"}],
                }
            }
        )

        self.assertNotIn("a@example.com", self.pages()["entity/41/index.html"])

    def testALongListSplitsIntoRangeKeyedBuckets(self):
        """Rather than into numbered pages, which renumber under growth."""
        names = {
            f"M{x:03}-MIB": dict(BETA, meta={"module": f"M{x:03}-MIB"})
            for x in range(7)
        }

        build_site(self.out, corpus(**names), size=3)
        written = self.pages()

        keys = [x.key for x in buckets(sorted(names), 3)]

        self.assertEqual(3, len(keys))

        for key in keys:
            with self.subTest(key=key):
                self.assertIn(f"browse/{key}/index.html", written)

    def testAShortListKeepsItsUnbucketedUrl(self):
        self.build()
        written = self.pages()

        self.assertIn("browse/index.html", written)
        self.assertEqual(1, sum(1 for x in written if x.startswith("browse/")))

    def testTheKeyStripIsOnEveryBucketPage(self):
        """So any bucket is one hop from any other and crawl depth does not
        grow with the corpus (pysnmp/pysmi#284)."""
        names = {
            f"M{x:03}-MIB": dict(BETA, meta={"module": f"M{x:03}-MIB"})
            for x in range(7)
        }

        build_site(self.out, corpus(**names), size=3)
        keys = [x.key for x in buckets(sorted(names), 3)]
        written = self.pages()

        for page in (f"browse/{keys[0]}/index.html", f"browse/{keys[-1]}/index.html"):
            for key in keys:
                with self.subTest(page=page, key=key):
                    self.assertIn(key, written[page])

    def testTheStylesheetIsWrittenOnce(self):
        self.build()

        self.assertTrue(os.path.isfile(os.path.join(self.out, "style.css")))

    def testTheReportCountsWhatWasWritten(self):
        report = self.build(
            anchors={"1.3.6.1.4.1.41": "ALPHA-MIB"},
            arcs=arcs_for(
                "1",
                "1.3",
                "1.3.6",
                "1.3.6.1",
                "1.3.6.1.4",
                "1.3.6.1.4.1",
                "1.3.6.1.4.1.41",
            ),
        )
        counts = report.counts()

        self.assertEqual(report.pages, counts["pages"])
        self.assertEqual(2, counts["modules"])
        self.assertGreater(counts["bytes"], 0)

    def testTwoBuildsOfOneCorpusAgree(self):
        """A site is an artifact, and an artifact that differs between two
        builds of one input is not reproducible."""
        first = os.path.join(self.root, "one")
        second = os.path.join(self.root, "two")
        rows = corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA})

        build_site(first, rows)
        build_site(second, rows)

        for base, _dirs, files in os.walk(first):
            for name in files:
                path = os.path.join(base, name)
                other = os.path.join(second, os.path.relpath(path, first))

                with self.subTest(page=os.path.relpath(path, first)):
                    with open(path, "rb") as fileObj:
                        one = fileObj.read()

                    with open(other, "rb") as fileObj:
                        two = fileObj.read()

                    self.assertEqual(one, two)


class ChildrenTestCase(unittest.TestCase):
    """The child map both the OID tree and the module pages read."""

    def testChildrenAreTheArcsDirectlyBelow(self):
        found = children_of(arcs_for("1", "1.3", "1.3.6", "1.4"))

        self.assertEqual(["1.3", "1.4"], [x.arc for x in found["1"]])
        self.assertEqual(["1.3.6"], [x.arc for x in found["1.3"]])

    def testTheyAreInTreeOrder(self):
        """Numerically: 1.10 comes after 1.9, which a lexical sort reverses."""
        found = children_of(arcs_for("1", "1.9", "1.10"))

        self.assertEqual(["1.9", "1.10"], [x.arc for x in found["1"]])


class EntityModelTestCase(unittest.TestCase):
    def testItReadsTheEntityIndexRow(self):
        page = entity_page(
            "1.3.6.1.4.1.9",
            {"number": 9, "organization": "ciscoSystems", "modules": ["B", "A"]},
        )

        self.assertEqual(9, page.number)
        self.assertEqual("1.3.6.1.4.1.9", page.arc)
        self.assertEqual(("A", "B"), page.modules)
