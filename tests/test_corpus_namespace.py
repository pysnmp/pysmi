#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The input set is declared, and declared in an order.

A corpus build resolves a module name that two namespaces hold by source
order, so the order the namespaces arrive in is part of the answer. Reading
them from a manifest rather than walking a directory tree is what makes that
order something someone chose.
"""

import json
import os
import shutil
import tempfile
import unittest

from pysmi import error
from pysmi.corpus.namespace import Namespace, load_manifest, read_manifest


class NamespaceTestCase(unittest.TestCase):
    """What a namespace has to say about itself."""

    def testTierMustBeOneOfTheKnownOnes(self):
        self.assertRaises(error.PySmiError, Namespace, "n", "mibs", "almost-standard")

    def testANamelessNamespaceIsRefused(self):
        self.assertRaises(error.PySmiError, Namespace, "", "mibs", "vendor")

    def testASourcelessNamespaceIsRefused(self):
        self.assertRaises(error.PySmiError, Namespace, "n", "", "vendor")

    def testTiersRankStandardFirst(self):
        standard = Namespace("s", "mibs", "standard")
        vendor = Namespace("v", "mibs", "vendor")

        self.assertLess(standard.tier_rank, vendor.tier_rank)

    def testAPackageSourceIsRecognized(self):
        namespace = Namespace("base", "package:pysmi.mibs.asn1", "standard")

        self.assertTrue(namespace.is_package)
        self.assertEqual("pysmi.mibs.asn1", namespace.package)

    def testADirectorySourceIsNotAPackage(self):
        self.assertFalse(Namespace("v", "mibs/vendor", "vendor").is_package)


class ManifestTestCase(unittest.TestCase):
    """Reading the input set off disk."""

    def setUp(self):
        self.root = tempfile.mkdtemp()

        for name in ("cisco", "juniper", "arista", "notes.txt"):
            path = os.path.join(self.root, "src", "vendor", name)

            if name.endswith(".txt"):
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, "w").close()
            else:
                os.makedirs(path, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def manifest(self, **body):
        """Write a manifest and return its path."""
        path = os.path.join(self.root, "corpus.json")

        with open(path, "w") as fileObj:
            json.dump(body, fileObj)

        return path

    def testNamespacesKeepDeclarationOrder(self):
        path = self.manifest(
            version=1,
            namespaces=[
                {"name": "b", "source": "src/vendor/juniper", "tier": "vendor"},
                {"name": "a", "source": "src/vendor/cisco", "tier": "vendor"},
            ],
        )

        self.assertEqual(["b", "a"], [x.name for x in load_manifest(path)])

    def testRelativePathsResolveAgainstTheManifest(self):
        path = self.manifest(
            namespaces=[{"name": "cisco", "source": "src/vendor/cisco"}]
        )

        self.assertEqual(
            os.path.join(self.root, "src", "vendor", "cisco"),
            load_manifest(path)[0].source,
        )

    def testAnIncludeExpandsSorted(self):
        # 300 vendor directories are not going to be listed by hand, and the
        # shell would expand them in whatever order the filesystem reports.
        path = self.manifest(namespaces=[{"include": "src/vendor/*", "tier": "vendor"}])

        self.assertEqual(
            ["arista", "cisco", "juniper"], [x.name for x in load_manifest(path)]
        )

    def testAnIncludeTakesDirectoriesOnly(self):
        path = self.manifest(namespaces=[{"include": "src/vendor/*"}])

        self.assertNotIn("notes.txt", [x.name for x in load_manifest(path)])

    def testAnIncludeCarriesItsTier(self):
        path = self.manifest(namespaces=[{"include": "src/vendor/*", "tier": "draft"}])

        self.assertEqual({"draft"}, {x.tier for x in load_manifest(path)})

    def testAPackageSourceSurvivesTheManifest(self):
        path = self.manifest(
            namespaces=[{"source": "package:pysmi.mibs.asn1", "tier": "standard"}]
        )

        namespace = load_manifest(path)[0]

        self.assertEqual("pysmi.mibs.asn1", namespace.name)
        self.assertTrue(namespace.is_package)

    def testANamespaceIsPublishedByDefault(self):
        path = self.manifest(namespaces=[{"source": "src/vendor/cisco"}])

        self.assertTrue(load_manifest(path)[0].publish)

    def testAResolutionSourceSaysSo(self):
        path = self.manifest(
            namespaces=[
                {
                    "name": "standard",
                    "source": "package:pysmi.mibs.asn1",
                    "tier": "standard",
                    "publish": False,
                },
                {"include": "src/vendor/*", "tier": "vendor"},
            ]
        )

        namespaces = load_manifest(path)

        self.assertFalse(namespaces[0].publish)
        self.assertEqual({True}, {x.publish for x in namespaces[1:]})

    def testAnIncludeCarriesItsPublishFlag(self):
        path = self.manifest(namespaces=[{"include": "src/vendor/*", "publish": False}])

        self.assertEqual({False}, {x.publish for x in load_manifest(path)})

    def testADuplicateNamespaceIsRefused(self):
        path = self.manifest(
            namespaces=[
                {"name": "cisco", "source": "src/vendor/cisco"},
                {"name": "cisco", "source": "src/vendor/juniper"},
            ]
        )

        self.assertRaises(error.PySmiError, load_manifest, path)

    def testAnUnknownVersionIsRefused(self):
        path = self.manifest(version=2, namespaces=[{"source": "src/vendor/cisco"}])

        self.assertRaises(error.PySmiError, load_manifest, path)

    def testAnEmptyManifestIsRefused(self):
        self.assertRaises(error.PySmiError, load_manifest, self.manifest(namespaces=[]))

    def testAMissingManifestIsRefused(self):
        self.assertRaises(
            error.PySmiError, load_manifest, os.path.join(self.root, "nope.json")
        )

    def testAnEntryNamingNeitherSourceNorIncludeIsRefused(self):
        path = self.manifest(namespaces=[{"tier": "vendor"}])

        self.assertRaises(error.PySmiError, load_manifest, path)

    def testAnIncludeThatAlsoNamesASourceIsRefused(self):
        path = self.manifest(
            namespaces=[{"include": "src/vendor/*", "source": "src/vendor/cisco"}]
        )

        self.assertRaises(error.PySmiError, load_manifest, path)


class ManifestDeclarationTestCase(unittest.TestCase):
    """A manifest declares what the corpus is, not only where it comes from.

    Until pysnmp/pysmi#263 it declared sources alone, so which artifacts a
    corpus carried and what had to be true of it lived in the publisher's
    build script.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.root, "src", "cisco"))

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def manifest(self, **body):
        """A manifest with one namespace, plus whatever it declares."""
        path = os.path.join(self.root, "corpus.json")

        with open(path, "w") as fileObj:
            json.dump(
                {"namespaces": [{"source": "src/cisco"}], **body},
                fileObj,
            )

        return path

    def testAManifestNeedDeclareNeither(self):
        manifest = read_manifest(self.manifest())

        self.assertIsNone(manifest.emit)
        self.assertEqual({}, manifest.expect)

    def testTheEmitSetIsReadAsDeclared(self):
        manifest = read_manifest(self.manifest(emit=["asn1", "json:/elsewhere"]))

        self.assertEqual(["asn1", "json:/elsewhere"], manifest.emit)

    def testTheExpectationsAreReadAsDeclared(self):
        expect = {"modules": {"min": 8000}, "namespaces-present": ["ietf"]}

        self.assertEqual(expect, read_manifest(self.manifest(expect=expect)).expect)

    def testAnEmptyEmitSetIsRefused(self):
        self.assertRaises(error.PySmiError, read_manifest, self.manifest(emit=[]))

    def testAnEmitSetThatIsNotNamesIsRefused(self):
        self.assertRaises(error.PySmiError, read_manifest, self.manifest(emit="asn1"))
        self.assertRaises(error.PySmiError, read_manifest, self.manifest(emit=[1]))

    def testAnExpectationNothingReportsIsRefused(self):
        # Silently ignoring it would leave the publisher believing a check
        # was being made that never was.
        self.assertRaises(
            error.PySmiError,
            read_manifest,
            self.manifest(expect={"moduls": {"min": 1}}),
        )

    def testABoundThatIsNotMinOrMaxIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            read_manifest,
            self.manifest(expect={"modules": {"about": 10}}),
        )

    def testABoundThatIsNotAnIntegerIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            read_manifest,
            self.manifest(expect={"failures": {"max": "none"}}),
        )

    def testAnExpectationOfTheWrongShapeIsRefused(self):
        self.assertRaises(
            error.PySmiError,
            read_manifest,
            self.manifest(expect={"namespaces-present": "ietf"}),
        )
        self.assertRaises(
            error.PySmiError, read_manifest, self.manifest(expect={"modules": 8000})
        )

    def testExpectIsRefusedWhenItIsNotAnObject(self):
        self.assertRaises(
            error.PySmiError, read_manifest, self.manifest(expect=["modules"])
        )

    def testLoadManifestStillRefusesWhatReadManifestRefuses(self):
        # The namespaces-only view validates the whole file: a manifest one
        # entry point accepts and the other does not would be a trap.
        self.assertRaises(error.PySmiError, load_manifest, self.manifest(emit=[]))
