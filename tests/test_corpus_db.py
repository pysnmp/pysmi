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
    FULL,
    SCHEMA_VERSION,
    SEARCH,
    oid_from_key,
    oid_key,
    open_db,
    subtree_bound,
    validate,
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

    def testRejectsEmptyKey(self):
        with self.assertRaises(error.PySmiError):
            oid_from_key(b"")

    def testSubtreeBoundOfAKeyThatIsAllOnes(self):
        # Nothing sorts above a key of every byte 0xFF, and SQLite has no
        # +infinity for a BLOB, so the bound has to get longer rather than
        # increment. Unreachable from a real OID -- oid_key writes a length
        # byte first -- but subtree_bound is published for readers to
        # reimplement, so the boundary is part of what they must match.
        key = b"\xff\xff"

        self.assertGreater(subtree_bound(key), key)
        self.assertGreater(subtree_bound(key), key + b"\x00")


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

    def testDocumentValuesThatAreNotSymbolsAreSkipped(self):
        # A jsondoc's top-level values are objects, but the writer reads
        # documents it did not produce -- a hand-edited one, or a future
        # schema that adds a scalar beside meta -- and one stray value should
        # not cost the module.
        document = {
            "a": scalar("1.3.6.1.4.1.99.1", "a"),
            "schemaNote": "not a symbol",
            "meta": {"schema": 1},
        }
        path, counts = build({"TEST-MIB": document})

        self.assertEqual(counts["node"], 1)
        self.assertEqual(counts["type"], 1)

    def testImportsEntriesThatAreNotListsAreSkipped(self):
        path, counts = build(
            {
                "TEST-MIB": document(
                    a=scalar("1.3.6.1.4.1.99.1", "a"),
                    imports={
                        "class": "imports",
                        "SNMPv2-SMI": ["OBJECT-TYPE"],
                        "BROKEN": "not a list",
                    },
                )
            }
        )

        self.assertEqual(counts["import"], 1)

    def testWritingOverAnExistingCorpusReplacesIt(self):
        # A rebuild writes to the path the last build left a file at, and a
        # corpus opened immutable must not be a half-overwritten one.
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "core.db")

        for oid in ("1.3.6.1.4.1.99.1", "1.3.6.1.4.1.99.2"):
            write_db(
                path,
                [("TEST-MIB", document(a=scalar(oid, "a")), 0, 0)],
                {},
            )

        db = open_db(path)

        try:
            rows = db.execute("SELECT oid FROM node").fetchall()

        finally:
            db.close()

        self.assertEqual(rows, [("1.3.6.1.4.1.99.2",)])

    def testMalformedOidFailsTheBuild(self):
        # Not skipped: an OID the corpus cannot place is a defect in the
        # corpus, and a build that drops it quietly publishes a hole.
        with self.assertRaises(error.PySmiError):
            build({"TEST-MIB": document(a=scalar("1.3.6.1.4.six", "a"))})


class ProvenanceTestCase(unittest.TestCase):
    """Where each module came from (pysnmp/pysmi#278).

    The build knows which namespace supplied a module, which file it read and
    what that file's digest was. None of it used to survive the build, so
    nothing downstream could answer the first question anyone asks of a MIB
    they did not publish.
    """

    ORIGIN = {
        "namespace": "vendor",
        "file": "acme/TEST-MIB",
        "digest": "sha256:abc",
    }

    def rows(self, path):
        db = open_db(path)

        try:
            return {
                module: (namespace, file, digest)
                for module, namespace, file, digest in db.execute(
                    "SELECT module, namespace, file, digest FROM provenance"
                )
            }

        finally:
            db.close()

    def corpus(self, provenance=None):
        return build(
            {
                "TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a")),
                "OTHER-MIB": document(b=scalar("1.3.6.1.4.1.98.1", "b")),
            },
            provenance=provenance,
        )

    def testItIsWrittenPerModule(self):
        path, counts = self.corpus({"TEST-MIB": self.ORIGIN})

        self.assertEqual(1, counts["provenance"])
        self.assertEqual(
            {"TEST-MIB": ("vendor", "acme/TEST-MIB", "sha256:abc")}, self.rows(path)
        )

    def testAModuleWithNoOriginGetsNoRow(self):
        """Absence is the answer, and it is not the same as empty strings.

        A reader rendering provenance has to be able to say "not recorded"
        rather than showing blanks.
        """
        path, _ = self.corpus({"TEST-MIB": self.ORIGIN})

        self.assertNotIn("OTHER-MIB", self.rows(path))

    def testProvenanceForAModuleTheCorpusDoesNotCarryIsNotWritten(self):
        """It would be a row about nothing, and a join would find it."""
        path, counts = self.corpus({"TEST-MIB": self.ORIGIN, "ABSENT-MIB": self.ORIGIN})

        self.assertEqual(1, counts["provenance"])
        self.assertEqual(["TEST-MIB"], sorted(self.rows(path)))

    def testABuildThatRecordedNothingWritesNoRows(self):
        path, counts = self.corpus()

        self.assertEqual(0, counts["provenance"])
        self.assertEqual({}, self.rows(path))

    def testTwoBuildsOfOneCorpusAgreeByteForByte(self):
        """The table must not cost the file its reproducibility."""
        first, _ = self.corpus({"TEST-MIB": self.ORIGIN})
        second, _ = self.corpus({"TEST-MIB": self.ORIGIN})

        with open(first, "rb") as one, open(second, "rb") as two:
            self.assertEqual(one.read(), two.read())


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

    def testRefusesAFileThatIsNotSqliteAtAll(self):
        # The application_id check needs a readable header to compare; a file
        # that is not a database at all fails earlier, and has to fail as our
        # error rather than as a bare sqlite3.DatabaseError.
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "not.db")

        with open(path, "wb") as fileObj:
            fileObj.write(b"this is not a database" * 64)

        with self.assertRaises(error.PySmiError):
            open_db(path)

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

    def testIsCreatedTheWayAnOrdinaryFileIs(self):
        # The defect this guards against is mkstemp's 0600, which made a whole
        # build's output readable only by the uid that ran it -- invisible
        # until a container running as another user served it (pysnmp/mibs#365).
        #
        # The assertion is 0666 minus the umask rather than a bit mask: a mask
        # of 0o044 passes on 0640, where an unrelated uid still cannot read the
        # corpus, and a mask of 0o004 fails on 0640 even though the umask asked
        # for that. What is being pinned is that the writer chooses no mode of
        # its own, so the caller's umask is what decides.
        umask = os.umask(0)
        os.umask(umask)

        path, _ = build({"TEST-MIB": document(a=scalar("1.3.6.1.4.1.99.1", "a"))})

        self.assertEqual(os.stat(path).st_mode & 0o777, 0o666 & ~umask)


if __name__ == "__main__":
    unittest.main()


class OpenPathTestCase(unittest.TestCase):
    """That a path reaches SQLite as a path, not as most of one.

    The same two defects were found and fixed in pysnmp's reader, which opens
    the same file the same way; this is the writer side of that contract.
    """

    def testAPathWithUriPunctuationOpensTheFileItNames(self):
        # "?" ends the path at the query string. SQLite then opens an empty
        # database of the shorter name -- which does not raise, it answers
        # nothing, and the corpus reads as a file with application_id 0.
        # "?" is the character that motivated the escaping and the only one
        # here Windows will not accept in a filename -- WinError 123 comes
        # from mkdir, before any of this is reached. It is tested wherever a
        # directory can be named that, which is every platform but Windows.
        awkward = ["sharp#", "with space", "per%cent"]

        if os.name != "nt":
            awkward.insert(0, "we?ird")

        for name in awkward:
            with self.subTest(directory=name):
                directory = os.path.join(tempfile.mkdtemp(), name)
                os.makedirs(directory)
                path, _ = build(
                    {"TEST-MIB": document(testScalar=scalar("1.3.6.1.4.1.99.1", "x"))},
                    tiers={"TEST-MIB": "vendor"},
                )
                moved = os.path.join(directory, "core.db")
                os.rename(path, moved)

                connection = open_db(moved)

                try:
                    application = connection.execute(
                        "PRAGMA application_id"
                    ).fetchone()[0]

                finally:
                    connection.close()

                self.assertEqual(application, APPLICATION_ID)

    def testADirectoryIsRefusedAsAPySmiError(self):
        # os.path.exists is not "SQLite can open it": a directory gets past
        # every check and fails in connect, which is outside the try unless
        # it is put inside one.
        directory = tempfile.mkdtemp()

        with self.assertRaises(error.PySmiError):
            open_db(directory)


class ValidateTestCase(unittest.TestCase):
    """The invariants a build must not violate.

    open_db decides whether a file is a corpus. These decide whether it is a
    sound one, which is a question only a whole build can answer -- no test
    over one module can say that no module among thousands lost its content
    hash. Each one is checked by corrupting a corpus that passes, because a
    validator that cannot fail is worse than none: it reports "sound" for
    every input, including the broken ones it exists to catch.
    """

    def setUp(self):
        self.path, _ = build(
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
                    testOther=scalar("1.3.6.1.4.1.99.2", "testOther"),
                )
            },
            tiers={"TEST-MIB": "vendor"},
            ranked={"1.3.6.1.4.1.99": "TEST-MIB"},
        )

    def corrupt(self, *statements):
        """Break the corpus, the way a defective build would have written it."""
        connection = sqlite3.connect(self.path)

        try:
            for statement in statements:
                connection.execute(statement)

            connection.commit()

        finally:
            connection.close()

    def testASoundCorpusHasNoProblems(self):
        self.assertEqual(validate(self.path), [])

    def testCatchesANodeNamingAModuleTheCorpusLacks(self):
        self.corrupt("UPDATE node SET module = 'GONE-MIB' WHERE name = 'testScalar'")

        self.assertIn("node rows name a module", " ".join(validate(self.path)))

    def testCatchesAnIndexRowNamingAModuleTheCorpusLacks(self):
        self.corrupt("UPDATE oid_index SET module = 'GONE-MIB'")

        self.assertIn("oid_index rows name a module", " ".join(validate(self.path)))

    def testCatchesADanglingTypeReference(self):
        self.corrupt("UPDATE node SET syntax = 9999 WHERE name = 'testScalar'")

        self.assertIn("type row that is not there", " ".join(validate(self.path)))

    def testCatchesAScalarThatLostItsSyntax(self):
        self.corrupt("UPDATE node SET syntax = NULL WHERE name = 'testScalar'")

        self.assertIn("carry no syntax", " ".join(validate(self.path)))

    def testCatchesAModuleThatLostItsContentHash(self):
        # An empty hash means "cannot tell whether two corpora agree", which
        # is the one answer the hash exists to prevent. A NULL one is not
        # checked because the column is NOT NULL: SQLite refuses the update,
        # which is how this test found that half of the check unreachable.
        self.corrupt("UPDATE module SET content_hash = ''")

        self.assertIn("no content hash", " ".join(validate(self.path)))

    def testTheSchemaItselfRefusesANullContentHash(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.corrupt("UPDATE module SET content_hash = NULL")

    def testCatchesATierOutsideTheVocabulary(self):
        self.corrupt("UPDATE module SET tier = 'enterprise'")

        self.assertIn("tier outside the vocabulary", " ".join(validate(self.path)))

    def testCatchesANodesColumnThatDisagreesWithTheRows(self):
        # The column is passed to the writer rather than counted by it, so
        # nothing but this notices when the two drift.
        self.corrupt("UPDATE module SET nodes = nodes + 1")

        self.assertIn("disagreeing with their node rows", " ".join(validate(self.path)))

    def testCatchesAKeyThatOrdersWrongly(self):
        # A key that no longer encodes its own OID: the walk still runs, and
        # visits this node somewhere it does not belong. Nothing raises.
        connection = sqlite3.connect(self.path)

        try:
            connection.execute(
                "UPDATE node SET oid_key = ? WHERE name = ?",
                (oid_key("1.3.6.1.4.1.1"), "testOther"),
            )
            connection.commit()

        finally:
            connection.close()

        self.assertIn("out of OID order", " ".join(validate(self.path)))

    def testReportsEveryProblemRatherThanTheFirst(self):
        # A build wants its whole list, not one round trip per defect.
        self.corrupt(
            "UPDATE module SET tier = 'enterprise'",
            "UPDATE node SET syntax = NULL WHERE name = 'testScalar'",
        )

        self.assertEqual(len(validate(self.path)), 2)

    def testReportsADamagedFileRatherThanRaising(self):
        # Damage does not come back as an answer: a page that will not decode
        # raises out of whichever query reaches it, integrity_check included.
        # This function is documented to return a list, so that has to become
        # one -- writing this test is how the raise was found.
        # A wide span rather than one short write at the midpoint: where the
        # midpoint lands depends on how many tables the schema has, and a
        # write that happens to fall in free space damages nothing.
        size = os.path.getsize(self.path)

        with open(self.path, "r+b") as fileObj:
            fileObj.seek(size // 4)
            fileObj.write(b"\xde\xad\xbe\xef" * (size // 8 // 4))

        problems = validate(self.path)

        self.assertTrue(problems)
        self.assertIn("SQLite", " ".join(problems))

    def testRefusesAFileThatIsNotACorpus(self):
        # open_db's job, asserted here so the two cannot drift: validate is
        # documented to raise for this rather than to report it as a problem.
        directory = tempfile.mkdtemp()
        path = os.path.join(directory, "empty.db")
        sqlite3.connect(path).close()

        with self.assertRaises(error.PySmiError):
            validate(path)


class ProfileTestCase(unittest.TestCase):
    """What each profile carries, and that the schema does not move with it.

    The point of the two profiles is that one reader serves both: a browser
    over ``search.db`` and pysnmp over ``core.db`` issue the same queries and
    differ only in which ones come back empty. So the schema is asserted
    identical here, not merely compatible -- a table or column that appeared
    in one and not the other would make ``meta.tables`` something a consumer
    has to branch on rather than something it can report.
    """

    corpus = {
        "TEST-MIB": document(
            testMib={
                "name": "testMib",
                "oid": "1.3.6.1.4.1.99",
                "class": "moduleidentity",
                "lastupdated": "2026-01-01 00:00",
                "revisions": [{"revision": "2026-01-01 00:00"}],
            },
            testScalar=scalar("1.3.6.1.4.1.99.1", "testScalar"),
            testOther=scalar("1.3.6.1.4.1.99.2", "testOther"),
            TestTC={
                "name": "TestTC",
                "class": "textualconvention",
                "status": "current",
                "type": {"type": "OCTET STRING", "class": "type"},
            },
            imports={"class": "imports", "SNMPv2-SMI": ["OBJECT-TYPE"]},
        ),
        # A second module defining one of the same names, which is the case
        # the name index exists for: "who defines testScalar" has two answers
        # and the corpus-wide direction has to give both.
        "OTHER-MIB": document(
            otherMib={
                "name": "otherMib",
                "oid": "1.3.6.1.4.1.98",
                "class": "moduleidentity",
            },
            testScalar=scalar("1.3.6.1.4.1.98.1", "testScalar"),
        ),
    }

    def build(self, tables):
        return build(
            self.corpus,
            tiers={"TEST-MIB": "vendor", "OTHER-MIB": "vendor"},
            ranked={"1.3.6.1.4.1.99": "TEST-MIB", "1.3.6.1.4.1.98": "OTHER-MIB"},
            tables=tables,
            provenance={
                "TEST-MIB": {"namespace": "test", "file": "TEST-MIB", "digest": "x"},
                "OTHER-MIB": {"namespace": "test", "file": "OTHER-MIB", "digest": "y"},
            },
        )

    #: Written out rather than composed, for the reason ``db.py`` writes its
    #: inserts out: a name interpolated into SQL reads the same whether or not
    #: it came from a literal.
    COUNTS = {
        "node": "SELECT count(*) FROM node",
        "type": "SELECT count(*) FROM type",
        "module": "SELECT count(*) FROM module",
        "symbol": "SELECT count(*) FROM symbol",
        "import": "SELECT count(*) FROM import",
        "provenance": "SELECT count(*) FROM provenance",
        "oid_index": "SELECT count(*) FROM oid_index",
    }

    def rows(self, path, table):
        db = open_db(path)

        try:
            return db.execute(self.COUNTS[table]).fetchone()[0]

        finally:
            db.close()

    def testFullIsTheDefault(self):
        path, _ = build(self.corpus)

        self.assertGreater(self.rows(path, "node"), 0)

    def testSearchCarriesNoNodesAndNoTypes(self):
        path, counts = self.build(SEARCH)

        for table in ("node", "type"):
            self.assertEqual(self.rows(path, table), 0)
            self.assertEqual(counts[table], 0)

    def testSearchCarriesWhatALookupNeeds(self):
        path, _ = self.build(SEARCH)

        for table in ("module", "symbol", "import", "provenance", "oid_index"):
            self.assertGreater(self.rows(path, table), 0, table)

    def testBothProfilesCarryTheSameSchema(self):
        shapes = []

        for tables in (FULL, SEARCH):
            path, _ = self.build(tables)
            db = open_db(path)

            try:
                shapes.append(
                    sorted(
                        db.execute(
                            "SELECT type, name, sql FROM sqlite_schema "
                            "WHERE name NOT LIKE 'sqlite_%'"
                        )
                    )
                )

            finally:
                db.close()

        self.assertEqual(shapes[0], shapes[1])

    def testMetaSaysWhichProfileWroteTheFile(self):
        for tables in (FULL, SEARCH):
            path, _ = self.build(tables)
            db = open_db(path)

            try:
                meta = dict(db.execute("SELECT key, value FROM meta"))

            finally:
                db.close()

            self.assertEqual(meta["tables"], tables)

    def testSearchStillStatesHowManyNodesTheCorpusHas(self):
        # An empty node table is a choice about this file, not a claim that
        # the corpus defines nothing. A consumer reporting corpus size must
        # get the same number from either profile.
        counted = {}

        for tables in (FULL, SEARCH):
            path, _ = self.build(tables)
            db = open_db(path)

            try:
                counted[tables] = (
                    dict(db.execute("SELECT key, value FROM meta"))["nodes"],
                    db.execute(
                        "SELECT nodes FROM module WHERE name = 'TEST-MIB'"
                    ).fetchone()[0],
                )

            finally:
                db.close()

        self.assertEqual(counted[FULL], counted[SEARCH])
        self.assertEqual(counted[SEARCH], ("5", 3))

    def testBothProfilesValidate(self):
        for tables in (FULL, SEARCH):
            path, _ = self.build(tables)

            self.assertEqual(validate(path), [], tables)

    def testValidateRefusesASearchFileCarryingNodes(self):
        # The label has to mean something. A file that says it carries no
        # nodes and does was written by something that did not mean it.
        path, _ = self.build(SEARCH)
        connection = sqlite3.connect(path)

        try:
            connection.execute(
                "INSERT INTO node VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (oid_key("1.3.6.1.4.1.99.3"), "TEST-MIB", "x", "1.3.6.1.4.1.99.3")
                + ("objecttype", "scalar", "current", "read-only")
                + (None, None, None, None, None),
            )
            connection.commit()

        finally:
            connection.close()

        self.assertIn("says it carries none", " ".join(validate(path)))

    def testEachProfileIsByteReproducible(self):
        # search.db is a published artifact, so it carries the same promise
        # core.db does: a rebuild that changed nothing publishes nothing.
        for tables in (FULL, SEARCH):
            one, _ = self.build(tables)
            two, _ = self.build(tables)

            with open(one, "rb") as first, open(two, "rb") as second:
                self.assertEqual(first.read(), second.read(), tables)

    def testRejectsAProfileItDoesNotWrite(self):
        with self.assertRaises(error.PySmiError):
            self.build("everything")
