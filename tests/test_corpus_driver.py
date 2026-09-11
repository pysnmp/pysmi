#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""A corpus build is reproducible, or it is not a corpus build.

The shell pipeline this driver replaces had four properties that made its
output depend on things other than its input: it read a directory every one of
its parallel jobs was writing into, it resolved missing dependencies from its
own last publish over the network, it set ``--ignore-errors`` on one pass of
three, and its index resolved collisions by ``os.listdir`` order.

These tests pin the driver's answers to all four, as properties rather than as
golden files: two runs agree, a run with no network succeeds, every output
format describes the same module set, and a module more than one namespace
holds resolves the same way whichever namespace is processed first.

See pysnmp/pysmi#182.
"""

import json
import os
import shutil
import sqlite3
import tempfile
import textwrap
import unittest
from unittest import mock

from pysmi import error
from pysmi.corpus import CorpusDriver, CorpusOutputs, Namespace, check_disjoint
from pysmi.corpus.driver import STANDARD_TXT_EXCLUDED_PREFIXES, CorpusReport
from pysmi.mibinfo import source_digest
from pysmi.registry.pen import Registrant
from pysmi.registry.smi import ArcName


def module(name, oid, *, revision="202401010000Z", description="a module"):
    """A minimal module that compiles, on its own arc under enterprises."""
    symbol = name.lower().replace("-", "")

    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, OBJECT-TYPE, Integer32, enterprises
                FROM SNMPv2-SMI;

        {symbol}MI MODULE-IDENTITY
            LAST-UPDATED "{revision}"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "{description}"
            ::= {{ enterprises {oid} }}

        {symbol}Object OBJECT-TYPE
            SYNTAX      Integer32
            MAX-ACCESS  read-only
            STATUS      current
            DESCRIPTION "{description}"
            ::= {{ {symbol}MI 1 }}
        END
        """
    )


def grouped():
    """A module that declares an OBJECT-IDENTITY group under its own anchor.

    The ordinary shape of a vendor MIB, and what makes the OID index far
    larger than the registration tree: over pysnmp/mibs, 5,438 modules
    contribute 98,867 indexed arcs between them, nearly all of them group
    nodes like this one.
    """
    return textwrap.dedent(
        """\
        GROUPED-MIB DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, OBJECT-IDENTITY, OBJECT-TYPE, Integer32,
            enterprises
                FROM SNMPv2-SMI;

        groupedMI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "a module with a group node"
            ::= { enterprises 77 }

        groupedObjects OBJECT-IDENTITY
            STATUS      current
            DESCRIPTION "the group everything hangs off"
            ::= { groupedMI 1 }

        groupedThing OBJECT-TYPE
            SYNTAX      Integer32
            MAX-ACCESS  read-only
            STATUS      current
            DESCRIPTION "a thing"
            ::= { groupedObjects 1 }
        END
        """
    )


def squatter():
    """A vendor module registering itself on SNMPv2-MIB's own arc."""
    return textwrap.dedent(
        """\
        SQUATTER-MIB DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, OBJECT-TYPE, Integer32, snmpModules
                FROM SNMPv2-SMI;

        squatterMI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "sits on 1.3.6.1.6.3.1, which SNMPv2-MIB owns"
            ::= { snmpModules 1 }

        squatterObject OBJECT-TYPE
            SYNTAX      Integer32
            MAX-ACCESS  read-only
            STATUS      current
            DESCRIPTION "an object"
            ::= { squatterMI 99 }
        END
        """
    )


#: A module that does not parse. Vendors publish these; a corpus build has to
#: carry on past them and say so, rather than subtract them silently.
BROKEN = "BROKEN-MIB DEFINITIONS ::= BEGIN this is not SMI at all\n"


class CorpusTestCase(unittest.TestCase):
    """A scratch corpus of two vendor namespaces, one of them defective."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.src = os.path.join(self.root, "src")

        self.write("alpha", "ALPHA-MIB", module("ALPHA-MIB", 41))
        self.write("beta", "BETA-MIB", module("BETA-MIB", 42))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, namespace, name, text):
        """Put one module into one namespace directory."""
        directory = os.path.join(self.src, namespace)
        os.makedirs(directory, exist_ok=True)

        with open(os.path.join(directory, name), "w") as fileObj:
            fileObj.write(text)

    def namespaces(self, *names, tier="vendor"):
        """The namespaces named, in the order given."""
        return [
            Namespace(x, os.path.join(self.src, x), tier)
            for x in (names or ("alpha", "beta"))
        ]

    def outputs(self, where="output", **kwargs):
        """The full published layout under a scratch directory."""
        out = os.path.join(self.root, where)
        layout = {
            "asn1": os.path.join(out, "asn1"),
            "notexts": os.path.join(out, "notexts"),
            "texts": os.path.join(out, "texts"),
            "json": os.path.join(out, "json"),
            "index": os.path.join(out, "index.csv"),
            "ranked_index": os.path.join(out, "index-v2.csv"),
            "standard": os.path.join(out, "standard.txt"),
            "closure": os.path.join(out, "closure.json"),
            "report": os.path.join(out, "report.json"),
        }
        layout.update(kwargs)

        return CorpusOutputs(**layout)

    def tree(self, where="output"):
        """Every published file under an output directory, mapped to its bytes.

        ``report.json`` is left out: it is the build's log, and it records
        how long each phase took. Every artifact the corpus publishes is
        here.
        """
        base = os.path.join(self.root, where)
        found = {}

        for root, _, files in os.walk(base):
            for name in sorted(files):
                if name == "report.json":
                    continue

                path = os.path.join(root, name)

                with open(path, "rb") as fileObj:
                    found[os.path.relpath(path, base)] = fileObj.read()

        return found


class JsonTextsTestCase(CorpusTestCase):
    """Prose in the jsondoc tree, when a build asks for it (pysnmp/pysmi#277).

    A published jsondoc carries names, OIDs, syntax, access and status and no
    prose, though the texts are 38% of a MIB. A consumer that wants a
    DESCRIPTION has to fetch and parse the ASN.1, which means a second SMI
    parser for prose the compiler already read.
    """

    def rendered(self, where="output"):
        with open(
            os.path.join(self.root, where, "json", "ALPHA-MIB.json"), encoding="utf-8"
        ) as fileObj:
            return json.load(fileObj)

    def outputs_json(self, where="output", **kwargs):
        out = os.path.join(self.root, where)
        layout = {"json": os.path.join(out, "json")}
        layout.update(kwargs)

        return CorpusOutputs(**layout)

    def testTheTreeCarriesNoProseByDefault(self):
        """What it has always held, and what it holds unless asked."""
        CorpusDriver(self.namespaces(), self.outputs_json()).run()

        self.assertNotIn("description", self.rendered()["alphamibObject"])

    def testAskingForTextsPutsThemInTheTree(self):
        out = os.path.join(self.root, "output")

        CorpusDriver(
            self.namespaces(),
            CorpusOutputs(json_texts=os.path.join(out, "json")),
        ).run()

        self.assertEqual("a module", self.rendered()["alphamibObject"]["description"])

    def testAskingForTextsAloneIsOneCompilePass(self):
        """Prose without a second pass over the corpus, which is the point."""
        driver = CorpusDriver(
            self.namespaces(),
            CorpusOutputs(json_texts=os.path.join(self.root, "output", "json")),
        )

        self.assertEqual(["json-texts"], [x.name for x in driver._destinations()])

    def testBothTreesCanBeBuiltAtOnce(self):
        """A build publishing a lean tree and rendering from a complete one.

        The issue asks for both options, so neither may exclude the other.
        """
        driver = CorpusDriver(
            self.namespaces(),
            self.outputs_json(json_texts=os.path.join(self.root, "output", "full")),
        )

        self.assertEqual(
            ["json", "json-texts"], [x.name for x in driver._destinations()]
        )

    def testTheProjectionsReadTheTreeTheBuildHas(self):
        """A build that asked only for the tree with texts in it still gets an
        index, from that tree rather than from a second pass."""
        out = os.path.join(self.root, "output")
        outputs = CorpusOutputs(
            json_texts=os.path.join(out, "json"),
            ranked_index=os.path.join(out, "index-v2.csv"),
        )

        CorpusDriver(self.namespaces(), outputs).run()

        with open(outputs.ranked_index, encoding="utf-8") as fileObj:
            self.assertIn("ALPHA-MIB", fileObj.read())

    def testTheLayoutIsNotKept(self):
        """genTexts and keepTextsLayout stay separate: a JSON consumer wants
        the text normalised rather than the publisher's line breaks."""
        driver = CorpusDriver(
            self.namespaces(),
            CorpusOutputs(json_texts=os.path.join(self.root, "output", "json")),
        )
        destination = driver._destinations()[0]

        self.assertTrue(destination.genTexts)
        self.assertFalse(destination.keepTextsLayout)


class ProvenanceTestCase(CorpusTestCase):
    """Where each published module came from (pysnmp/pysmi#278).

    The build resolves every module in order to stage it, so it knows which
    namespace supplied the copy that won, which file it read and what that
    file's digest was. None of it used to survive the build.
    """

    def testEveryStagedModuleHasAnOrigin(self):
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(["ALPHA-MIB", "BETA-MIB"], sorted(report.provenance))

    def testTheOriginNamesTheNamespaceThatSuppliedIt(self):
        """Two namespaces are two directories under one root here, which is why
        the path alone cannot answer it."""
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual("alpha", report.provenance["ALPHA-MIB"]["namespace"])
        self.assertEqual("beta", report.provenance["BETA-MIB"]["namespace"])

    def testTheFileIsRelativeToItsNamespace(self):
        """An absolute path would carry the directory this build ran in, which
        differs between two builds of one source tree."""
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual("ALPHA-MIB", report.provenance["ALPHA-MIB"]["file"])
        self.assertNotIn(self.root, report.provenance["ALPHA-MIB"]["file"])

    def testTheDigestIsOfTheTextThatWasStaged(self):
        """The provenance has to be true of the ASN.1 published beside it."""
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        with open(
            os.path.join(self.root, "output", "asn1", "ALPHA-MIB"),
            encoding="utf-8",
            newline="",
        ) as fileObj:
            staged = fileObj.read()

        self.assertEqual(
            source_digest(staged), report.provenance["ALPHA-MIB"]["digest"]
        )

    def testTheShadowedModuleIsRecordedAsComingFromTheWinner(self):
        """Shadowing says which copies lost; provenance says which one won."""
        self.write("beta", "ALPHA-MIB", module("ALPHA-MIB", 41, description="other"))

        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertIn("ALPHA-MIB", report.shadowed)
        self.assertEqual("alpha", report.provenance["ALPHA-MIB"]["namespace"])

    def testItReachesTheDatabase(self):
        outputs = self.outputs(core_db=os.path.join(self.root, "output", "core.db"))

        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertEqual(2, report.db["provenance"])

        connection = sqlite3.connect(outputs.core_db)

        try:
            rows = dict(connection.execute("SELECT module, namespace FROM provenance"))

        finally:
            connection.close()

        self.assertEqual({"ALPHA-MIB": "alpha", "BETA-MIB": "beta"}, rows)

    def testTheDatabaseGetsItWithoutTheAsn1Tree(self):
        """Staging answers provenance for free; a build that did not stage
        pays one resolution pass for it rather than going without."""
        outputs = self.outputs(
            asn1=None, core_db=os.path.join(self.root, "output", "core.db")
        )

        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertEqual(0, report.staged)
        self.assertEqual(2, report.db["provenance"])
        self.assertEqual(["ALPHA-MIB", "BETA-MIB"], sorted(report.provenance))

    def testAPackageNamespaceIsNamedRatherThanLeftBlank(self):
        """A namespace over ``pysmi.mibs.asn1`` is served by the compiler's
        own priority reader, not by the one this driver built for it, so the
        reader that answers is a different object with the same job.
        Identifying the namespace by object identity alone reported nothing
        for all 210 bundled modules -- found building pysnmp/mibs against
        5.0.0-rc.1, where every standard-tier row carried an empty namespace.
        """
        namespaces = [
            Namespace("standard", "package:pysmi.mibs.asn1", "standard"),
            *self.namespaces(),
        ]

        report = CorpusDriver(namespaces, self.outputs()).run()

        self.assertEqual("standard", report.provenance["SNMPv2-SMI"]["namespace"])
        self.assertEqual("alpha", report.provenance["ALPHA-MIB"]["namespace"])

    def testEveryModuleGetsANamespace(self):
        """The weaker statement the one above is an instance of: a module in
        the corpus came from one of its namespaces, and provenance that
        cannot say which is provenance that answers nothing."""
        namespaces = [
            Namespace("standard", "package:pysmi.mibs.asn1", "standard"),
            *self.namespaces(),
        ]

        report = CorpusDriver(namespaces, self.outputs()).run()
        declared = {x.name for x in namespaces}

        self.assertNotEqual({}, report.provenance)

        for name, origin in report.provenance.items():
            with self.subTest(module=name):
                self.assertIn(origin["namespace"], declared)

    def testABuildThatAsksForNeitherRecordsNothing(self):
        """Provenance costs a resolution pass. A build wanting neither the
        tree nor the database does not pay it to fill in a report field."""
        outputs = CorpusOutputs(
            json=os.path.join(self.root, "output", "json"),
            report=os.path.join(self.root, "output", "report.json"),
        )

        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertEqual({}, report.provenance)


class ImportClosureTestCase(CorpusTestCase):
    """The files a consumer needs in order to load a module (pysnmp/pysmi#280).

    The build resolves every import edge in order to compile, so it is the
    build that writes the closure down rather than every reader re-walking a
    table for it.
    """

    def closure(self, where="output"):
        """The artifact this build wrote."""
        with open(
            os.path.join(self.root, where, "closure.json"), encoding="utf-8"
        ) as fileObj:
            return json.load(fileObj)["closure"]

    def testItIsPartOfThePublishedLayout(self):
        """No --emit needed: it is a projection of a tree the build reads anyway."""
        CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertIn("ALPHA-MIB", self.closure())

    def testAModuleIsInItsOwnClosure(self):
        """Which makes the artifact directly usable as a file list."""
        CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertIn("ALPHA-MIB", self.closure()["ALPHA-MIB"]["files"])

    def testTheClosureIsEveryFileTheModuleNeeds(self):
        """These modules import SNMPv2-SMI, which imports two more.

        The closure is the file list, so it carries what the edges reach and
        not only the edges themselves.
        """
        CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(
            ["ALPHA-MIB", "SNMPv2-CONF", "SNMPv2-SMI", "SNMPv2-TC"],
            self.closure()["ALPHA-MIB"]["files"],
        )

    def testACompleteCorpusReportsNothingMissing(self):
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(0, report.closure["incomplete"])
        self.assertEqual([], self.closure()["ALPHA-MIB"]["missing"])

    def testItIsNotWrittenUnlessAskedFor(self):
        outputs = self.outputs()
        outputs.closure = None

        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertEqual({}, report.closure)
        self.assertFalse(
            os.path.exists(os.path.join(self.root, "output", "closure.json"))
        )


class ArcNamesTestCase(CorpusTestCase):
    """What every arc the corpus reaches is called (pysnmp/pysmi#288).

    These modules register under ``enterprises`` -- 1.3.6.1.4.1 -- so the path
    to them runs through arcs no module registers and the OID index attributes
    to whichever module mentioned them.
    """

    def outputs_arcs(self, **kwargs):
        out = os.path.join(self.root, "output")
        layout = {
            "json": os.path.join(out, "json"),
            "arcs": os.path.join(out, "arcs.json"),
        }
        layout.update(kwargs)

        return CorpusOutputs(**layout)

    def written(self):
        with open(
            os.path.join(self.root, "output", "arcs.json"), encoding="utf-8"
        ) as fileObj:
            return json.load(fileObj)["arc"]

    def testAnArcInsideAModuleIsNotANodeOfTheTree(self):
        """pysnmp/pysmi#301: the driver handed the whole OID index here, and
        a module's OBJECT-IDENTITY group nodes are in it -- so the arc index
        carried every group every module declares. Over pysnmp/mibs that was
        98,903 arcs and an 11 MB artifact against 14,752 and about 1.6 MB.

        A group node under a module's own registration is a thing inside that
        module, which the module page renders in context.
        """
        self.write("alpha", "GROUPED-MIB", grouped())

        CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        written = self.written()

        self.assertIn("1.3.6.1.4.1.77", written)
        self.assertNotIn("1.3.6.1.4.1.77.1", written)

    def testEveryArcIsARegistrationOrAboveOne(self):
        self.write("alpha", "GROUPED-MIB", grouped())

        CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        for arc in self.written():
            with self.subTest(arc=arc):
                self.assertNotRegex(arc, r"^1\.3\.6\.1\.4\.1\.\d+\.\d")

    def testThePathToAModuleIsNamed(self):
        CorpusDriver(
            self.namespaces(),
            self.outputs_arcs(),
            smiRegistry={"1.3": ArcName("1.3", "org", "https://iana/smi")},
        ).run()

        found = self.written()

        self.assertEqual("org", found["1.3"]["name"])
        self.assertEqual("registry", found["1.3"]["source"])

    def testAnArcAStandardNamesIsCitedRatherThanRegistered(self):
        """A cited name and a registered one are different kinds of fact, and
        a page has to be able to render them differently."""
        CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        self.assertEqual("standard", self.written()["1.3"]["source"])

    def testAModuleDescriptorIsLabelledAsOne(self):
        """SNMPv2-SMI defines "private" at 1.3.6.1.4 and the corpus compiles
        it, so a descriptor names the arc. That is a weaker fact than a
        registration and the artifact says which it is -- which is the whole
        point: the index used to present the two identically."""
        CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        found = self.written()["1.3.6.1.4"]

        self.assertEqual("private", found["name"])
        self.assertEqual("module", found["source"])

    def testTheRegistryDisplacesTheDescriptor(self):
        """The defect this exists to fix: a name read off whichever module
        mentioned an arc, standing where the authority's name should."""
        CorpusDriver(
            self.namespaces(),
            self.outputs_arcs(),
            smiRegistry={
                "1.3.6.1.4": ArcName("1.3.6.1.4", "private", "https://iana/smi")
            },
        ).run()

        self.assertEqual("registry", self.written()["1.3.6.1.4"]["source"])

    def testAModuleDescriptorNamesAnArcNothingElseDoes(self):
        """The weakest source, and now labelled as what it is rather than
        standing in the index as though it were a registration."""
        CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        found = self.written()["1.3.6.1.4.1.41"]

        self.assertEqual("alphamibMI", found["name"])
        self.assertEqual("module", found["source"])
        self.assertEqual("ALPHA-MIB", found["reference"])

    def testTheEnterpriseRegistryNamesTheBareArc(self):
        """No module registers a vendor's bare arc, only what hangs beneath."""
        CorpusDriver(
            self.namespaces(),
            self.outputs_arcs(),
            oidRegistry={41: Registrant(41, "Acme Networks")},
        ).run()

        found = self.written()

        self.assertEqual("Acme Networks", found["1.3.6.1.4.1.41"]["name"])
        self.assertEqual("registry", found["1.3.6.1.4.1.41"]["source"])

    def testTheReportCountsBySource(self):
        report = CorpusDriver(self.namespaces(), self.outputs_arcs()).run()

        self.assertEqual(report.arcs["arcs"], len(self.written()))
        self.assertIn("standard", report.arcs)

    def testItIsNotWrittenUnlessAskedFor(self):
        outputs = self.outputs_arcs()
        outputs.arcs = None

        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertEqual({}, report.arcs)


class RepeatabilityTestCase(CorpusTestCase):
    """Two runs over identical input produce identical output."""

    def testTwoRunsAgreeByteForByte(self):
        CorpusDriver(self.namespaces(), self.outputs("first")).run()
        CorpusDriver(self.namespaces(), self.outputs("second")).run()

        self.assertEqual(self.tree("first"), self.tree("second"))

    def testARerunOverItsOwnOutputAgreesToo(self):
        # The interesting half: the second run finds output already there,
        # which is where a build that skips what looks up to date stops being
        # a build of the corpus it reports.
        CorpusDriver(self.namespaces(), self.outputs()).run()
        first = self.tree()

        CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(first, self.tree())


class OfflineTestCase(CorpusTestCase):
    """A run with no network access succeeds."""

    def testNoHttpReaderIsEverConstructed(self):
        # Not a mock of the socket layer: the point is that the driver has no
        # code path that reaches for the network, so the assertion is that
        # nothing that could is instantiated.
        from pysmi.reader import httpclient

        with mock.patch.object(
            httpclient.HttpReader,
            "__init__",
            side_effect=AssertionError("a corpus build must not fetch"),
        ):
            report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(2, report.staged)

    def testNoBorrowerIsConfigured(self):
        # mibdump defaults to borrowing a pre-compiled module from
        # pysnmp.github.io when compilation fails. A corpus build that did
        # that would bootstrap off its own last publish, which is how a bad
        # publish perpetuates itself.
        driver = CorpusDriver(self.namespaces(), self.outputs())

        for destination in driver._destinations():
            compiler = driver._compiler_for(destination)

            self.assertEqual([], compiler._borrowers)

    def testAUrlNamespaceIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            CorpusDriver,
            [Namespace("web", "https://example.invalid/mibs/@mib@", "vendor")],
            self.outputs(),
        )


class SharedDirectoryTestCase(CorpusTestCase):
    """Nothing is written into a directory that is also a source."""

    def testWritingIntoASourceIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            CorpusDriver,
            self.namespaces(),
            self.outputs(asn1=os.path.join(self.src, "alpha")),
        )

    def testWritingBelowASourceIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            CorpusDriver,
            self.namespaces(),
            self.outputs(json=os.path.join(self.src, "alpha", "json")),
        )

    def testWritingAboveASourceIsRefused(self):
        # The other direction matters just as much: an output directory that
        # contains a source is a build that can overwrite its own inputs.
        self.assertRaises(
            error.PySmiError,
            check_disjoint,
            self.namespaces(),
            CorpusOutputs(asn1=self.src),
        )

    def testSourcesAreUnchangedByABuild(self):
        before = {}

        for root, _, files in os.walk(self.src):
            for name in files:
                path = os.path.join(root, name)

                with open(path, "rb") as fileObj:
                    before[path] = fileObj.read()

        CorpusDriver(self.namespaces(), self.outputs()).run()

        after = {}

        for root, _, files in os.walk(self.src):
            for name in files:
                path = os.path.join(root, name)

                with open(path, "rb") as fileObj:
                    after[path] = fileObj.read()

        self.assertEqual(before, after)


class ErrorPolicyTestCase(CorpusTestCase):
    """One error policy: every format keeps going, and the build says so."""

    def setUp(self):
        super().setUp()
        self.write("alpha", "BROKEN-MIB", BROKEN)

    def testADefectiveModuleDoesNotRemoveItsNamespace(self):
        # The shell build set --ignore-errors on the jsondoc pass alone, and
        # MibCompiler.compile() was all-or-nothing, so one defective module
        # took its whole namespace out of notexts/ and texts/ while json/
        # kept it. 41% of the vendor corpus was published that way.
        CorpusDriver(self.namespaces(), self.outputs()).run()

        for artifact, suffix in (
            ("notexts", ".py"),
            ("texts", ".py"),
            ("json", ".json"),
        ):
            self.assertTrue(
                os.path.exists(
                    os.path.join(self.root, "output", artifact, f"ALPHA-MIB{suffix}")
                ),
                f"ALPHA-MIB is missing from {artifact}",
            )

    def testEveryFormatDescribesTheSameModuleSet(self):
        CorpusDriver(self.namespaces(), self.outputs()).run()

        def names(artifact, suffix):
            directory = os.path.join(self.root, "output", artifact)

            return {
                x[: -len(suffix)] for x in os.listdir(directory) if x.endswith(suffix)
            }

        # The JSON tree also carries the base MIBs it compiles from the
        # bundle, which the pysnmp tree takes from pysnmp instead; what has
        # to agree is this corpus's own modules.
        ours = {"ALPHA-MIB", "BETA-MIB"}

        self.assertEqual(ours, names("notexts", ".py") & ours)
        self.assertEqual(ours, names("texts", ".py") & ours)
        self.assertEqual(ours, names("json", ".json") & ours)

    def testTheFailureIsReported(self):
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        for destination in ("notexts", "texts", "json"):
            self.assertIn("BROKEN-MIB", report.failed[destination])

    def testTheReportIsWrittenOut(self):
        CorpusDriver(self.namespaces(), self.outputs()).run()

        with open(os.path.join(self.root, "output", "report.json")) as fileObj:
            report = json.load(fileObj)

        self.assertIn("BROKEN-MIB", report["failed"]["json"])
        self.assertEqual(2, len(report["namespaces"]))


class PrecedenceTestCase(CorpusTestCase):
    """Which copy of a shared name wins does not depend on scheduling."""

    def setUp(self):
        super().setUp()
        # The same module name in both namespaces, at different revisions.
        # In the shell build, which one reached output/asn1 -- and therefore
        # which one everything else compiled against -- was decided by which
        # parallel job finished last.
        self.write(
            "alpha",
            "SHARED-MIB",
            module("SHARED-MIB", 51, revision="201001010000Z", description="older"),
        )
        self.write(
            "beta",
            "SHARED-MIB",
            module("SHARED-MIB", 51, revision="202401010000Z", description="newer"),
        )

    def testTheNewestRevisionWinsWhicheverNamespaceIsFirst(self):
        forwards = CorpusDriver(
            self.namespaces("alpha", "beta"), self.outputs("forwards")
        ).run()
        backwards = CorpusDriver(
            self.namespaces("beta", "alpha"), self.outputs("backwards")
        ).run()

        for where in ("forwards", "backwards"):
            with open(os.path.join(self.root, where, "asn1", "SHARED-MIB")) as fileObj:
                self.assertIn("newer", fileObj.read())

        self.assertEqual(
            forwards.shadowed["SHARED-MIB"]["precedence"],
            backwards.shadowed["SHARED-MIB"]["precedence"],
        )

    def testTheStagedAsn1IsTheTextThatWasCompiled(self):
        # The published ASN.1 and the published JSON beside it have to be the
        # same module. In the shell build they were not guaranteed to be: the
        # compile read output/asn1 while other jobs wrote into it, and the
        # copy that landed there last was not necessarily the one used.
        CorpusDriver(self.namespaces(), self.outputs()).run()

        with open(os.path.join(self.root, "output", "asn1", "SHARED-MIB")) as fileObj:
            staged = fileObj.read()

        # The texts tree is where DESCRIPTION survives compilation, so it is
        # what can be compared against the ASN.1 word for word.
        with open(
            os.path.join(self.root, "output", "texts", "SHARED-MIB.py")
        ) as fileObj:
            compiled = fileObj.read()

        self.assertIn("newer", staged)
        self.assertIn("newer", compiled)
        self.assertNotIn("older", compiled)

    def testTheShadowedCopyIsNamed(self):
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        shadowed = report.shadowed["SHARED-MIB"]

        self.assertIn("alpha", shadowed["shadowed"][0])
        self.assertIn("beta", shadowed["used"])


class ArtifactTestCase(CorpusTestCase):
    """The legacy artifact set, as its consumers bind to it."""

    def testAsn1FilenamesAreBareModuleNames(self):
        # sc4snmp configures asn1/@mib@ and pysmi substitutes a bare module
        # name, so an extension makes every URL a 404.
        CorpusDriver(self.namespaces(), self.outputs()).run()

        published = os.listdir(os.path.join(self.root, "output", "asn1"))

        self.assertEqual({"ALPHA-MIB", "BETA-MIB"}, set(published))

    def testStandardTxtHoldsTheStandardTierLessItsExclusions(self):
        namespaces = [
            Namespace("base", "package:pysmi.mibs.asn1", "standard"),
            *self.namespaces(),
        ]

        CorpusDriver(namespaces, self.outputs()).run()

        with open(os.path.join(self.root, "output", "standard.txt")) as fileObj:
            names = fileObj.read().split()

        self.assertIn("IF-MIB", names)
        self.assertNotIn("ALPHA-MIB", names)
        self.assertEqual(names, sorted(names))
        self.assertEqual(
            [], [x for x in names if x.startswith(STANDARD_TXT_EXCLUDED_PREFIXES)]
        )

    def testTheLegacyIndexReplaysItsFrozenSnapshot(self):
        frozen = os.path.join(self.root, "index-frozen.csv")

        with open(frozen, "w") as fileObj:
            # A deliberately wrong answer, of the kind index-frozen.csv
            # carries on purpose, on an arc ALPHA-MIB owns.
            fileObj.write("BETA-MIB,1.3.6.1.4.1.41\n")

        CorpusDriver(self.namespaces(), self.outputs(frozen_index=frozen)).run()

        with open(os.path.join(self.root, "output", "index.csv")) as fileObj:
            legacy = dict(
                reversed(row.split(",")) for row in fileObj.read().splitlines()
            )

        with open(os.path.join(self.root, "output", "index-v2.csv")) as fileObj:
            ranked = dict(
                reversed(row.split(",")) for row in fileObj.read().splitlines()
            )

        self.assertEqual("BETA-MIB", legacy["1.3.6.1.4.1.41"])
        self.assertEqual("ALPHA-MIB", ranked["1.3.6.1.4.1.41"])

    def testAStandardModuleOutranksAVendorModuleOnTheSameArc(self):
        # The tier arrives declared, from the namespace, rather than being
        # inferred by walking a directory tree.
        #
        # 1.3.6.1.6.3.1 is SNMPv2-MIB's arc, and a vendor module registering
        # itself on top of it is exactly the collision the published index
        # gets wrong today: it resolves to RAPID-CITY, and sc4snmp loads
        # that module for it.
        self.write("alpha", "SQUATTER-MIB", squatter())

        report = CorpusDriver(
            [
                Namespace("base", "package:pysmi.mibs.asn1", "standard"),
                *self.namespaces(),
            ],
            self.outputs(),
        ).run()

        with open(os.path.join(self.root, "output", "index-v2.csv")) as fileObj:
            ranked = dict(
                reversed(row.split(",")) for row in fileObj.read().splitlines()
            )

        self.assertEqual("SNMPv2-MIB", ranked["1.3.6.1.6.3.1"])
        self.assertTrue(report.nodes["distinct"] <= report.nodes["defined"])

    def testAStaleDocumentIsNotIndexed(self):
        # An output directory left over from a build with a different input
        # set still holds JSON for modules this corpus does not carry.
        # Indexing the directory rather than the build is how MIB_INDEX comes
        # to name a module MIB_SOURCES answers 404 for.
        CorpusDriver(self.namespaces(), self.outputs()).run()

        stale = os.path.join(self.root, "output", "json", "GHOST-MIB.json")

        with open(stale, "w") as fileObj:
            json.dump(
                {
                    "ghostMI": {
                        "class": "moduleidentity",
                        "oid": "1.3.6.1.4.1.777",
                    }
                },
                fileObj,
            )

        CorpusDriver(self.namespaces(), self.outputs()).run()

        with open(os.path.join(self.root, "output", "index-v2.csv")) as fileObj:
            self.assertNotIn("GHOST-MIB", fileObj.read())

    def testTheNodeCountIsReported(self):
        # pysnmp/pysnmp#196 needs the post-dedup count measured and
        # pysnmp/pysmi#183 wants it before it freezes column widths, so the
        # build states both numbers rather than leaving them to be counted
        # afterwards.
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertLessEqual(report.nodes["distinct"], report.nodes["defined"])
        self.assertEqual(
            len(os.listdir(os.path.join(self.root, "output", "json"))),
            report.nodes["modules"],
        )


class CompactCorpusTestCase(CorpusTestCase):
    """A namespace can be resolved against without being carried.

    Two corpora come out of one source set. The one pysnmp/mibs publishes
    carries the standard modules, because its consumers fetch them from it.
    One built for a runtime that already has them -- pysmi bundles 210, and
    the wheel ships their compiled form -- carries only what that runtime
    lacks. Leaving the standard namespace out entirely is not the same thing:
    every vendor module that imports SNMPv2-SMI would fail.
    """

    def namespaces(self, *names, tier="vendor"):
        """The vendor namespaces, behind the bundle as a resolution source."""
        return [
            Namespace("base", "package:pysmi.mibs.asn1", "standard", publish=False),
            *super().namespaces(*names, tier=tier),
        ]

    def testAResolveOnlyNamespaceReachesNoOutputTree(self):
        CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual(
            {"ALPHA-MIB", "BETA-MIB"},
            set(os.listdir(os.path.join(self.root, "output", "asn1"))),
        )

        for artifact, suffix in (("notexts", ".py"), ("json", ".json")):
            names = os.listdir(os.path.join(self.root, "output", artifact))

            self.assertNotIn(f"SNMPv2-SMI{suffix}", names)
            self.assertNotIn(f"SNMPv2-TC{suffix}", names)
            self.assertIn(f"ALPHA-MIB{suffix}", names)

    def testItStillSuppliesWhatThePublishedModulesImport(self):
        # The whole point: ALPHA-MIB imports from SNMPv2-SMI and compiles.
        report = CorpusDriver(self.namespaces(), self.outputs()).run()

        self.assertEqual({}, report.failed["json"])
        self.assertEqual(2, report.staged)

    def testTheModulesItCarriesAreTheSameEitherWay(self):
        # A compact corpus is a subset of the full one, not a different
        # rendering of it: byte-identical per module.
        CorpusDriver(self.namespaces(), self.outputs("compact")).run()
        CorpusDriver(
            [
                Namespace("base", "package:pysmi.mibs.asn1", "standard"),
                *CorpusTestCase.namespaces(self),
            ],
            self.outputs("full"),
        ).run()

        for artifact in (
            "asn1/ALPHA-MIB",
            "json/ALPHA-MIB.json",
            "notexts/ALPHA-MIB.py",
        ):
            with self.subTest(artifact=artifact):
                with open(
                    os.path.join(self.root, "compact", artifact), "rb"
                ) as fileObj:
                    compact = fileObj.read()

                with open(os.path.join(self.root, "full", artifact), "rb") as fileObj:
                    full = fileObj.read()

                self.assertEqual(full, compact)

    def testTheIndexCoversOnlyWhatIsCarried(self):
        CorpusDriver(self.namespaces(), self.outputs()).run()

        with open(os.path.join(self.root, "output", "index-v2.csv")) as fileObj:
            modules = {row.split(",")[0] for row in fileObj.read().splitlines()}

        self.assertEqual({"ALPHA-MIB", "BETA-MIB"}, modules)

    def testACorpusOfNothingButResolutionSourcesIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            CorpusDriver,
            [Namespace("base", "package:pysmi.mibs.asn1", "standard", publish=False)],
            self.outputs(),
        )

    def testAModuleAPublishedNamespaceAlsoHoldsIsStillCarried(self):
        # Stubbing is for what only a resolution source has. A module the
        # corpus holds a copy of is the corpus's, and which copy is used is
        # the precedence rule's business rather than this one's.
        self.write("extra", "SHARED-MIB", module("SHARED-MIB", 61))
        self.write("alpha", "SHARED-MIB", module("SHARED-MIB", 61))

        namespaces = [
            Namespace(
                "extra", os.path.join(self.src, "extra"), "vendor", publish=False
            ),
            *self.namespaces(),
        ]
        driver = CorpusDriver(namespaces, self.outputs())

        self.assertNotIn("SHARED-MIB", driver._resolve_only_modules())

    def testAModuleOnlyAResolutionSourceHoldsIsStubbed(self):
        self.write("extra", "ONLY-THERE-MIB", module("ONLY-THERE-MIB", 62))

        namespaces = [
            Namespace(
                "extra", os.path.join(self.src, "extra"), "vendor", publish=False
            ),
            *self.namespaces(),
        ]
        driver = CorpusDriver(namespaces, self.outputs())

        self.assertIn("ONLY-THERE-MIB", driver._resolve_only_modules())


class StubTestCase(CorpusTestCase):
    """What a destination is told not to generate."""

    def testTheDefaultIsWhatMibdumpStubs(self):
        driver = CorpusDriver(self.namespaces(), self.outputs())
        compiler = driver._compiler_for(driver._destinations()[0])

        stubbed = compiler._searchers[0]._mibnames

        self.assertIn("SNMPv2-SMI", stubbed)
        self.assertIn("SNMP-FRAMEWORK-MIB", stubbed)

    def testTheStubListIsAKnob(self):
        # A caller generating the base layer itself wants a narrower list:
        # most of the base MIBs generate perfectly well, and only the three
        # the generator unconditionally imports *from* genuinely cannot.
        # hatch_build.py is that caller. See pysnmp/pysmi#196.
        driver = CorpusDriver(
            self.namespaces(),
            self.outputs(),
            stubs={"pysnmp": ["SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF"]},
        )
        compiler = driver._compiler_for(driver._destinations()[0])

        stubbed = compiler._searchers[0]._mibnames

        self.assertIn("SNMPv2-SMI", stubbed)
        self.assertNotIn("SNMP-FRAMEWORK-MIB", stubbed)

    def testAnEmptyStubListMeansStubNothing(self):
        # Distinct from not configuring one at all, which means the default.
        driver = CorpusDriver(self.namespaces(), self.outputs(), stubs={"pysnmp": []})
        compiler = driver._compiler_for(driver._destinations()[0])

        self.assertEqual((), compiler._searchers[0]._mibnames)


class InputSetTestCase(CorpusTestCase):
    """What the driver refuses before it starts."""

    def testAnEmptyInputSetIsRefused(self):
        self.assertRaises(error.PySmiError, CorpusDriver, [], self.outputs())

    def testASourceThatIsNotADirectoryIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            CorpusDriver,
            [Namespace("nowhere", os.path.join(self.root, "nowhere"), "vendor")],
            self.outputs(),
        )

    def testTheDatabaseIsBuiltWhenAskedFor(self):
        outputs = self.outputs(core_db=os.path.join(self.root, "output", "core.db"))
        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertTrue(os.path.exists(outputs.core_db))
        self.assertGreater(report.db["module"], 0)
        self.assertEqual(report.db["node"], report.db["node"])

    def testTheDatabaseIsNotBuiltUnlessAskedFor(self):
        # Building one costs a pass over the whole jsondoc tree, so the
        # default layout must not pay for it.
        outputs = self.outputs()
        report = CorpusDriver(self.namespaces(), outputs).run()

        self.assertIsNone(outputs.core_db)
        self.assertEqual(report.db, {})

    def testTheBuildIsStampedWithWhatTheCallerGaveIt(self):
        # write_db has taken these since it was written, and until now nothing
        # could pass them: no driver argument, no command-line option. A
        # database nothing can stamp leaves corpus_version unset for every
        # build mibcorpus produces, so a consumer cannot tell two apart.
        outputs = self.outputs(core_db=os.path.join(self.root, "output", "core.db"))
        CorpusDriver(
            self.namespaces(),
            outputs,
            corpusVersion="2.1.0",
            corpusId="pysnmp/mibs",
        ).run()

        connection = sqlite3.connect(outputs.core_db)

        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))

        finally:
            connection.close()

        self.assertEqual(meta["corpus_version"], "2.1.0")
        self.assertEqual(meta["corpus_id"], "pysnmp/mibs")

    def testAnUnstampedBuildSaysSoRatherThanInventingOne(self):
        # A version taken from a clock or a checkout would make two builds of
        # one source tree differ, which is the property write_db exists to
        # preserve.
        outputs = self.outputs(core_db=os.path.join(self.root, "output", "core.db"))
        CorpusDriver(self.namespaces(), outputs).run()

        connection = sqlite3.connect(outputs.core_db)

        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))

        finally:
            connection.close()

        self.assertIsNone(meta.get("corpus_version"))
        self.assertIsNone(meta.get("corpus_id"))

    def testTheCorpusCacheIsKeyedByWhatWasAskedFor(self):
        # write_index and write_db both read the jsondoc tree, and the read is
        # cached so a 5,000-module tree is not read twice. Caching the first
        # answer under every selector would make a narrow call poison a wide
        # one: an index over one module followed by a database over all of
        # them would write only that module.
        outputs = self.outputs(core_db=os.path.join(self.root, "output", "core.db"))
        driver = CorpusDriver(self.namespaces(), outputs)
        report = CorpusReport()

        driver.stage(report)
        driver.compile(report)

        driver.write_index(report, ["ALPHA-MIB"])
        driver.write_db(report, None)

        connection = sqlite3.connect(outputs.core_db)

        try:
            modules = {x[0] for x in connection.execute("SELECT name FROM module")}

        finally:
            connection.close()

        self.assertIn("ALPHA-MIB", modules)
        self.assertIn("BETA-MIB", modules)

    def testAnIndexWithoutJsonStagesOneForItself(self):
        # Until pysnmp/pysmi#262 this was refused, and a caller wanting an
        # index alone had to name a scratch path for a jsondoc tree it did
        # not want and remove it afterwards. The dependency is pysmi's, so
        # pysmi carries it.
        path = os.path.join(self.root, "output", "index.csv")

        CorpusDriver(self.namespaces(), CorpusOutputs(index=path)).run()

        self.assertTrue(os.path.isfile(path))
        self.assertEqual(["index.csv"], os.listdir(os.path.dirname(path)))

    def testWritingAnIndexDirectlyStillNeedsATreeToProjectFrom(self):
        # run() is what stages one. The methods under it take the outputs
        # they are given and cannot invent a tree that is not there.
        driver = CorpusDriver(
            self.namespaces(),
            CorpusOutputs(index=os.path.join(self.root, "output", "index.csv")),
        )

        self.assertRaises(error.PySmiError, driver.write_index, CorpusReport())
