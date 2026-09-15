#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""A corpus may carry a few of its modules and resolve against the rest.

``"publish": false`` narrows a build by namespace: the standard modules
supply what the vendor modules import and reach no output tree, which is what
makes the compact corpus a corpus. ``select`` is the same narrowing by
module, and it exists for a question a namespace cannot express: *what do the
three modules this change touched look like?*

The answer has to come from a compile that resolved those modules' imports
against the whole corpus. A build over the three changed files alone would
fail on every import they make, and a build over all 5,510 answers the
question in five minutes and buries it in 7,430 pages. So the input set stays
whole and the output set narrows, and the property that makes it worth
anything is the one the compact corpus rests on too: a module built narrowed
is byte for byte the module built whole.

See pysnmp/pysmi#316.
"""

import json
import os
import textwrap
import unittest

from pysmi import error
from pysmi.corpus import CorpusDriver

from .test_corpus_driver import BROKEN, CorpusTestCase


def importer(name, oid, imported):
    """A module that takes a textual convention from another vendor module."""
    symbol = name.lower().replace("-", "")

    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, OBJECT-TYPE, enterprises
                FROM SNMPv2-SMI
            TestString
                FROM {imported};

        {symbol}MI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "imports from a module the build may not carry"
            ::= {{ enterprises {oid} }}

        {symbol}Object OBJECT-TYPE
            SYNTAX      TestString
            MAX-ACCESS  read-only
            STATUS      current
            DESCRIPTION "a thing"
            ::= {{ {symbol}MI 1 }}
        END
        """
    )


def convention(name, oid):
    """A module defining the textual convention :py:func:`importer` wants."""
    symbol = name.lower().replace("-", "")

    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, enterprises
                FROM SNMPv2-SMI
            TEXTUAL-CONVENTION
                FROM SNMPv2-TC;

        {symbol}MI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "what the importer imports"
            ::= {{ enterprises {oid} }}

        TestString ::= TEXTUAL-CONVENTION
            STATUS      current
            DESCRIPTION "a string"
            SYNTAX      OCTET STRING
        END
        """
    )


class SelectionTestCase(CorpusTestCase):
    """A corpus of four vendor modules, two of which import a third."""

    def setUp(self):
        super().setUp()

        self.write("gamma", "GAMMA-TC-MIB", convention("GAMMA-TC-MIB", 43))
        self.write("gamma", "GAMMA-MIB", importer("GAMMA-MIB", 44, "GAMMA-TC-MIB"))

    def build(self, *selected, where="output", **kwargs):
        """Build the corpus, narrowed to *selected* when any is named."""
        return CorpusDriver(
            self.namespaces("alpha", "beta", "gamma"),
            self.outputs(where),
            select=selected or kwargs.pop("select", None),
            **kwargs,
        ).run()

    def published(self, where="output"):
        """The module names the ASN.1 tree carries."""
        return sorted(os.listdir(os.path.join(self.root, where, "asn1")))

    def report(self, where="output"):
        """The build's report, as it was written."""
        with open(os.path.join(self.root, where, "report.json")) as fileObj:
            return json.load(fileObj)


class CarriesWhatItSelectedTestCase(SelectionTestCase):
    """The output set narrows and the input set does not."""

    def testOnlyTheSelectedModulesAreCarried(self):
        """Every artifact, not just the one the narrowing was aimed at."""
        self.build("ALPHA-MIB")

        self.assertEqual(["ALPHA-MIB"], self.published())
        self.assertEqual(
            ["ALPHA-MIB.json"],
            sorted(os.listdir(os.path.join(self.root, "output", "json"))),
        )

        with open(os.path.join(self.root, "output", "index-v2.csv")) as fileObj:
            named = {x.strip().split(",")[-1] for x in fileObj if "," in x}

        self.assertNotIn("BETA-MIB", named)

    def testAModuleOutsideTheSelectionStillResolvesWhatIsInIt(self):
        """The point of the whole thing.

        GAMMA-MIB takes a textual convention from GAMMA-TC-MIB. Selecting
        the importer alone has to produce a compiled importer -- a build
        handed only that file would fail on the import.
        """
        report = self.build("GAMMA-MIB")

        self.assertEqual(["GAMMA-MIB"], self.published())
        self.assertEqual({}, report.failed["json"])
        self.assertEqual(1, report.modules)

    def testTheImportedModuleIsNotPublishedByBeingImported(self):
        """Resolving something is not carrying it.

        A dependency comes back from the compile as ``untouched``, which for
        a distribution build means the corpus already holds it. Under a
        selection it means the opposite, and reading it the first way staged
        fourteen files for a two-module preview.
        """
        self.build("GAMMA-MIB")

        self.assertEqual(["GAMMA-MIB"], self.published())

    def testTheReportCountsTheSelectionRatherThanTheNamespaces(self):
        self.build("ALPHA-MIB", "BETA-MIB")

        self.assertEqual(2, self.report()["modules"])
        self.assertEqual(2, self.report()["staged"])


class SameCorpusTestCase(SelectionTestCase):
    """A module built narrowed is the module built whole.

    The same claim ``"publish": false`` rests on, and for the same reason: if
    a narrowed build produces different bytes, a reader looking at a preview
    is looking at something other than what the corpus will publish, and the
    preview is worse than nothing.
    """

    def testTheAsn1IsTheSameBytes(self):
        self.build(where="whole")
        self.build("GAMMA-MIB", where="narrow")

        self.assertEqual(
            self.tree("whole")["asn1/GAMMA-MIB"],
            self.tree("narrow")["asn1/GAMMA-MIB"],
        )

    def testTheJsonIsTheSameBytes(self):
        self.build(where="whole")
        self.build("GAMMA-MIB", where="narrow")

        whole = self.tree("whole")["json/GAMMA-MIB.json"]
        narrow = self.tree("narrow")["json/GAMMA-MIB.json"]

        self.assertEqual(whole, narrow)

    def testTheNarrowedTreeIsASubsetOfTheWholeOne(self):
        """Every file the narrow build wrote, the whole build wrote too.

        Held per-module rather than over the tree: the indexes, the closure
        and the report are summaries of a module *set* and differ by design.
        """
        self.build(where="whole")
        self.build("ALPHA-MIB", "GAMMA-MIB", where="narrow")

        whole = self.tree("whole")
        narrow = self.tree("narrow")

        for path, data in narrow.items():
            if not path.startswith(("asn1/", "json/", "notexts/", "texts/")):
                continue

            self.assertIn(path, whole)
            self.assertEqual(whole[path], data, path)


class SelectionIsCheckedTestCase(SelectionTestCase):
    """A selection nobody can satisfy is an error, not a smaller corpus."""

    def testAModuleNoNamespaceHoldsIsRefused(self):
        with self.assertRaises(error.PySmiError) as caught:
            self.build("ALPHA-MIB", "NOT-A-MIB")

        self.assertIn("NOT-A-MIB", str(caught.exception))

    def testTheErrorNamesEveryMissingModuleRatherThanTheFirst(self):
        """A caller fixing its selection wants the whole list, once."""
        with self.assertRaises(error.PySmiError) as caught:
            self.build("MISSING-ONE-MIB", "MISSING-TWO-MIB")

        self.assertIn("MISSING-ONE-MIB", str(caught.exception))
        self.assertIn("MISSING-TWO-MIB", str(caught.exception))

    def testAnEmptySelectionIsRefused(self):
        """Distinct from no selection, which publishes everything.

        A caller that computed a set and computed it empty has not asked for
        a distribution build; it has asked for a corpus of nothing, and the
        answer is to say so rather than to publish 5,510 modules.
        """
        with self.assertRaises(error.PySmiError):
            CorpusDriver(self.namespaces("alpha"), self.outputs(), select=[])

    def testNoSelectionPublishesEverything(self):
        self.build()

        self.assertEqual(
            ["ALPHA-MIB", "BETA-MIB", "GAMMA-MIB", "GAMMA-TC-MIB"], self.published()
        )
        self.assertEqual({}, self.report()["selected"])


class SelectionReportTestCase(SelectionTestCase):
    """What was asked for, and what became of each."""

    def testItNamesWhatWasAskedForAndWhatArrived(self):
        self.build("ALPHA-MIB", "GAMMA-MIB")

        self.assertEqual(
            {
                "requested": ["ALPHA-MIB", "GAMMA-MIB"],
                "published": ["ALPHA-MIB", "GAMMA-MIB"],
                "failed": [],
            },
            self.report()["selected"],
        )

    def testAModuleThatDoesNotCompileIsReportedRatherThanMissing(self):
        """The failure a pull request check exists to catch.

        A selected module that will not compile has to come back named. It
        is absent from the tree either way; what distinguishes a broken MIB
        from one nobody asked for is this record.
        """
        self.write("delta", "BROKEN-MIB", BROKEN)

        CorpusDriver(
            self.namespaces("alpha", "beta", "gamma", "delta"),
            self.outputs(),
            select=["ALPHA-MIB", "BROKEN-MIB"],
        ).run()

        selected = self.report()["selected"]

        self.assertEqual(["ALPHA-MIB", "BROKEN-MIB"], selected["requested"])
        self.assertEqual(["ALPHA-MIB"], selected["published"])
        self.assertEqual(["BROKEN-MIB"], selected["failed"])
        self.assertEqual(["ALPHA-MIB"], self.published())

    def testAFileTooDamagedToNameItselfIsRefusedRatherThanCounted(self):
        """A module is what a file declares, and this file declares nothing.

        The distinction matters to a caller deriving its selection from file
        names. A MIB that will not compile is reported as failed; a file that
        is not a MIB at all -- a vendor's download page saved under a module
        name, which is how these arrive -- holds no module to report on, and
        saying so is more use than an empty page.
        """
        self.write("delta", "DELTA-MIB", "<html>not a MIB</html>\n")

        with self.assertRaises(error.PySmiError) as caught:
            CorpusDriver(
                self.namespaces("alpha", "delta"),
                self.outputs(),
                select=["DELTA-MIB"],
            ).run()

        self.assertIn("DELTA-MIB", str(caught.exception))


class NothingCompiledTestCase(SelectionTestCase):
    """A build whose whole selection failed still reports.

    The narrower the build, the likelier this is: a preview of the one module
    a pull request added, where that module does not compile, produces no
    jsondoc at all. Every artifact is a projection of that tree, and each of
    them used to end in a traceback out of ``os.listdir`` -- so the one case
    the check exists to catch was the one case it could not report.
    """

    def setUp(self):
        super().setUp()

        self.write("delta", "BROKEN-MIB", BROKEN)

    def testTheBuildFinishesAndNamesTheFailure(self):
        report = CorpusDriver(
            self.namespaces("alpha", "delta"),
            self.outputs(),
            select=["BROKEN-MIB"],
        ).run()

        self.assertEqual(0, report.modules)
        self.assertEqual(["BROKEN-MIB"], report.selected["failed"])
        self.assertEqual([], report.selected["published"])
        self.assertIn("BROKEN-MIB", report.failed["json"])

    def testTheSiteIsEmptyRatherThanATraceback(self):
        out = os.path.join(self.root, "site")

        CorpusDriver(
            self.namespaces("alpha", "delta"),
            self.outputs("site", asn1=None, notexts=None, texts=None, site=out),
            select=["BROKEN-MIB"],
        ).run()

        self.assertFalse(os.path.exists(os.path.join(out, "mib", "BROKEN-MIB")))


class SelectedSiteTestCase(SelectionTestCase):
    """The browse site of a narrowed build browses the narrowed set."""

    def testThePagesAreTheSelectedModulesAndNothingElse(self):
        out = os.path.join(self.root, "site")

        CorpusDriver(
            self.namespaces("alpha", "beta", "gamma"),
            self.outputs("site", asn1=None, notexts=None, texts=None, site=out),
            select=["GAMMA-MIB"],
        ).run()

        self.assertTrue(
            os.path.isfile(os.path.join(out, "mib", "GAMMA-MIB", "index.html"))
        )
        self.assertFalse(os.path.exists(os.path.join(out, "mib", "GAMMA-TC-MIB")))
        self.assertFalse(os.path.exists(os.path.join(out, "mib", "ALPHA-MIB")))

    def testTheListingNamesOnlyTheSelectedModules(self):
        out = os.path.join(self.root, "site")

        CorpusDriver(
            self.namespaces("alpha", "beta", "gamma"),
            self.outputs("site", asn1=None, notexts=None, texts=None, site=out),
            select=["GAMMA-MIB"],
        ).run()

        with open(os.path.join(out, "browse", "index.html")) as fileObj:
            listing = fileObj.read()

        self.assertIn("GAMMA-MIB", listing)
        self.assertNotIn("ALPHA-MIB", listing)


if __name__ == "__main__":
    unittest.main()
