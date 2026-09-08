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
import tempfile
import textwrap
import unittest
from unittest import mock

from pysmi import error
from pysmi.corpus import CorpusDriver, CorpusOutputs, Namespace, check_disjoint
from pysmi.corpus.driver import STANDARD_TXT_EXCLUDED_PREFIXES


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

    def testAnIndexWithoutJsonIsRefused(self):
        # The index is built from the jsondoc tree, so asking for one without
        # the other is a build that cannot produce what it was asked for.
        driver = CorpusDriver(
            self.namespaces(),
            CorpusOutputs(index=os.path.join(self.root, "output", "index.csv")),
        )

        self.assertRaises(error.PySmiError, driver.run)
