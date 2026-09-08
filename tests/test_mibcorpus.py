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

import json
import os
import shutil
import tempfile
import textwrap
import unittest
from unittest import mock

from pysmi import error
from pysmi.scripts import mibcorpus


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

        for artifact in ("index.csv", "index-v2.csv", "standard.txt", "report.json"):
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
