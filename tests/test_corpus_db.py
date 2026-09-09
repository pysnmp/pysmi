#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""The corpus database: its OID ordering, its shape, and its determinism.

Three things here are contracts rather than implementation details, and each
has a consumer that breaks quietly if it slips.

The **OID key ordering** is what makes ``oid_key > ?`` a GETNEXT and a subtree
a range. Get it wrong and nothing raises; a walk simply visits nodes in an
order that is not OID order, which looks like a MIB defect rather than an
encoding defect.

The **schema** is read by pysnmp with stdlib ``sqlite3`` and no pysmi import
(pysnmp/pysnmp#199), so a column that quietly changes type or goes missing is
a break in a repository that does not run these tests.

**Determinism** is what lets a corpus be content-addressed. Two builds of one
source tree produce one file, so a rebuild that changed nothing publishes
nothing.
"""

import os
import sqlite3
import tempfile
import unittest

from pysmi import error
from pysmi.corpus.db import (
    APPLICATION_ID,
    SCHEMA_VERSION,
    oid_from_key,
    oid_key,
    open_db,
    subtree_bound,
    write_db,
)


def document(**symbols):
    """A jsondoc carrying the symbols named, plus the meta every one has."""
    doc = dict(symbols)
    doc["meta"] = {"schema": 1}

    return doc


def scalar(oid, name, syntax="Integer32", **extra):
    """An OBJECT-TYPE scalar, as ``JsonCodeGen`` renders one."""
    symbol = {
        "name": name,
        "oid": oid,
        "class": "objecttype",
        "nodetype": "scalar",
        "maxaccess": "read-only",
        "status": "current",
        "syntax": {"type": syntax, "class": "type"},
    }
    symbol.update(extra)

    return symbol


def build(documents, **kwargs):
    """Write a corpus to a temporary path and hand back the path."""
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "core.db")
    counts = write_db(
        path,
        [(name, doc, 0, 0) for name, doc in documents.items()],
        kwargs.pop("tiers", {}),
        **kwargs,
    )

    return path, counts


class OidKeyTestCase(unittest.TestCase):
    """The encoding that makes bytewise order numeric order."""

    def testRoundTrips(self):
        for oid in ("1", "1.3.6", "1.3.6.1.4.1.9", "2.0", "1.3.6.1.4.1.4294967295"):
            self.assertEqual(oid_from_key(oid_key(oid)), oid)

    def testByteOrderIsNumericOrder(self):
        # 1.3.10 below 1.3.9 is what dotted-decimal string sorting gets wrong,
        # and 1.3.256 is what a single byte per arc gets wrong.
        oids = ["1.3.6", "1.3.6.1", "1.3.7", "1.3.9", "1.3.10", "1.3.256", "2.0"]

        self.assertEqual(
            sorted(oids, key=oid_key),
            sorted(oids, key=lambda x: tuple(int(a) for a in x.split("."))),
        )

    def testPrefixEncodesToBytePrefix(self):
        self.assertTrue(oid_key("1.3.6.1").startswith(oid_key("1.3.6")))

    def testParentSortsBeforeChildren(self):
        self.assertLess(oid_key("1.3.6"), oid_key("1.3.6.0"))

    def testSubtreeBoundBracketsTheSubtree(self):
        low, high = oid_key("1.3.6"), subtree_bound(oid_key("1.3.6"))

        self.assertTrue(low <= oid_key("1.3.6.1.4.1.99") < high)
        self.assertFalse(low <= oid_key("1.3.7") < high)

    def testSubtreeBoundCarriesPastMaxArc(self):
        # An arc of 0xFF is the byte the naive "increment the last byte"
        # overflows on, so the bound has to shorten rather than wrap.
        key = oid_key("1.255")

        self.assertGreater(subtree_bound(key), key)
        self.assertGreater(subtree_bound(key), oid_key("1.255.1"))

    def testRejectsWhatIsNotAnOid(self):
        for bad in ("", "1.3.six", "not an oid"):
            with self.assertRaises(error.PySmiError):
                oid_key(bad)

    def testRejectsArcOutOfRange(self):
        with self.assertRaises(error.PySmiError):
            oid_key("1.4294967296")

    def testRejectsTruncatedKey(self):
        with self.assertRaises(error.PySmiError):
            oid_from_key(b"\x04\x01\x02")


class SchemaTestCase(unittest.TestCase):
    """What a reader is promised it will find."""

    def setUp(self):
        self.path, self.counts = build(
            {
                "TEST-MIB": document(
                    testMib={
                        "name": "testMib",
                        "oid": "1.3.6.1.4.1.99",
                        "class": "moduleidentity",
                        "lastupdated": "2026-01-01 00:00",
                        "revisions": [{"revision": "2026-01-01 00:00"}],
                    },
                    testScalar=scalar("1.3.6.1.4.1.99.1", "testScalar"),
                    testOther=scalar("1.3.6.1.4.1.99.2", "testOther", units="seconds"),
                    TestTC={
                        "name": "TestTC",
                        "class": "textualconvention",
                        "status": "current",
                        "displayhint": "255a",
                        "type": {"type": "OCTET STRING", "class": "type"},
                    },
                    imports={"class": "imports", "SNMPv2-SMI": ["OBJECT-TYPE"]},
                )
            },
            tiers={"TEST-MIB": "vendor"},
            ranked={"1.3.6.1.4.1.99": "TEST-MIB"},
            corpusVersion="3",
            corpusId="test",
        )
        self.db = open_db(self.path)

    def tearDown(self):
        self.db.close()

    def testMetaCarriesTheVersionsAConsumerGatesOn(self):
        meta = dict(self.db.execute("SELECT key, value FROM meta"))

        self.assertEqual(meta["schema_version"], str(SCHEMA_VERSION))
        self.assertEqual(meta["corpus_version"], "3")
        self.assertEqual(meta["corpus_id"], "test")
        self.assertEqual(meta["texts"], "0")

    def testMetaOmitsWhatTheCallerDidNotSupply(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.98.1", "a"))})
        db = open_db(path)

        try:
            meta = dict(db.execute("SELECT key, value FROM meta"))

        finally:
            db.close()

        self.assertNotIn("corpus_version", meta)
        self.assertNotIn("corpus_id", meta)

    def testModuleRowCarriesTierAndHash(self):
        row = self.db.execute(
            "SELECT tier, oid, lastupdated, revision, content_hash, nodes "
            "FROM module WHERE name = 'TEST-MIB'"
        ).fetchone()

        self.assertEqual(row[0], "vendor")
        self.assertEqual(row[1], "1.3.6.1.4.1.99")
        self.assertEqual(row[3], "202601010000Z")
        self.assertTrue(row[4])
        self.assertEqual(row[5], 3)

    def testNodeLookupByOid(self):
        row = self.db.execute(
            "SELECT module, name, nodetype, maxaccess, units FROM node "
            "WHERE oid_key = ?",
            (oid_key("1.3.6.1.4.1.99.2"),),
        ).fetchone()

        self.assertEqual(
            row, ("TEST-MIB", "testOther", "scalar", "read-only", "seconds")
        )

    def testNodeLookupByName(self):
        row = self.db.execute(
            "SELECT oid FROM node WHERE module = ? AND name = ?",
            ("TEST-MIB", "testScalar"),
        ).fetchone()

        self.assertEqual(row[0], "1.3.6.1.4.1.99.1")

    def testNextNodeIsOidOrder(self):
        row = self.db.execute(
            "SELECT oid FROM node WHERE oid_key > ? ORDER BY oid_key LIMIT 1",
            (oid_key("1.3.6.1.4.1.99.1"),),
        ).fetchone()

        self.assertEqual(row[0], "1.3.6.1.4.1.99.2")

    def testSyntaxResolvesThroughTheTypeTable(self):
        row = self.db.execute(
            "SELECT t.spec FROM node JOIN type t ON t.id = node.syntax "
            "WHERE node.name = 'testScalar'"
        ).fetchone()

        self.assertEqual(row[0], '{"class":"type","type":"Integer32"}')

    def testOneTypeRowServesEveryNodeUsingIt(self):
        rows = self.db.execute(
            "SELECT DISTINCT syntax FROM node WHERE syntax IS NOT NULL"
        ).fetchall()

        # testScalar and testOther are both Integer32, so they share an id --
        # which is the identity a reader caches a synthesized class against.
        self.assertEqual(len(rows), 1)

    def testTextualConventionIsASymbolNotANode(self):
        row = self.db.execute(
            "SELECT class, displayhint FROM symbol WHERE name = 'TestTC'"
        ).fetchone()

        self.assertEqual(row, ("textualconvention", "255a"))
        self.assertIsNone(
            self.db.execute("SELECT 1 FROM node WHERE name = 'TestTC'").fetchone()
        )

    def testImportsAreResolvableBySymbol(self):
        row = self.db.execute(
            "SELECT source FROM import WHERE module = ? AND name = ?",
            ("TEST-MIB", "OBJECT-TYPE"),
        ).fetchone()

        self.assertEqual(row[0], "SNMPv2-SMI")

    def testOidIndexCarriesTheRankedProjection(self):
        row = self.db.execute(
            "SELECT module FROM oid_index WHERE oid_key = ?",
            (oid_key("1.3.6.1.4.1.99"),),
        ).fetchone()

        self.assertEqual(row[0], "TEST-MIB")

    def testImportsClauseIsNotAModuleSymbol(self):
        # "imports" is a document key, not an SMI descriptor; a reader that
        # took it for one would offer a symbol no MIB declares.
        self.assertIsNone(
            self.db.execute("SELECT 1 FROM symbol WHERE name = 'imports'").fetchone()
        )


class WriterTestCase(unittest.TestCase):
    """What the writer refuses, skips and repeats."""

    def testTwoBuildsAreByteIdentical(self):
        documents = {
            "B-MIB": document(b=scalar("1.3.6.1.4.1.99.2", "b", syntax="Counter32")),
            "A-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a")),
        }

        first, _ = build(documents)
        # Reversed, so a writer that let iteration order reach the file fails.
        second, _ = build(dict(reversed(list(documents.items()))))

        with open(first, "rb") as one, open(second, "rb") as two:
            self.assertEqual(one.read(), two.read())

    def testFakeColumnsAreNotNodes(self):
        # pysmiFakeCol OIDs are templates carrying %s, resolved against a row
        # OID that a corpus never sees. Encoding one would raise; carrying it
        # unencoded would put a non-OID in the tree.
        path, counts = build(
            {
                "TEST-MIB": document(
                    real=scalar("1.3.6.1.4.1.99.1", "real"),
                    pysmiFakeCol1000=scalar("%s.1000", "pysmiFakeCol1000"),
                )
            }
        )

        self.assertEqual(counts["node"], 1)

    def testTierDefaultsToVendorForAnUndeclaredModule(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})
        db = open_db(path)

        try:
            row = db.execute("SELECT tier FROM module").fetchone()

        finally:
            db.close()

        self.assertEqual(row[0], "vendor")

    def testTwoModulesMayDefineOneOid(self):
        path, counts = build(
            {
                "A-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a")),
                "B-MIB": document(b=scalar("1.3.6.1.4.1.99.1", "b")),
            }
        )

        self.assertEqual(counts["node"], 2)

    def testMalformedOidFailsTheBuild(self):
        # Not skipped: an OID the corpus cannot place is a defect in the
        # corpus, and a build that drops it quietly publishes a hole.
        with self.assertRaises(error.PySmiError):
            build({"TEST-MIB": document(a=scalar("1.3.6.1.4.six", "a"))})


class OpenTestCase(unittest.TestCase):
    """What :py:func:`open_db` refuses."""

    def testOpensReadOnlyWithoutAWritableDirectory(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})
        os.chmod(os.path.dirname(path), 0o500)

        try:
            db = open_db(path)
            db.execute("SELECT 1 FROM node").fetchone()
            db.close()

        finally:
            os.chmod(os.path.dirname(path), 0o700)

    def testRefusesADatabaseThatIsNotACorpus(self):
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "other.db")
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE t (x)")
        connection.commit()
        connection.close()

        with self.assertRaises(error.PySmiError):
            open_db(path)

    def testRefusesAnUnreadableSchemaVersion(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})
        connection = sqlite3.connect(path)
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        connection.close()

        with self.assertRaisesRegex(error.PySmiError, "schema version"):
            open_db(path)

    def testStampsTheApplicationId(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})
        connection = sqlite3.connect(path)

        try:
            self.assertEqual(
                connection.execute("PRAGMA application_id").fetchone()[0],
                APPLICATION_ID,
            )

        finally:
            connection.close()

    def testPublishesWithNoJournalAlongside(self):
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})

        self.assertFalse(os.path.exists(path + "-wal"))
        self.assertFalse(os.path.exists(path + "-journal"))

    def testIsReadableByAnyoneWhoCanReachIt(self):
        # A corpus served by a container running as another uid answers 403
        # for every module if the build's umask reached the file.
        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})

        self.assertTrue(os.stat(path).st_mode & 0o044)


if __name__ == "__main__":
    unittest.main()
