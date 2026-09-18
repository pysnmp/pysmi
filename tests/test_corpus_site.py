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

from pysmi import error
from pysmi.corpus.arcs import Arc
from pysmi.corpus.buckets import buckets
from pysmi.corpus.site import Theme, build_site, load_theme, module_page
from pysmi.corpus.site.build import PageSizes
from pysmi.corpus.site.crawl import Crawl, clip, newest
from pysmi.corpus.site.dates import LABEL, read_changed
from pysmi.corpus.site.html import attributes, paragraphs, table, tag, text
from pysmi.corpus.site.model import (
    RECENT,
    Tally,
    children_of,
    entity_page,
    imported_by,
    tier_name,
)
from pysmi.corpus.site.render import figure, kpis, module_html, overview_html
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

    def testAShortTableScrollsToo(self):
        """A table is wide because of its columns, not its rows.

        The wrapper used to be gated on the row count, more than twelve, so a
        three-row definition table went out bare and pushed the page sideways
        instead of scrolling inside itself. One row is enough to want it.
        """
        written = table(["A", "B"], [["1", "2"]])

        self.assertIn('<div class="wide">', written)
        self.assertTrue(
            written.startswith('<div class="wide">'),
            f"the table is not inside the container: {written[:60]}",
        )

    def testAnEmptyTableHasNoContainerEither(self):
        """Nothing to scroll, so nothing to wrap."""
        self.assertNotIn("wide", table(["A"], []))


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

    def testEveryDefinitionIsADeepLink(self):
        # The row carries the descriptor as its id, so mib/ALPHA-MIB/#alphaThing
        # lands on the definition. Nothing asserted this before the markup was
        # trimmed, which is how the anchor could have been dropped silently.
        written = self.rendered()

        self.assertIn('<tr id="alphaThing">', written)

    def testDefinitionCellsCarryNoWrappers(self):
        # The stylesheet reaches these cells by position. A wrapper per cell
        # cost 61 bytes a row, which over pysnmp/mibs' 764,000 definitions was
        # 47 MB of module pages -- so a regression that reintroduces one is a
        # size regression, and this is what notices.
        written = self.rendered()
        table = written[written.index('class="defs') :]

        for wrapper in ("<code", '<span class="oid"'):
            with self.subTest(wrapper=wrapper):
                self.assertNotIn(wrapper, table)

        # Still there, still legible, just unwrapped.
        self.assertIn("<td>1.3.6.1.4.1.41.1</td>", written)

    def testTheTableSaysWhichShapeItIs(self):
        # .defs.typed is the five-column shape and .defs the three-column one.
        # The positional rules in the stylesheet depend on telling them apart,
        # so a theme replacing it needs this to be stable.
        written = self.rendered()

        self.assertIn('class="defs typed"', written)

    def testCellsAreNotSeparatedByNewlines(self):
        written = self.rendered()

        self.assertNotIn("</td>\n<td>", written)

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

    def bucketed_entities(self, count=7, size=3):
        """A corpus with enough registrants that the list of them splits.

        The fixtures elsewhere have one or two, which never bucket -- and the
        corpus this is built for has 356, which do. That gap is how
        pysnmp/pysmi#276 shipped with every registrant breadcrumb pointing at
        a page nothing wrote.
        """
        return {
            f"1.3.6.1.4.1.{40 + x}": {
                "number": 40 + x,
                "organization": f"Vendor {x}",
                "modules": ["ALPHA-MIB"],
                "contacts": [],
            }
            for x in range(count)
        }

    def testTheRegistrantListHasARootWhenItBuckets(self):
        """Every registrant page's breadcrumb points at entity/, and so does
        llms.txt. A bucketed list that writes only its buckets leaves that a
        404."""
        self.build(entities=self.bucketed_entities(), size={"entity": 3})

        written = self.pages()

        self.assertIn("entity/index.html", written)
        self.assertGreater(sum(1 for x in written if x.startswith("entity/")), 8)

    def testEveryLinkResolvesWhenTheListsBucket(self):
        """The whole-tree check the fixtures above are too small to exercise."""
        self.build(
            entities=self.bucketed_entities(),
            size={"browse": 1, "entity": 3},
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


class CrawlTestCase(unittest.TestCase):
    """The crawl surface (pysnmp/pysmi#284).

    Written only when the manifest declares a ``base-url``, which is what says
    this build is producing a distribution site rather than a subtree somebody
    else will assemble.
    """

    CRAWL = Crawl(
        base="https://mibs.example",
        description="A corpus of MIB modules.",
        policy={
            "*": {"disallow": ["asn1", "json"]},
            "ClaudeBot": {"allow": ["asn1", "json"]},
        },
    )

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "site")

    def build(self, crawl=None, **kwargs):
        return build_site(
            self.out,
            corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA}),
            crawl=self.CRAWL if crawl is None else crawl,
            **kwargs,
        )

    def read(self, name):
        with open(os.path.join(self.out, *name.split("/")), encoding="utf-8") as f:
            return f.read()

    def testASubtreeBuildWritesNoCrawlSurface(self):
        report = build_site(self.out, corpus(**{"ALPHA-MIB": ALPHA}))

        self.assertFalse(report.crawlable)
        self.assertEqual(0, report.sitemaps)

        for name in ("sitemap.xml", "robots.txt", "llms.txt"):
            with self.subTest(file=name):
                self.assertFalse(os.path.exists(os.path.join(self.out, name)))

    def testADistributionBuildWritesIt(self):
        report = self.build()

        self.assertTrue(report.crawlable)
        self.assertGreater(report.sitemaps, 0)

        for name in ("sitemap.xml", "robots.txt", "llms.txt"):
            with self.subTest(file=name):
                self.assertTrue(os.path.exists(os.path.join(self.out, name)))

    def testAPageCarriesItsCanonicalUrl(self):
        self.build()

        self.assertIn(
            '<link rel="canonical" href="https://mibs.example/mib/ALPHA-MIB/">',
            self.read("mib/ALPHA-MIB/index.html"),
        )

    def testAPageCarriesADescription(self):
        self.build()
        written = self.read("mib/ALPHA-MIB/index.html")

        self.assertIn('<meta name="description"', written)
        self.assertIn("First paragraph.", written)

    def testADescriptionFallsBackToWhatThePageIs(self):
        """A build carrying no texts has no DESCRIPTION, and a stated count
        beats a generated sentence that says nothing."""
        build_site(self.out, corpus(**{"BETA-MIB": BETA}), crawl=self.CRAWL)

        self.assertIn("BETA-MIB: 0 object(s)", self.read("mib/BETA-MIB/index.html"))

    def testTheJsonLdIdentifiesByOid(self):
        """An OID is a globally unique identifier that already exists, and a
        consumer holding one should be able to match it without reading
        prose."""
        self.build(anchors={"1.3.6.1.4.1.41": "ALPHA-MIB"})
        written = self.read("mib/ALPHA-MIB/index.html")

        self.assertIn('"identifier":"urn:oid:1.3.6.1.4.1.41"', written)
        self.assertIn('"identifier":"urn:oid:1.3.6.1.4.1.41.1"', written)
        self.assertIn('"@type":["DefinedTermSet","Dataset"]', written)

    def testTheJsonLdCarriesTheRevisionDate(self):
        self.build()

        self.assertIn(
            '"dateModified":"2024-01-01"', self.read("mib/ALPHA-MIB/index.html")
        )

    def testTheJsonLdCannotCloseItsOwnScriptElement(self):
        """Inside <script> the only sequence that ends it is "</", and a
        vendor DESCRIPTION containing one would otherwise break the page."""
        document = dict(ALPHA)
        document["alphaMI"] = dict(
            ALPHA["alphaMI"], description="ends with </script> in it"
        )

        build_site(self.out, corpus(**{"ALPHA-MIB": document}), crawl=self.CRAWL)
        written = self.read("mib/ALPHA-MIB/index.html")

        self.assertIn("<\\/script>", written)
        self.assertEqual(1, written.count("</script>"))

    def testTheJsonLdCannotOpenAnHtmlComment(self):
        document = dict(ALPHA)
        document["alphaMI"] = dict(ALPHA["alphaMI"], description="a <!-- b")

        build_site(self.out, corpus(**{"ALPHA-MIB": document}), crawl=self.CRAWL)
        written = self.read("mib/ALPHA-MIB/index.html")

        self.assertIn("<\\!--", written)

    def testEverySitemapUrlIsAPageThatWasWritten(self):
        """Built from what the writer recorded rather than by walking the
        tree, so it cannot list a URL this build did not write."""
        self.build()

        listed = set()

        for name in os.listdir(self.out):
            if name.startswith("sitemap-"):
                listed.update(re.findall(r"<loc>([^<]+)</loc>", self.read(name)))

        for url in listed:
            path = url[len("https://mibs.example/") :]

            with self.subTest(url=url):
                self.assertTrue(
                    os.path.isfile(
                        os.path.join(self.out, *path.split("/"), "index.html")
                    )
                    if path
                    else os.path.isfile(os.path.join(self.out, "index.html"))
                )

    def testEveryPageIsInTheSitemap(self):
        self.build()

        listed = set()

        for name in os.listdir(self.out):
            if name.startswith("sitemap-"):
                listed.update(re.findall(r"<loc>([^<]+)</loc>", self.read(name)))

        for base, _dirs, files in os.walk(self.out):
            if "index.html" not in files:
                continue

            rel = os.path.relpath(base, self.out).replace(os.sep, "/")
            url = "https://mibs.example/" + ("" if rel == "." else rel + "/")

            with self.subTest(page=rel):
                self.assertIn(url, listed)

    def testTheIndexIsEmittedRegardless(self):
        """At this size one file is well inside the protocol's 50,000-URL
        limit, but a downstream corpus may not be and exceeding it fails
        silently."""
        self.build()
        index = self.read("sitemap.xml")

        self.assertIn("<sitemapindex", index)
        self.assertIn("sitemap-mib.xml", index)

    def testLastmodIsTheModulesOwnRevisionDate(self):
        """Not the build clock. A corpus rebuilt on every push that stamps
        every page with today's date teaches a crawler the field is noise."""
        self.build()

        self.assertIn("<lastmod>2024-01-01</lastmod>", self.read("sitemap-mib.xml"))

    def testNoBuildDateReachesASitemap(self):
        import datetime

        self.build()
        today = datetime.date.today().isoformat()

        for name in os.listdir(self.out):
            if name.startswith("sitemap"):
                with self.subTest(file=name):
                    self.assertNotIn(today, self.read(name))

    def testAPageWithNoDateIsListedWithoutOne(self):
        """Absent rather than invented: no lastmod says "I do not know", which
        is true, where the build date says something false."""
        build_site(
            self.out,
            corpus(**{"UNDATED-MIB": {"x": {"name": "x", "class": "objecttype"}}}),
            crawl=self.CRAWL,
        )
        written = self.read("sitemap-mib.xml")

        self.assertIn("UNDATED-MIB", written)
        self.assertNotIn("<lastmod>", written)

    def testTwoBuildsProduceTheSameSitemap(self):
        first = os.path.join(self.root, "one")
        second = os.path.join(self.root, "two")
        rows = corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA})

        build_site(first, rows, crawl=self.CRAWL)
        build_site(second, rows, crawl=self.CRAWL)

        for name in ("sitemap.xml", "sitemap-mib.xml", "robots.txt", "llms.txt"):
            with self.subTest(file=name):
                with open(os.path.join(first, name), "rb") as f:
                    one = f.read()

                with open(os.path.join(second, name), "rb") as f:
                    two = f.read()

                self.assertEqual(one, two)

    def testRobotsNamesArtifactsRatherThanPaths(self):
        """A distribution saying "keep search engines out of the raw JSON"
        should not have to know what that tree is called."""
        self.build()
        written = self.read("robots.txt")

        self.assertIn("User-agent: *\nDisallow: /asn1/\nDisallow: /json/", written)
        self.assertIn("User-agent: ClaudeBot\nAllow: /asn1/\nAllow: /json/", written)

    def testRobotsPointsAtTheSitemap(self):
        self.build()

        self.assertIn(
            "Sitemap: https://mibs.example/sitemap.xml", self.read("robots.txt")
        )

    def testAnArtifactNobodyKnowsIsSkippedRatherThanWritten(self):
        """A rule about a tree that is not there is a rule nobody can act on,
        and it would read as though the tree existed."""
        crawl = Crawl(base="https://mibs.example", policy={"*": {"disallow": ["nope"]}})

        self.build(crawl=crawl)
        written = self.read("robots.txt")

        self.assertNotIn("nope", written)
        self.assertIn("User-agent: *", written)

    def testLlmsSaysWhatThisIsAndWhereTheDataIs(self):
        self.build()
        written = self.read("llms.txt")

        self.assertIn("A corpus of MIB modules.", written)
        self.assertIn("https://mibs.example/browse/", written)
        self.assertIn("https://mibs.example/asn1/", written)

    def testBulkLinksTakeTheDataOriginWhereOneIsDeclared(self):
        """Pages and files can be on two hosts. mibsdepot.com resolves a
        directory URL to its index.html and data.mibsdepot.com does not, so a
        build that wrote every link against one origin would publish three
        bulk links that 404."""
        self.build(
            crawl=Crawl(
                base="https://mibs.example",
                data="https://data.mibs.example",
                description="A corpus of MIB modules.",
            )
        )
        written = self.read("llms.txt")

        self.assertIn("https://data.mibs.example/asn1/", written)
        self.assertIn("https://data.mibs.example/json/", written)
        self.assertIn("https://data.mibs.example/index-v2.csv", written)
        # A page is always on the site's own origin, the sitemap included.
        self.assertIn("https://mibs.example/browse/", written)
        self.assertIn("https://mibs.example/sitemap.xml", written)
        self.assertNotIn("https://mibs.example/asn1/", written)
        # The canonical link describes a page, so the data origin never
        # reaches one.
        self.assertNotIn("data.mibs.example", self.read("sitemap.xml"))

    def testLlmsIsTitledForTheCorpusRatherThanItsDescription(self):
        report = build_site(
            self.out,
            corpus(**{"ALPHA-MIB": ALPHA}),
            theme=Theme(corpus="pysnmp/mibs"),
            crawl=self.CRAWL,
        )

        self.assertTrue(report.crawlable)
        self.assertTrue(self.read("llms.txt").startswith("# pysnmp/mibs\n"))


class CrawlHelperTestCase(unittest.TestCase):
    """The pieces, away from a whole build."""

    def testNewestTakesTheLatestDate(self):
        self.assertEqual("2020-05-06", newest(["2019-01-01 00:00", "2020-05-06 12:00"]))

    def testAnUnreadableStampIsDroppedRatherThanRanked(self):
        """HPR-MIB carries 970514000000Z -- year 9705, month 14 -- and month
        14 compares above every real date there will ever be, so the module
        carrying it would set the lastmod of every page listing it."""
        self.assertEqual("2020-05-06", newest(["9705-14-01", "2020-05-06 00:00", ""]))

    def testSomethingThatIsNotShapedLikeADateIsDropped(self):
        self.assertEqual("", newest(["not a date", "202401010000Z"]))

    def testNoDatesGiveNoDate(self):
        self.assertEqual("", newest([]))

    def testClipCollapsesWhitespaceForAMetaTag(self):
        self.assertEqual("a b c", clip("a\n  b\tc"))

    def testClipStopsAtAWordBoundary(self):
        written = clip("alpha beta gamma delta", 12)

        self.assertLessEqual(len(written), 12)
        self.assertTrue(written.endswith("…"))
        self.assertNotIn("gamma", written)

    def testAUrlIsJoinedWithoutDoubledSlashes(self):
        crawl = Crawl(base="https://x.example/")

        self.assertEqual("https://x.example/mib/A/", crawl.url("/mib/A/"))

    def testADataUrlFallsBackToTheSiteOrigin(self):
        """One origin serving both is the ordinary case, and a distribution
        that declares no data-url must not lose its bulk links to an empty
        string."""
        crawl = Crawl(base="https://x.example")

        self.assertEqual("https://x.example/asn1/", crawl.data_url("asn1/"))

    def testADataUrlIsJoinedWithoutDoubledSlashes(self):
        crawl = Crawl(base="https://x.example/", data="https://data.x.example/")

        self.assertEqual("https://data.x.example/asn1/", crawl.data_url("/asn1/"))


class PageSizeTestCase(unittest.TestCase):
    """How long each kind of list gets before it splits.

    One number would do if the lists were alike. The module list is the site's
    front door; a registrant's list is reached by someone already narrowed to
    one vendor, and Cisco's 1,341 modules at the same size would be three
    pages of 500 links each. pysnmp/mibs#406.
    """

    def testNothingGivesTheDefaults(self):
        self.assertEqual(PageSizes(), PageSizes.of(None))

    def testOneNumberAppliesToEveryList(self):
        self.assertEqual(PageSizes(browse=50, entity=50), PageSizes.of(50))

    def testTheListsCanBeNamedIndividually(self):
        self.assertEqual(
            PageSizes(browse=500, entity=200),
            PageSizes.of({"browse": 500, "entity": 200}),
        )

    def testNamingOneLeavesTheOtherAtItsDefault(self):
        found = PageSizes.of({"entity": 200})

        self.assertEqual(200, found.entity)
        self.assertEqual(PageSizes().browse, found.browse)

    def testAListNobodyKnowsIsRefused(self):
        """A manifest saying "entities" where the key is "entity" would
        otherwise publish a site silently paginated wrong."""
        with self.assertRaises(ValueError):
            PageSizes.of({"entities": 200})

    def testASizeThatIsNotAPositiveNumberIsRefused(self):
        for bad in ({"browse": 0}, {"browse": -1}, {"browse": "500"}, {"browse": True}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                PageSizes.of(bad)

    def testSomethingThatIsNeitherIsRefused(self):
        with self.assertRaises(TypeError):
            PageSizes.of(["500"])

    def testABooleanIsNotAPageSize(self):
        with self.assertRaises(TypeError):
            PageSizes.of(True)

    def testTheTwoListsSplitIndependently(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        out = os.path.join(root, "site")

        names = {
            f"M{x:03}-MIB": dict(BETA, meta={"module": f"M{x:03}-MIB"})
            for x in range(7)
        }

        build_site(
            out,
            corpus(**names),
            size={"browse": 3, "entity": 100},
            entities={
                "1.3.6.1.4.1.41": {
                    "number": 41,
                    "organization": "Acme",
                    "modules": sorted(names),
                    "contacts": [],
                }
            },
        )

        written = {
            os.path.relpath(os.path.join(b, f), out).replace(os.sep, "/")
            for b, _d, files in os.walk(out)
            for f in files
            if f == "index.html"
        }

        self.assertEqual(4, sum(1 for x in written if x.startswith("browse/")))
        self.assertEqual(1, sum(1 for x in written if x.startswith("entity/41/")))


class OverviewTestCase(unittest.TestCase):
    """What the entry point states about the corpus as a whole.

    Every figure is a sum over the module pages the build already rendered,
    and every one of them is in the bytes -- the front page is the first thing
    a crawler reads, and a figure it has to fetch is a figure it does not see.
    """

    def tally(self, *rows):
        """A tally over ``(module, jsondoc, tier, revised)`` rows."""
        found = Tally()

        for name, document, tier, revised in rows:
            found.add(
                module_page(name, document), tier=tier_name(tier), revised=revised
            )

        return found

    def testItCountsModulesByTier(self):
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 0, "2024-01-01"),
            ("BETA-MIB", BETA, 2, "2024-02-02"),
        ).overview()

        self.assertEqual(2, overview.modules)
        self.assertEqual({"standard": 1, "vendor": 1}, dict(overview.tiers))

    def testTiersComeOutInRankOrder(self):
        """Rather than in the order the modules happened to be read, so two
        builds of one corpus state it the same way."""
        overview = self.tally(
            ("BETA-MIB", BETA, 2, "2024-02-02"),
            ("ALPHA-MIB", ALPHA, 0, "2024-01-01"),
        ).overview()

        self.assertEqual(["standard", "vendor"], list(overview.tiers))

    def testATierWithNoModulesIsNotNamed(self):
        """A count of zero states an opinion about a tier the corpus does not
        draw from."""
        overview = self.tally(("ALPHA-MIB", ALPHA, 0, "2024-01-01")).overview()

        self.assertNotIn("vendor", overview.tiers)
        self.assertNotIn("draft", overview.tiers)

    def testItSumsWhatTheCorpusDefines(self):
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 0, "2024-01-01"),
            ("BETA-MIB", BETA, 2, "2024-02-02"),
        ).overview()

        self.assertEqual(
            (
                len(module_page("ALPHA-MIB", ALPHA).objects)
                + len(module_page("BETA-MIB", BETA).objects)
            ),
            overview.objects,
        )
        self.assertEqual(1, overview.notifications)
        self.assertEqual(1, overview.types)

    def testARepairedModuleIsCounted(self):
        found = Tally()
        found.add(
            module_page("ALPHA-MIB", ALPHA, defects=(("PATCH-1", ""),), patch="--- a\n")
        )
        found.add(module_page("BETA-MIB", BETA))

        self.assertEqual(1, found.overview().repaired)

    def testAnIncompleteClosureIsCounted(self):
        found = Tally()
        found.add(module_page("ALPHA-MIB", ALPHA, missing=("GAMMA-MIB",)))
        found.add(module_page("BETA-MIB", BETA))

        self.assertEqual(1, found.overview().incomplete)

    def testTheLatestIsNewestFirstWithinItsTier(self):
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 2, "2024-01-01"),
            ("BETA-MIB", BETA, 2, "2026-03-04"),
            ("GAMMA-MIB", BETA, 2, "2025-02-03"),
        ).overview()

        self.assertEqual(
            ["BETA-MIB", "GAMMA-MIB", "ALPHA-MIB"],
            [x.module for x in overview.latest["vendor"]],
        )

    def testTheLatestIsBounded(self):
        """The list answers what moved lately, which a handful of rows
        answers. The whole corpus stays one hop away through the range
        keys."""
        overview = self.tally(
            *(
                (f"M{x:03}-MIB", BETA, 2, f"2024-01-{x + 1:02}")
                for x in range(RECENT + 5)
            )
        ).overview()

        self.assertEqual(RECENT, len(overview.latest["vendor"]))

    def testEachTierHasItsOwnList(self):
        """Which is the point of splitting them: a corpus of 5,000 vendor
        modules and a few hundred standard ones has no recent standard
        revision in a single list, and the standard modules are what a reader
        resolving an OID is looking at."""
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 0, "2020-01-01"),
            ("BETA-MIB", BETA, 2, "2026-03-04"),
        ).overview()

        self.assertEqual(["ALPHA-MIB"], [x.module for x in overview.latest["standard"]])
        self.assertEqual(["BETA-MIB"], [x.module for x in overview.latest["vendor"]])

    def testAModuleWithNoReadableDateIsCountedAndNotListed(self):
        """HPR-MIB carries 970514000000Z -- year 9705, month 14 -- and a date
        that cannot be placed cannot order a list."""
        overview = self.tally(("ALPHA-MIB", ALPHA, 2, "")).overview()

        self.assertEqual(1, overview.modules)
        self.assertEqual({}, dict(overview.latest))
        self.assertEqual("", overview.revised)

    def testTheCorpusDateIsTheNewestAnyModuleCarries(self):
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 0, "2024-01-01"),
            ("BETA-MIB", BETA, 2, "2026-03-04"),
        ).overview()

        self.assertEqual("2026-03-04", overview.revised)


class OverviewRenderTestCase(unittest.TestCase):
    """The figures as the entry point renders them."""

    def overview(self, **kwargs):
        found = Tally()
        found.add(
            module_page("ALPHA-MIB", ALPHA), tier="standard", revised="2024-01-01"
        )
        found.add(module_page("BETA-MIB", BETA), tier="vendor", revised="2026-03-04")

        return found.overview(**kwargs)

    def testTheFiguresAreGrouped(self):
        """A reader scanning a headline reads 14,752 and not 14752."""
        self.assertEqual("14,752", figure(14752))

    def testThereIsOneHeroFigure(self):
        """Two numbers at the same size are two headlines and no lead."""
        written = overview_html("../", self.overview())

        self.assertEqual(1, written.count('class="hero"'))

    def testTheHeroIsTheModuleCount(self):
        written = overview_html("../", self.overview())

        self.assertIn('<span class="figure">2</span>', written)
        self.assertIn("modules in this corpus", written)

    def testAZeroCountIsNoTile(self):
        """A build given no arc names holds no opinion about how many arcs
        there are, and a tile reading 0 states one."""
        self.assertNotIn("OID arcs", kpis(self.overview()))
        self.assertIn("OID arcs", kpis(self.overview(arcs=7)))

    def testEveryTierGetsASection(self):
        written = overview_html("../", self.overview())

        self.assertIn("Recently revised standard modules", written)
        self.assertIn("Recently revised vendor modules", written)

    def testTheModuleLinksAreRelativeToTheSiteRoot(self):
        written = overview_html("../", self.overview())

        self.assertIn('href="../mib/BETA-MIB/"', written)

    def testACorpusOfNoModulesRendersNothing(self):
        """A heading over an empty tile row reads as a fact the corpus holds
        and is not showing."""
        self.assertEqual("", overview_html("../", Tally().overview()))

    def testTheOrganizationIsEscaped(self):
        """It is whatever a vendor typed into ORGANIZATION."""
        found = Tally()
        found.add(module_page("ALPHA-MIB", ALPHA), tier="vendor", revised="2024-01-01")

        self.assertNotIn("<Networks>", overview_html("../", found.overview()))


class ChangedDatesTestCase(unittest.TestCase):
    """The dates a distribution supplies for its own modules.

    Every date a MIB carries is its publisher's, so "what has this
    distribution done lately" is a question the corpus cannot answer out of
    its own contents. The dates arrive from the distribution, and the point of
    the checking here is that a date nobody supplied never reaches a page: a
    row reading "this corpus holds 6,982 modules we track" over a corpus whose
    standard tier comes from somewhere else is exactly the kind of claim this
    feature exists to avoid making.
    """

    def setUp(self):
        self.where = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.where, ignore_errors=True)

    def written(self, body):
        """A dates file holding *body* verbatim."""
        path = os.path.join(self.where, "dates.json")

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(body)

        return path

    def testItReadsTheDates(self):
        found = read_changed(self.written('{"ALPHA-MIB": "2026-09-17"}'))

        self.assertEqual({"ALPHA-MIB": "2026-09-17"}, dict(found.dates))

    def testItTakesTheLabelTheManifestGave(self):
        found = read_changed(self.written("{}"), "Added here")

        self.assertEqual("Added here", found.label)

    def testThereIsALabelWithoutOne(self):
        self.assertEqual(LABEL, read_changed(self.written("{}")).label)

    def testAMissingFileIsAnError(self):
        """Named and unreadable is a typo in a manifest, not a reason to
        publish a site that quietly says the distribution changed nothing."""
        with self.assertRaises(error.PySmiError):
            read_changed(os.path.join(self.where, "nope.json"))

    def testTextThatIsNotJsonIsAnError(self):
        with self.assertRaises(error.PySmiError):
            read_changed(self.written("{oh dear"))

    def testAListIsNotADatesFile(self):
        with self.assertRaises(error.PySmiError):
            read_changed(self.written('["ALPHA-MIB"]'))

    def testADateItCannotSortByIsAnError(self):
        """The lists sort on these and print them verbatim, so a row reading
        "last week" sorts nowhere and says nothing a reader can compare."""
        for bad in (
            '{"ALPHA-MIB": "last week"}',
            '{"ALPHA-MIB": "2026-9-1"}',
            '{"ALPHA-MIB": 20260917}',
            '{"ALPHA-MIB": null}',
        ):
            with self.subTest(bad=bad), self.assertRaises(error.PySmiError):
                read_changed(self.written(bad))


class ChangedOverviewTestCase(unittest.TestCase):
    """The second recency axis, as the tally totals it."""

    def tally(self, *rows):
        """A tally over ``(module, jsondoc, tier, revised, changed)`` rows."""
        found = Tally()

        for name, document, tier, revised, changed in rows:
            found.add(
                module_page(name, document),
                tier=tier_name(tier),
                revised=revised,
                changed=changed,
            )

        return found

    def testWithoutDatesThereIsNoSecondAxis(self):
        overview = self.tally(("ALPHA-MIB", ALPHA, 0, "2024-01-01", "")).overview()

        self.assertEqual({}, dict(overview.latestChanged))

    def testItOrdersByTheSuppliedDateAndNotThePublishers(self):
        """The two orderings are the whole point: a module taken today carries
        whatever revision its publisher last set, which may be from 1994."""
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 2, "1994-01-01", "2026-09-17"),
            ("BETA-MIB", BETA, 2, "2026-03-04", "2020-01-01"),
        ).overview()

        self.assertEqual(
            ["BETA-MIB", "ALPHA-MIB"], [x.module for x in overview.latest["vendor"]]
        )
        self.assertEqual(
            ["ALPHA-MIB", "BETA-MIB"],
            [x.module for x in overview.latestChanged["vendor"]],
        )

    def testAModuleWithNoSuppliedDateIsNotListedUnderOne(self):
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 2, "2024-01-01", "2026-09-17"),
            ("BETA-MIB", BETA, 2, "2024-02-02", ""),
        ).overview()

        self.assertEqual(
            ["ALPHA-MIB"], [x.module for x in overview.latestChanged["vendor"]]
        )
        self.assertEqual(2, len(overview.latest["vendor"]))

    def testAModuleDatedOnlyByTheDistributionIsStillListedThere(self):
        """A module whose text carries no REVISION at all is invisible to the
        publisher axis and is not invisible to this one."""
        overview = self.tally(("ALPHA-MIB", ALPHA, 2, "", "2026-09-17")).overview()

        self.assertEqual({}, dict(overview.latest))
        self.assertEqual(
            ["ALPHA-MIB"], [x.module for x in overview.latestChanged["vendor"]]
        )

    def testATierNobodyDatedIsLeftOut(self):
        """Which is what makes the list honest on a corpus whose standard tier
        comes from somewhere the distribution does not track."""
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 0, "2024-01-01", ""),
            ("BETA-MIB", BETA, 2, "2024-02-02", "2026-09-17"),
        ).overview()

        self.assertEqual(["vendor"], list(overview.latestChanged))
        self.assertEqual({"vendor": 1}, dict(overview.datedChanged))

    def testThePoolIsWhatTheDistributionDatedAndNotTheTier(self):
        """ "The ten most recent of the 6,982 it tracks" and "of the 6,982 this
        corpus holds" are different claims."""
        overview = self.tally(
            ("ALPHA-MIB", ALPHA, 2, "2024-01-01", "2026-09-17"),
            ("BETA-MIB", BETA, 2, "2024-02-02", ""),
        ).overview()

        self.assertEqual({"vendor": 2}, dict(overview.tiers))
        self.assertEqual({"vendor": 1}, dict(overview.datedChanged))

    def testTheListIsBounded(self):
        overview = self.tally(
            *(
                (f"MOD-{x}-MIB", ALPHA, 2, "2024-01-01", f"2026-01-{x:02d}")
                for x in range(1, 20)
            )
        ).overview()

        self.assertEqual(RECENT, len(overview.latestChanged["vendor"]))


class ChangedRenderTestCase(unittest.TestCase):
    """The two axes as the entry point offers them."""

    def overview(self, changed=("2026-09-17", "2020-01-01")):
        found = Tally()
        found.add(
            module_page("ALPHA-MIB", ALPHA),
            tier="standard",
            revised="2024-01-01",
            changed=changed[0],
        )
        found.add(
            module_page("BETA-MIB", BETA),
            tier="vendor",
            revised="2026-03-04",
            changed=changed[1],
        )

        return found.overview()

    def testWithoutDatesThePageIsWhatItWas(self):
        """Every other distribution's front page must not grow a tab strip
        with one tab on it."""
        written = overview_html("../", self.overview(changed=("", "")))

        self.assertNotIn('class="switch"', written)
        self.assertNotIn('type="radio"', written)
        self.assertIn("Recently revised standard modules", written)

    def testBothAxesAreOffered(self):
        written = overview_html("../", self.overview())

        self.assertEqual(1, written.count('class="switch"'))
        self.assertEqual(2, written.count('type="radio"'))
        self.assertEqual(1, written.count('class="panel recent-published"'))
        self.assertEqual(1, written.count('class="panel recent-changed"'))

    def testOneTabIsCheckedToBeginWith(self):
        """A switch with nothing checked shows neither panel."""
        self.assertEqual(1, overview_html("../", self.overview()).count("checked"))

    def testEveryLabelPointsAtItsRadio(self):
        written = overview_html("../", self.overview())

        for name in ("recent-published", "recent-changed"):
            self.assertIn(f'id="{name}"', written)
            self.assertIn(f'for="{name}"', written)

    def testTheTabTakesTheManifestsLabel(self):
        written = overview_html("../", self.overview(), label="Added by us")

        self.assertIn("Added by us", written)

    def testThereIsALabelWithoutOne(self):
        self.assertIn(LABEL, overview_html("../", self.overview()))

    def testTheLabelIsEscaped(self):
        """It comes out of a manifest, which is a file somebody edits."""
        written = overview_html("../", self.overview(), label="<script>x</script>")

        self.assertNotIn("<script>", written)

    def testEachAxisNamesItsOwnDateColumn(self):
        written = overview_html("../", self.overview())

        self.assertIn(">Revised</th>", written)
        self.assertIn(">Changed</th>", written)

    def testEachPanelPrintsItsOwnDate(self):
        """The row is one object carrying both dates, so a panel reading the
        wrong field is a table of plausible-looking wrong dates."""
        written = overview_html("../", self.overview())
        published = written[written.index('class="panel recent-published"') :]
        published = published[: published.index('class="panel recent-changed"')]
        supplied = written[written.index('class="panel recent-changed"') :]

        self.assertIn("2024-01-01", published)
        self.assertNotIn("2026-09-17", published)
        self.assertIn("2026-09-17", supplied)
        self.assertNotIn("2024-01-01", supplied)

    def testATabbedHeadingNamesTheTierAndNotTheDate(self):
        """The tab above already says which date the panel is ordered by."""
        written = overview_html("../", self.overview())

        self.assertIn("<h2>Standard modules</h2>", written)
        self.assertNotIn("Recently revised standard modules", written)

    def testTheNoteSaysWhoseDateItIs(self):
        written = overview_html("../", self.overview())

        self.assertIn("the one the module itself carries", written)
        self.assertIn("not a date the module itself carries", written)

    def testEveryPanelIsInTheBytes(self):
        """The stylesheet hides one of them. A reader with no CSS sees both
        lists under their own headings, and so does a crawler."""
        written = overview_html("../", self.overview())

        self.assertIn("ALPHA-MIB", written)
        self.assertIn("2026-09-17", written)
        self.assertNotIn("script", written)


class BrowseOverviewTestCase(unittest.TestCase):
    """Where the figures land in a built tree."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        self.out = os.path.join(self.root, "site")

    def pages(self):
        found = {}

        for base, _dirs, files in os.walk(self.out):
            for name in files:
                if name.endswith(".html"):
                    path = os.path.relpath(os.path.join(base, name), self.out)
                    with open(os.path.join(base, name), encoding="utf-8") as fileObj:
                        found[path.replace(os.sep, "/")] = fileObj.read()

        return found

    def testTheEntryPointCarriesThem(self):
        build_site(self.out, corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA}))

        self.assertIn('class="kpis"', self.pages()["browse/index.html"])

    def testTheyAreInTheBytes(self):
        """The front page is the first thing a crawler reads, and the crawlers
        this exists to reach do not run JavaScript."""
        build_site(self.out, corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA}))
        written = self.pages()["browse/index.html"]

        self.assertNotIn("<script", written)
        self.assertIn("Recently revised", written)

    def testABucketPageIsAListAndNotAFrontPage(self):
        """Repeating the figures above each of twelve buckets states the same
        facts twelve times and moves the list below the fold."""
        names = {
            f"M{x:03}-MIB": dict(BETA, meta={"module": f"M{x:03}-MIB"})
            for x in range(7)
        }

        build_site(self.out, corpus(**names), size=3)
        written = self.pages()
        keys = [x.key for x in buckets(sorted(names), 3)]

        self.assertIn('class="kpis"', written["browse/index.html"])

        for key in keys:
            with self.subTest(key=key):
                self.assertNotIn('class="kpis"', written[f"browse/{key}/index.html"])

    def testTheEntryPointStatesTheCountOnceRatherThanTwice(self):
        build_site(self.out, corpus(**{"ALPHA-MIB": ALPHA, "BETA-MIB": BETA}))

        self.assertNotIn(
            "2 module(s) in this corpus", self.pages()["browse/index.html"]
        )

    def testTheTiersComeFromTheDocuments(self):
        """``read_documents`` yields the tier rank its namespace declared, and
        the page states the name."""
        build_site(
            self.out,
            [("ALPHA-MIB", ALPHA, 0, 0), ("BETA-MIB", BETA, 2, 0)],
        )
        written = self.pages()["browse/index.html"]

        self.assertIn("Standard modules", written)
        self.assertIn("Vendor modules", written)


class EmitPathTestCase(unittest.TestCase):
    """Where ``--emit=site`` puts the trees.

    The site's trees are named so that nothing collides with a corpus path,
    which is only worth anything if they share a directory with one: a reader
    browsing ``mib/IF-MIB/`` and a consumer fetching ``asn1/IF-MIB`` are
    looking at the same publication. pysnmp/mibs#409 depends on it -- the
    deploy step copies the Sphinx build over the corpus output and ships the
    lot, with no step of its own for the site.
    """

    def testTheDefaultPathIsTheOutputDirectory(self):
        from pysmi.scripts.mibcorpus import _outputs_for

        outputs = _outputs_for("output", ["json", "site"])

        self.assertEqual(os.path.join("output", ""), outputs.site)
        self.assertEqual(os.path.join("output", "json"), outputs.json)

    def testItIsStillOptIn(self):
        """The default layout is what pysnmp/mibs published before there was a
        site, and rendering 7,000 pages is not something a plain run pays."""
        from pysmi.scripts.mibcorpus import _outputs_for

        self.assertIsNone(_outputs_for("output", None).site)

    def testAPathOfItsOwnIsTakenAsGiven(self):
        from pysmi.scripts.mibcorpus import _outputs_for

        self.assertEqual("elsewhere", _outputs_for("output", ["site:elsewhere"]).site)
