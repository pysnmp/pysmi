#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""producer_of reads back the "Produced by <package>-<version>" marker
compiler writes into every module it stores -- the one signal both a
version-mismatch rebuild (pysnmp/pysmi#63) and pruning (pysnmp/pysmi#61) use
to tell a file this package wrote from one it did not.

The marker is a version string, and a version has hyphens of its own (an
rc build looks like pysmi-2.0.0-rc.11), so splitting the recorded package
name from its version is not a plain split on the first or last hyphen --
pinned here after a first attempt got exactly that wrong.
"""

import json
import unittest

from pysmi.mibinfo import producer_of


class ProducerOfTestCase(unittest.TestCase):
    def testPlainVersionInPythonComment(self):
        text = "#\n# Produced by pysmi-2.0.0\n#\n\nout = 1\n"
        self.assertEqual(("pysmi", "2.0.0"), producer_of(text))

    def testPreReleaseVersionInPythonComment(self):
        # The version itself contains a hyphen -- pysmi-2.0.0-rc.11 -- so a
        # naive split (first hyphen, or last hyphen) gets this wrong in one
        # direction or the other.
        text = "#\n# ASN.1 source IF-MIB\n# Produced by pysmi-2.0.0-rc.11\n#\n\nout = 1\n"
        self.assertEqual(("pysmi", "2.0.0-rc.11"), producer_of(text))

    def testMarkerAmongOtherCommentLines(self):
        text = (
            "#\n"
            "# PySNMP MIB module IF-MIB (http://snmplabs.com/pysmi)\n"
            "# ASN.1 source IF-MIB\n"
            "# Source digest sha256:abc123\n"
            "# Produced by pysmi-2.0.0-rc.11\n"
            "#\n"
        )
        self.assertEqual(("pysmi", "2.0.0-rc.11"), producer_of(text))

    def testJsonDocumentMetaComments(self):
        doc = {
            "module": "IF-MIB",
            "meta": {
                "schema": 1,
                "comments": [
                    "ASN.1 source IF-MIB",
                    "Produced by pysmi-2.0.0-rc.11",
                ],
            },
        }
        self.assertEqual(("pysmi", "2.0.0-rc.11"), producer_of(json.dumps(doc)))

    def testJsonDocumentWithoutComments(self):
        doc = {"module": "IF-MIB", "meta": {"schema": 1}}
        self.assertIsNone(producer_of(json.dumps(doc)))

    def testNoMarkerAtAll(self):
        self.assertIsNone(producer_of("# a hand-written file\nout = 1\n"))

    def testEmptyText(self):
        self.assertIsNone(producer_of(""))

    def testMarkerFromADifferentPackage(self):
        # Not this package's marker -- callers compare the returned name
        # against their own, this function does not filter by it.
        self.assertEqual(("somethingelse", "9.9.9"), producer_of("# Produced by somethingelse-9.9.9\n"))

    def testMalformedJsonFallsBackToRawTextSearch(self):
        # Not valid JSON (trailing comma), but still has the marker as plain
        # text -- the JSON parse attempt must not swallow that.
        text = '{"a": 1,} # Produced by pysmi-2.0.0-rc.11'
        self.assertEqual(("pysmi", "2.0.0-rc.11"), producer_of(text))

    def testJsonArrayIsNotTreatedAsADocument(self):
        # A JSON value that parses but is not a dict with "meta" falls back
        # to a raw-text search over the whole JSON string, rather than being
        # read as a document -- real writer output is always a "#" comment
        # or a JSON object, never a bare array, so this case does not arise
        # in practice.
        self.assertIsNone(producer_of(json.dumps(["nothing to see here"])))


if __name__ == "__main__":
    unittest.main()
