#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The ``mibcorpus`` command line.

A corpus build takes a source set and produces every artifact the corpus
publishes, which is a different shape of job from ``mibdump``'s "compile these
modules" -- so it is a different entry point rather than another destination
format. See the open question in :ref:`mibs-as-data`.
"""

import contextlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import textwrap
import unittest
from unittest import mock

from pysmi import error
from pysmi.corpus import db as corpus_db
from pysmi.scripts import mibcorpus


@contextlib.contextmanager
def _own_tempdir():
    """Point :py:mod:`tempfile` at a directory of our own, and yield it.

    What a build stages for itself goes somewhere ``tempfile`` chooses, so
    this is how a test sees whether anything was left behind without knowing
    the name it was staged under.
    """
    directory = tempfile.mkdtemp()
    previous = tempfile.tempdir
    tempfile.tempdir = directory

    try:
        yield directory

    finally:
        tempfile.tempdir = previous
        shutil.rmtree(directory, ignore_errors=True)


def module(name, oid):
    """A minimal module that compiles."""
    symbol = name.lower().replace("-", "")

    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, enterprises FROM SNMPv2-SMI;

        {symbol}MI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "a module"
            ::= {{ enterprises {oid} }}
        END
        """
    )


class ArgumentTestCase(unittest.TestCase):
    """What the command line means before anything is built."""

    def testANamespaceIsTierNameSource(self):
        namespace = mibcorpus._parse_namespace("vendor:cisco:/mibs/cisco")

        self.assertEqual(
            ("cisco", "/mibs/cisco", "vendor"),
            (
                namespace.name,
                namespace.source,
                namespace.tier,
            ),
        )

    def testAPackageSourceKeepsItsPrefix(self):
        namespace = mibcorpus._parse_namespace("standard:base:package:pysmi.mibs.asn1")

        self.assertEqual("package:pysmi.mibs.asn1", namespace.source)
        self.assertTrue(namespace.is_package)

    def testANamespaceIsPublishedByDefault(self):
        self.assertTrue(mibcorpus._parse_namespace("vendor:cisco:/mibs/cisco").publish)

    def testAResolveNamespaceIsNot(self):
        namespace = mibcorpus._parse_namespace(
            "standard:base:package:pysmi.mibs.asn1", publish=False
        )

        self.assertFalse(namespace.publish)

    def testTooFewFieldsIsRefused(self):
        self.assertRaises(
            error.PySmiError, mibcorpus._parse_namespace, "cisco:/mibs/cisco"
        )

    def testTheDefaultLayoutIsThePublishedOne(self):
        outputs = mibcorpus._outputs_for("out", None)

        self.assertEqual(os.path.join("out", "asn1"), outputs.asn1)
        self.assertEqual(os.path.join("out", "index.csv"), outputs.index)
        self.assertEqual(os.path.join("out", "index-v2.csv"), outputs.ranked_index)
        self.assertEqual(os.path.join("out", "standard.txt"), outputs.standard)
        self.assertEqual(os.path.join("out", "closure.json"), outputs.closure)

    def testJsonTextsAloneIsTheJsonTreeWithProseInIt(self):
        """The common case: one tree, and it carries the texts.

        pysnmp/pysmi#277.
        """
        outputs = mibcorpus._outputs_for("out", ["json-texts"])

        self.assertIsNone(outputs.json)
        self.assertEqual(os.path.join("out", "json"), outputs.json_texts)

    def testJsonTextsTakesAPathOfItsOwn(self):
        outputs = mibcorpus._outputs_for("out", ["json-texts:/elsewhere/json"])

        self.assertEqual("/elsewhere/json", outputs.json_texts)

    def testBothMayBeNamedAtDifferentPaths(self):
        """A build publishing a lean tree and rendering from a complete one.

        The issue asks for both options, so neither may exclude the other.
        """
        outputs = mibcorpus._outputs_for("out", ["json", "json-texts:/elsewhere/full"])

        self.assertEqual(os.path.join("out", "json"), outputs.json)
        self.assertEqual("/elsewhere/full", outputs.json_texts)

    def testPlainJsonCarriesNoProse(self):
        """What the tree has always held, and what it holds unless asked."""
        outputs = mibcorpus._outputs_for("out", ["json"])

        self.assertIsNone(outputs.json_texts)

    def testTheDefaultLayoutCarriesNoProse(self):
        """Turning it on by default would add roughly 70% to a published tree."""
        self.assertIsNone(mibcorpus._outputs_for("out", None).json_texts)

    def testNamingBothAtOnePathIsRefused(self):
        """The second pass would overwrite the first, and which survived would
        depend on the order the emit list happened to be read in."""
        with self.assertRaises(error.PySmiError) as caught:
            mibcorpus._outputs_for("out", ["json", "json-texts"])

        self.assertIn("path of its own", str(caught.exception))

    def testArcsIsNotInTheDefaultLayout(self):
        """It is only worth having with a registry to name its arcs, and that
        is an input the caller supplies. pysnmp/pysmi#288."""
        self.assertIsNone(mibcorpus._outputs_for("out", None).arcs)

        self.assertEqual(
            os.path.join("out", "arcs.json"),
            mibcorpus._outputs_for("out", ["arcs"]).arcs,
        )

    def testEmitNarrowsToWhatWasAsked(self):
        outputs = mibcorpus._outputs_for("out", ["json"])

        self.assertEqual(os.path.join("out", "json"), outputs.json)
        self.assertIsNone(outputs.notexts)
        self.assertIsNone(outputs.asn1)

    def testEmitTakesAPathOfItsOwn(self):
        outputs = mibcorpus._outputs_for("out", ["index:/elsewhere/index.csv"])

        self.assertEqual("/elsewhere/index.csv", outputs.index)

    def testAnUnknownArtifactIsRefused(self):
        self.assertRaises(error.PySmiError, mibcorpus._outputs_for, "out", ["sqlite"])


class RegistryTestCase(unittest.TestCase):
    """Which registry a --oid-registry file is, read from the file.

    A snapshot a repository commits is named whatever that repository calls
    it, so asking the caller to say which is which is asking them to repeat
    something the file already states. pysnmp/pysmi#288.
    """

    PEN = "PRIVATE ENTERPRISE NUMBERS\n\n9\n  Cisco Systems, Inc.\n    A\n      a&b\n"

    SMI = (
        '<?xml version="1.0"?>\n'
        '<registry xmlns="http://www.iana.org/assignments" id="smi-numbers">'
        "<description>iso (1)</description></registry>"
    )

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def write(self, name, text):
        path = os.path.join(self.tmp, name)

        with open(path, "w", encoding="utf-8") as fileObj:
            fileObj.write(text)

        return path

    def testThePublishedEnterpriseRegistryIsRecognised(self):
        enterprises, smi = mibcorpus._registries([self.write("anything.txt", self.PEN)])

        self.assertEqual("Cisco Systems, Inc.", enterprises[9].organization)
        self.assertEqual({}, smi)

    def testAReducedSnapshotIsRecognised(self):
        enterprises, _smi = mibcorpus._registries(
            [self.write("pen.csv", "number,organization\n9,Cisco\n")]
        )

        self.assertEqual("Cisco", enterprises[9].organization)

    def testSmiNumbersIsRecognised(self):
        _enterprises, smi = mibcorpus._registries([self.write("x.xml", self.SMI)])

        self.assertEqual("iso", smi["1"].name)

    def testBothMayBeGiven(self):
        """--oid-registry is repeatable, and the two name different arcs."""
        enterprises, smi = mibcorpus._registries(
            [self.write("pen.txt", self.PEN), self.write("smi.xml", self.SMI)]
        )

        self.assertEqual("Cisco Systems, Inc.", enterprises[9].organization)
        self.assertEqual("iso", smi["1"].name)

    def testSomethingThatIsNeitherIsRefused(self):
        """A build pointed at the wrong file should say so rather than emit an
        index naming nobody, which reads as a corpus registering under arcs
        nobody allocated."""
        with self.assertRaises(error.PySmiError):
            mibcorpus._registries([self.write("notes.txt", "just some text\n")])


class RunTestCase(unittest.TestCase):
    """Driving a build end to end."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.src = os.path.join(self.root, "src", "cisco")
        os.makedirs(self.src)

        with open(os.path.join(self.src, "A-MIB"), "w") as fileObj:
            fileObj.write(module("A-MIB", 41))

        self.out = os.path.join(self.root, "output")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def run_with(self, *args):
        """Run the tool, returning the exit code it asked for."""
        argv = ["mibcorpus", "--quiet", *args]

        with mock.patch.object(mibcorpus.sys, "argv", argv):
            try:
                mibcorpus.start()

            except SystemExit as exc:
                return exc.code

        return None

    def testAManifestBuildProducesThePublishedLayout(self):
        manifest = os.path.join(self.root, "corpus.json")

        with open(manifest, "w") as fileObj:
            json.dump(
                {
                    "version": 1,
                    "namespaces": [
                        {"include": "src/*", "tier": "vendor"},
                    ],
                },
                fileObj,
            )

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(f"--manifest={manifest}", f"--output-directory={self.out}"),
        )

        for artifact in ("asn1", "notexts", "texts", "json"):
            self.assertTrue(os.path.isdir(os.path.join(self.out, artifact)), artifact)

        for artifact in (
            "index.csv",
            "index-v2.csv",
            "standard.txt",
            "closure.json",
            "report.json",
        ):
            self.assertTrue(os.path.isfile(os.path.join(self.out, artifact)), artifact)

    def testANamespaceOnTheCommandLineIsEnough(self):
        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=json",
            ),
        )

        self.assertTrue(os.path.isfile(os.path.join(self.out, "json", "A-MIB.json")))
        self.assertFalse(os.path.exists(os.path.join(self.out, "notexts")))

    def testACompactCorpusCarriesOnlyWhatItPublishes(self):
        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                "--resolve-namespace=standard:base:package:pysmi.mibs.asn1",
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=json",
            ),
        )

        self.assertEqual(["A-MIB.json"], os.listdir(os.path.join(self.out, "json")))

    def testTheBuildIsStampedWithWhatTheCommandLineGaveIt(self):
        # write_db has taken these since it was written and until now nothing
        # could pass them, so every core.db mibcorpus produced left both keys
        # unset. This is the end of that path: command line to metadata.
        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=core-db",
                "--corpus-version=2.0.2",
                "--corpus-id=pysnmp/mibs",
            ),
        )

        connection = sqlite3.connect(os.path.join(self.out, "core.db"))

        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))

        finally:
            connection.close()

        self.assertEqual(meta["corpus_version"], "2.0.2")
        self.assertEqual(meta["corpus_id"], "pysnmp/mibs")

    def testAnUnstampedBuildCarriesNeitherKey(self):
        # Nothing is invented in their place: a version taken from a clock or
        # a checkout would make two builds of one source tree differ.
        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=core-db",
            ),
        )

        connection = sqlite3.connect(os.path.join(self.out, "core.db"))

        try:
            meta = dict(connection.execute("SELECT key, value FROM meta"))

        finally:
            connection.close()

        self.assertNotIn("corpus_version", meta)
        self.assertNotIn("corpus_id", meta)

    def testAProjectionCanBeAskedForOnItsOwn(self):
        # core.db and the indexes are built off the jsondoc tree, which is
        # pysmi's dependency and not the caller's: asking for one of them
        # used to mean also naming a scratch path for a tree the corpus was
        # not meant to carry, and cleaning it up. See pysnmp/pysmi#262.
        for artifact, produced in (
            ("core-db", "core.db"),
            ("index", "index.csv"),
            ("index-v2", "index-v2.csv"),
            ("closure", "closure.json"),
        ):
            with self.subTest(artifact=artifact):
                shutil.rmtree(self.out, ignore_errors=True)

                self.assertEqual(
                    mibcorpus.EX_OK,
                    self.run_with(
                        f"--namespace=vendor:cisco:{self.src}",
                        f"--output-directory={self.out}",
                        f"--emit={artifact}",
                    ),
                )

                self.assertEqual([produced], os.listdir(self.out))

    def testTheStagedTreeIsGoneWhenTheBuildReturns(self):
        with _own_tempdir() as scratch:
            self.assertEqual(
                mibcorpus.EX_OK,
                self.run_with(
                    f"--namespace=vendor:cisco:{self.src}",
                    f"--output-directory={self.out}",
                    "--emit=core-db",
                ),
            )

            self.assertEqual([], os.listdir(scratch))

    def testTheStagedTreeIsGoneWhenTheBuildRaises(self):
        # Cleaning up only on the way out of a successful build is how a
        # publisher ends up choosing its own bugs about the error path.
        with (
            _own_tempdir() as scratch,
            mock.patch.object(
                corpus_db, "write_db", side_effect=error.PySmiError("no database")
            ),
        ):
            self.assertEqual(
                mibcorpus.EX_SOFTWARE,
                self.run_with(
                    f"--namespace=vendor:cisco:{self.src}",
                    f"--output-directory={self.out}",
                    "--emit=core-db",
                ),
            )

            self.assertEqual([], os.listdir(scratch))

    def testAskingForTheTreeStillPutsItWhereItWasAskedFor(self):
        tree = os.path.join(self.root, "kept")

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=core-db",
                f"--emit=json:{tree}",
            ),
        )

        self.assertIn("A-MIB.json", os.listdir(tree))
        self.assertEqual(["core.db"], os.listdir(self.out))

    def testTheDatabaseIsTheSameWhicheverWayTheTreeWasGot(self):
        # The staged tree is the tree, so what is built off it cannot differ
        # from what a caller staging their own would have got.
        tree = os.path.join(self.root, "kept")
        staged = os.path.join(self.root, "staged-out")

        self.run_with(
            f"--namespace=vendor:cisco:{self.src}",
            f"--output-directory={self.out}",
            "--emit=core-db",
            f"--emit=json:{tree}",
            "--corpus-version=1.0.0",
        )
        self.run_with(
            f"--namespace=vendor:cisco:{self.src}",
            f"--output-directory={staged}",
            "--emit=core-db",
            "--corpus-version=1.0.0",
        )

        with open(os.path.join(self.out, "core.db"), "rb") as fileObj:
            explicit = fileObj.read()

        with open(os.path.join(staged, "core.db"), "rb") as fileObj:
            internal = fileObj.read()

        self.assertEqual(explicit, internal)

    def manifest(self, **keys):
        """A manifest over the fixture sources, plus whatever it declares."""
        path = os.path.join(self.root, "corpus.json")

        with open(path, "w") as fileObj:
            json.dump(
                {
                    "version": 1,
                    "namespaces": [{"include": "src/*", "tier": "vendor"}],
                    **keys,
                },
                fileObj,
            )

        return path

    def testTheManifestCanSayWhichArtifactsTheCorpusCarries(self):
        # What distinguishes one product from another used to be the emit set
        # in the caller's build script, so the definition of a distribution
        # was split between a file pysmi reads and one it has never seen.
        manifest = self.manifest(emit=["asn1", "index-v2"])

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

        self.assertEqual(["asn1", "index-v2.csv"], sorted(os.listdir(self.out)))

    def testTheManifestCanSendAnArtifactSomewhereOfItsOwn(self):
        elsewhere = os.path.join(self.root, "elsewhere")
        manifest = self.manifest(emit=[f"json:{elsewhere}"])

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

        self.assertIn("A-MIB.json", os.listdir(elsewhere))

    def testTheCommandLineWinsOverTheManifest(self):
        manifest = self.manifest(emit=["asn1", "index-v2"])

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
                "--emit=json",
            ),
        )

        self.assertEqual(["json"], os.listdir(self.out))

    def testAnEmptyEmitSetIsAUsageError(self):
        manifest = self.manifest(emit=[])

        self.assertEqual(
            mibcorpus.EX_USAGE,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

    def testAMetExpectationIsSilent(self):
        manifest = self.manifest(
            emit=["json"],
            expect={
                "modules": {"min": 1, "max": 1},
                "failures": {"max": 0},
                "namespaces-present": ["cisco"],
            },
        )

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

    def testAMissedBoundIsNamedAndFatal(self):
        manifest = self.manifest(emit=["json"], expect={"modules": {"min": 8000}})
        stderr = io.StringIO()

        with mock.patch.object(mibcorpus.sys, "stderr", stderr):
            code = self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            )

        self.assertEqual(mibcorpus.EX_DATAERR, code)
        self.assertIn("modules: expected at least 8000, got 1", stderr.getvalue())

    def testAMissingNamespaceIsNamedAndFatal(self):
        manifest = self.manifest(
            emit=["json"], expect={"namespaces-present": ["juniper"]}
        )
        stderr = io.StringIO()

        with mock.patch.object(mibcorpus.sys, "stderr", stderr):
            code = self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            )

        self.assertEqual(mibcorpus.EX_DATAERR, code)
        self.assertIn("juniper", stderr.getvalue())

    def testAFailingModuleCountsAgainstTheFailureBound(self):
        with open(os.path.join(self.src, "BROKEN-MIB"), "w") as fileObj:
            fileObj.write("BROKEN-MIB DEFINITIONS ::= BEGIN not SMI\n")

        manifest = self.manifest(emit=["json"], expect={"failures": {"max": 0}})

        self.assertEqual(
            mibcorpus.EX_DATAERR,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

    def testAnExpectationNothingReportsIsAUsageError(self):
        # A misspelled expectation that was quietly ignored would leave the
        # publisher believing it was being checked.
        manifest = self.manifest(expect={"moduls": {"min": 1}})

        self.assertEqual(
            mibcorpus.EX_USAGE,
            self.run_with(
                f"--manifest={manifest}",
                f"--output-directory={self.out}",
            ),
        )

    def testResolvingAgainstNothingPublishedIsASoftwareError(self):
        self.assertEqual(
            mibcorpus.EX_SOFTWARE,
            self.run_with(
                "--resolve-namespace=standard:base:package:pysmi.mibs.asn1",
                f"--output-directory={self.out}",
            ),
        )

    def testNoNamespacesIsAUsageError(self):
        self.assertEqual(mibcorpus.EX_USAGE, self.run_with("--output-directory=/tmp/x"))

    def testAnUnknownArtifactIsAUsageError(self):
        self.assertEqual(
            mibcorpus.EX_USAGE,
            self.run_with(f"--namespace=vendor:cisco:{self.src}", "--emit=sqlite"),
        )

    def testWritingIntoASourceIsASoftwareError(self):
        self.assertEqual(
            mibcorpus.EX_SOFTWARE,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.src}",
            ),
        )

    def testADefectiveModuleIsNotAnErrorByDefault(self):
        with open(os.path.join(self.src, "BROKEN-MIB"), "w") as fileObj:
            fileObj.write("BROKEN-MIB DEFINITIONS ::= BEGIN not SMI\n")

        self.assertEqual(
            mibcorpus.EX_OK,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=json",
            ),
        )

    def testFailOnErrorsSaysSo(self):
        with open(os.path.join(self.src, "BROKEN-MIB"), "w") as fileObj:
            fileObj.write("BROKEN-MIB DEFINITIONS ::= BEGIN not SMI\n")

        self.assertEqual(
            mibcorpus.EX_MIB_FAILED,
            self.run_with(
                f"--namespace=vendor:cisco:{self.src}",
                f"--output-directory={self.out}",
                "--emit=json",
                "--fail-on-errors",
            ),
        )
