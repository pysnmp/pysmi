#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The conformance fixture, checked against the writer that produces it.

pysnmp runs :py:data:`~pysmi.corpus.conformance.VECTORS` against its own
reader. These tests check the other half: that the fixture this tree builds
actually answers what the vectors claim, so a failure over there is a reader
defect rather than a fixture that was never right.
"""

import json
import os
import tempfile
import unittest

from pysmi.corpus import conformance
from pysmi.corpus.conformance import (
    DOCUMENTS,
    VECTORS,
    build_fixture,
    run_vectors,
    vectors_as_json,
    write_fixture,
)
from pysmi.corpus.db import open_db


class ConformanceTestCase(unittest.TestCase):
    """The fixture answers its own vectors."""

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.mkdtemp()
        cls.path = build_fixture(os.path.join(cls.directory, "conformance.db"))

    def testEveryVectorPasses(self):
        db = open_db(self.path)

        try:
            self.assertEqual(run_vectors(db), [])

        finally:
            db.close()

    def testFixtureIsDeterministic(self):
        other = build_fixture(os.path.join(tempfile.mkdtemp(), "conformance.db"))

        with open(self.path, "rb") as one, open(other, "rb") as two:
            self.assertEqual(one.read(), two.read())

    def testVectorIdsAreUnique(self):
        identifiers = [x["id"] for x in VECTORS]

        self.assertEqual(len(identifiers), len(set(identifiers)))

    def testEveryVectorSaysWhy(self):
        # A vector that fails has to say what broke without its reader's
        # author reconstructing the intent from an OID.
        for vector in VECTORS:
            self.assertTrue(vector.get("why"), vector["id"])

    def testVectorsRenderAsJson(self):
        # The contract is data, so a reader that is not written in Python can
        # run the same vectors.
        self.assertEqual(
            [x["id"] for x in json.loads(vectors_as_json())],
            [x["id"] for x in VECTORS],
        )

    def testWriteFixtureLandsBothFiles(self):
        database, vectors = write_fixture(os.path.join(tempfile.mkdtemp(), "out"))

        self.assertTrue(os.path.exists(database))

        with open(vectors, encoding="utf-8") as fileObj:
            written = json.load(fileObj)

        self.assertEqual([x["id"] for x in written], [x["id"] for x in VECTORS])

    def testFixtureCoversEveryOperation(self):
        # A schema operation with no vector is a part of the contract nothing
        # checks, which is how a reader ships a broken next_node.
        self.assertEqual(
            {x["op"] for x in VECTORS},
            {
                "meta",
                "find_module",
                "node",
                "node_by_name",
                "syntax",
                "defval",
                "indices",
                "next_node",
                "walk",
                "subtree",
                "symbol",
                "same_syntax",
                "import_source",
                "module_field",
                # The codec, which takes no corpus: a reader that encodes a
                # key differently finds nothing and walks in the wrong order,
                # and every operation above fails without naming the cause.
                "oid_key",
                "oid_from_key",
                "subtree_bound",
                "oid_key_order",
                "oid_key_prefix",
                "oid_key_refuses",
            },
        )

    def testHarnessReportsACodecThatAcceptsWhatItShouldRefuse(self):
        # The refusal vectors exist for a reader whose codec is too
        # permissive: one that encodes "1.3.six" to *something* sorts it
        # somewhere and answers queries about it, wrongly and quietly. That is
        # the defect they catch, so the harness has to notice a codec that
        # never raises -- which is what this substitutes.
        path = build_fixture(os.path.join(tempfile.mkdtemp(), "codec.db"))
        db = open_db(path)

        original = conformance.oid_key

        def too_permissive(oid):
            # Permissive exactly where the real codec refuses, and identical
            # everywhere else -- so this is a reader with one defect rather
            # than a codec replaced wholesale, and the other vectors still
            # answer as they should.
            try:
                return original(oid)

            except Exception:  # noqa: BLE001
                return b"\x01\x01"

        try:
            conformance.oid_key = too_permissive
            failures = run_vectors(db)

        finally:
            conformance.oid_key = original
            db.close()

        self.assertIn("oid-key-refuses-what-is-not-an-oid", failures)
        self.assertIn("oid-key-refuses-an-arc-above-the-ceiling", failures)

    def testHarnessReportsAVectorThatDoesNotHold(self):
        # run_vectors is only useful if it can fail. Every vector passing
        # against the real fixture proves the fixture; this proves the
        # harness, by asking it about a corpus that answers differently.
        import sqlite3

        path = build_fixture(os.path.join(tempfile.mkdtemp(), "broken.db"))
        connection = sqlite3.connect(path)
        connection.execute("UPDATE meta SET value = '99' WHERE key = 'corpus_version'")
        connection.commit()
        connection.close()

        db = open_db(path)

        try:
            self.assertIn("meta-corpus-version", run_vectors(db))

        finally:
            db.close()

    def testSpecOfAnAbsentTypeIsNone(self):
        # A node with no syntax -- a table, a row, an OBJECT-IDENTITY -- has
        # a NULL type id, and resolving one must be None rather than a lookup
        # for id NULL.
        db = open_db(self.path)

        try:
            row = db.execute(
                "SELECT syntax FROM node WHERE name = 'fixtureTable'"
            ).fetchone()

        finally:
            db.close()

        self.assertIsNone(row[0])

    def testFixtureCarriesAShadowedOid(self):
        # The collision is the case a reader is most likely to get wrong, so
        # losing it from the fixture should fail here rather than silently.
        oids = [
            symbol["oid"]
            for document in DOCUMENTS.values()
            for symbol in document.values()
            if isinstance(symbol, dict) and "oid" in symbol
        ]

        self.assertNotEqual(len(oids), len(set(oids)))


if __name__ == "__main__":
    unittest.main()
