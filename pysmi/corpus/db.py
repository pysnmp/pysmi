#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The corpus database: the SMI model laid out for lookup rather than for reading.

``core.db`` answers three questions a runtime asks and the published artifacts
cannot:

*Which module owns this OID?* ``index-v2.csv`` answers that already, and this
carries the same projection in :py:data:`SCHEMA` for consumers that would
rather not parse a second file.

*What is the node at this OID?* The CSV cannot say -- it is ``MODULE,OID`` and
nothing else, and it indexes a module's *anchors*, so ``ifDescr`` is not in it
at all. Answering from the published ``json/`` tree means parsing the whole
module: 11 ms and 9,773 symbols of ``CISCO-ENTITY-VENDORTYPE-OID-MIB`` to reach
one of them. Here it is one row.

*What comes after this OID?* Nothing published answers it. An anchor index has
no per-node ordering, so a GETNEXT walk cannot be served from one at all.

What this deliberately does not carry is prose. DESCRIPTION and REFERENCE are
roughly a third of a module's bytes, the runtime discards them under the
default ``loadTexts=False``, and the ``json/`` tree already serves the one
consumer that wants them -- a MIB browser. See :doc:`/mibs-as-data`.

Determinism
-----------

Two runs over the same sources produce the same bytes. That rules out the
obvious things -- no build timestamp, no host name, no producer version -- and
some less obvious ones: rows are inserted in a fixed order so the b-tree is
laid out identically, and the file is VACUUMed so no free page survives to
record how it was filled. A caller that wants its build stamped passes
``corpusVersion``, which is data it chose rather than data we observed.

Ordering OIDs as bytes
----------------------

The label for this section lives in :doc:`/corpus-schema`, which is the
specification a reader is written from; defining it here as well would be two
anchors for one contract.

SQLite compares BLOBs bytewise, so the encoding has to make bytewise order
equal numeric OID order. Dotted decimal does not: ``"1.3.10"`` sorts below
``"1.3.9"``. Fixed-width arcs do not either, since a sub-identifier is
unbounded in principle and 32-bit in practice, and four bytes per arc is most
of the file.

:py:func:`oid_key` encodes each arc as a length byte followed by that many
big-endian bytes. Comparing two encodings compares the length bytes first, and
a longer arc is a larger arc, so the order is right without the padding. Two
properties fall out and both are load-bearing:

* An OID that is a prefix of another encodes to a byte prefix of its encoding,
  so a subtree is a range rather than a scan.
* A prefix sorts before everything under it, so ``oid_key > ?`` ordered
  ascending is GETNEXT.
"""

import json
import os
import sqlite3
from collections.abc import Iterable, Iterator
from typing import Any, Final

from pysmi import __version__ as pysmi_version
from pysmi import error
from pysmi.codegen.normalized import content_hash
from pysmi.corpus.index import arcs, newest_revision
from pysmi.corpus.namespace import DEFAULT_TIER

#: The schema version this module writes, stamped into ``meta`` and into the
#: database's own ``user_version`` header field.
#:
#: A consumer gates on it and refuses what it does not understand. It is
#: deliberately not the corpus version: conflating the two would force a
#: pysnmp release on every corpus rebuild (pysnmp/pysnmp#196).
SCHEMA_VERSION: Final = 1

#: SQLite's ``application_id``, so ``file`` and any other tool that reads the
#: header can tell a corpus from an unrelated database. "PSMI" as big-endian
#: ASCII.
APPLICATION_ID: Final = 0x50534D49

#: The largest sub-identifier :py:func:`oid_key` will encode. RFC 2578 section
#: 7.1.3 makes a sub-identifier a 32-bit unsigned integer, and the length byte
#: leaves room for more than that anyway; the check is here so a malformed OID
#: fails where it is read rather than as a mis-sorted row much later.
MAX_ARC: Final = 0xFFFFFFFF

#: Symbol classes that carry an OID and are therefore nodes in the tree.
#:
#: Everything else a module declares -- a TEXTUAL-CONVENTION, a type
#: assignment -- is a symbol without a place in the OID tree, and goes to
#: :py:data:`SCHEMA`'s ``symbol`` table instead.
NODE_CLASSES: Final[frozenset[str]] = frozenset(
    {
        "objecttype",
        "objectidentity",
        "moduleidentity",
        "notificationtype",
        "objectgroup",
        "notificationgroup",
        "modulecompliance",
        "agentcapabilities",
    }
)

#: Symbol classes that declare a type rather than a node.
SYMBOL_CLASSES: Final[frozenset[str]] = frozenset({"textualconvention", "type"})

#: The schema, as the statements that create it.
#:
#: ``WITHOUT ROWID`` throughout: every table here is keyed by something the
#: reader actually looks up, so the implicit rowid would be a second key that
#: nothing queries and that every index would carry a copy of.
SCHEMA: Final[tuple[str, ...]] = (
    """
    CREATE TABLE meta (
        key   TEXT PRIMARY KEY,
        value TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE module (
        name         TEXT PRIMARY KEY,
        tier         TEXT NOT NULL,
        oid          TEXT,
        lastupdated  TEXT,
        revision     TEXT,
        content_hash TEXT NOT NULL,
        nodes        INTEGER NOT NULL
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE type (
        id   INTEGER PRIMARY KEY,
        spec TEXT NOT NULL UNIQUE
    )
    """,
    """
    CREATE TABLE node (
        oid_key   BLOB NOT NULL,
        module    TEXT NOT NULL,
        name      TEXT NOT NULL,
        oid       TEXT NOT NULL,
        class     TEXT NOT NULL,
        nodetype  TEXT,
        status    TEXT,
        maxaccess TEXT,
        units     TEXT,
        syntax    INTEGER,
        defval    TEXT,
        indices   TEXT,
        augments  TEXT,
        PRIMARY KEY (oid_key, module)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE symbol (
        module      TEXT NOT NULL,
        name        TEXT NOT NULL,
        class       TEXT NOT NULL,
        status      TEXT,
        displayhint TEXT,
        type        INTEGER,
        PRIMARY KEY (module, name)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE import (
        module TEXT NOT NULL,
        name   TEXT NOT NULL,
        source TEXT NOT NULL,
        PRIMARY KEY (module, name)
    ) WITHOUT ROWID
    """,
    """
    CREATE TABLE oid_index (
        oid_key BLOB PRIMARY KEY,
        oid     TEXT NOT NULL,
        module  TEXT NOT NULL
    ) WITHOUT ROWID
    """,
    "CREATE INDEX node_by_module ON node (module, oid_key)",
    "CREATE INDEX node_by_name ON node (module, name)",
)


#: The row inserts, written out rather than composed.
#:
#: Composing ``INSERT INTO {table}`` from a name is safe here -- the names are
#: this module's own literals -- but it is indistinguishable at a glance from
#: the shape that is not safe, and a reviewer should not have to trace a
#: variable to tell which one this is.
_INSERT_NODE: Final = "INSERT OR REPLACE INTO node VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)"
_INSERT_SYMBOL: Final = "INSERT OR REPLACE INTO symbol VALUES (?,?,?,?,?,?)"
_INSERT_IMPORT: Final = "INSERT OR REPLACE INTO import VALUES (?,?,?)"


def oid_key(oid: str) -> bytes:
    """Encode an OID so that bytewise order is numeric order.

    See :ref:`corpus-oid-key` for why the encoding is shaped this way.

    Args:
        oid: dotted decimal, as a jsondoc writes it

    Returns:
        The sort key.

    Raises:
        PySmiError: the OID is not dotted decimal, or an arc is out of range.
    """
    parts = arcs(oid)

    if not parts:
        raise error.PySmiError(f"not an OID: {oid!r}")

    out = bytearray()

    for arc in parts:
        if arc < 0 or arc > MAX_ARC:
            raise error.PySmiError(f"sub-identifier out of range in {oid!r}: {arc}")

        width = max(1, (arc.bit_length() + 7) // 8)
        out.append(width)
        out += arc.to_bytes(width, "big")

    return bytes(out)


def oid_from_key(key: bytes) -> str:
    """Decode what :py:func:`oid_key` encoded.

    Args:
        key: the sort key

    Returns:
        The OID, dotted decimal.

    Raises:
        PySmiError: the key is truncated or otherwise not one of ours.
    """
    parts: list[str] = []
    at = 0

    while at < len(key):
        width = key[at]
        at += 1

        if width < 1 or at + width > len(key):
            raise error.PySmiError(f"truncated OID key at byte {at}")

        parts.append(str(int.from_bytes(key[at : at + width], "big")))
        at += width

    if not parts:
        raise error.PySmiError("empty OID key")

    return ".".join(parts)


def subtree_bound(key: bytes) -> bytes:
    """The exclusive upper bound of the subtree rooted at *key*.

    ``oid_key >= key AND oid_key < subtree_bound(key)`` is every node at or
    below that OID, which is a range the primary key serves directly.

    Args:
        key: an encoded OID, as :py:func:`oid_key` returns

    Returns:
        The first key that sorts above every descendant.
    """
    out = bytearray(key)

    while out and out[-1] == 0xFF:
        out.pop()

    if not out:
        # Every byte was 0xFF, so nothing sorts above it; SQLite has no
        # +infinity for a BLOB, and one more byte does the same job.
        return bytes(key) + b"\xff"

    out[-1] += 1

    return bytes(out)


def _text(value: Any) -> str | None:
    """A string column's value, or ``None`` when the module declared none."""
    return value if isinstance(value, str) and value else None


def _blob(value: Any) -> str | None:
    """A structured column's value as compact JSON, or ``None`` when absent.

    Sorted keys, no incidental whitespace: the column is compared and hashed by
    consumers, so two runs must render one structure one way.
    """
    if value in (None, {}, []):
        return None

    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _module_row(
    module: str, document: dict[str, Any], tier: str, nodes: int
) -> tuple[Any, ...]:
    """The ``module`` row for one jsondoc.

    Args:
        module: the module's descriptor
        document: the jsondoc
        tier: the tier its namespace declared
        nodes: how many rows this module actually contributed to ``node``.
            Passed in rather than counted here: the two would be counted by
            different rules -- this one would include the ``pysmiFakeCol``
            templates and the duplicate OIDs the writer collapses -- and a
            column that disagrees with ``SELECT count(*)`` is worse than no
            column.
    """
    identity = next(
        (
            x
            for x in document.values()
            if isinstance(x, dict) and x.get("class") == "moduleidentity"
        ),
        {},
    )

    return (
        module,
        tier,
        _text(identity.get("oid")),
        _text(identity.get("lastupdated")),
        newest_revision(document) or None,
        content_hash(document),
        nodes,
    )


def _node_rows(
    module: str, document: dict[str, Any], types: dict[str, int]
) -> Iterator[tuple[Any, ...]]:
    """The ``node`` rows for one jsondoc, in OID order.

    A symbol whose OID is a ``pysmiFakeCol`` template is skipped: it has no
    place in the tree until a row OID resolves it, and a corpus is not where
    that happens.
    """
    rows = []

    for name, symbol in document.items():
        if not isinstance(symbol, dict):
            continue

        oid = symbol.get("oid")

        if symbol.get("class") not in NODE_CLASSES or not isinstance(oid, str):
            continue

        if "%s" in oid:
            continue

        rows.append(
            (
                oid_key(oid),
                module,
                name,
                oid,
                symbol["class"],
                _text(symbol.get("nodetype")),
                _text(symbol.get("status")),
                _text(symbol.get("maxaccess")),
                _text(symbol.get("units")),
                types.get(_blob(symbol.get("syntax")) or ""),
                _blob(symbol.get("default")),
                _blob(symbol.get("indices")),
                _blob(symbol.get("augmentation")),
            )
        )

    yield from sorted(rows, key=lambda row: (row[0], row[2]))


def _symbol_rows(
    module: str, document: dict[str, Any], types: dict[str, int]
) -> Iterator[tuple[Any, ...]]:
    """The ``symbol`` rows for one jsondoc, in name order."""
    rows = []

    for name, symbol in document.items():
        if not isinstance(symbol, dict) or symbol.get("class") not in SYMBOL_CLASSES:
            continue

        rows.append(
            (
                module,
                name,
                symbol["class"],
                _text(symbol.get("status")),
                _text(symbol.get("displayhint")),
                types.get(_blob(symbol.get("type")) or ""),
            )
        )

    yield from sorted(rows, key=lambda row: row[1])


def _type_specs(document: dict[str, Any]) -> Iterator[str]:
    """Every distinct type specification one jsondoc uses, as stored JSON.

    A syntax is quoted in full on every object that has it, and a corpus
    repeats a handful of them tens of thousands of times -- ``DisplayString``
    with one size constraint accounts for a whole class of columns on its own.
    Storing each once is worth the join twice over: it takes bytes out of the
    hottest table, and it hands a reader a stable identity for "this is the
    same type", which is what keeps class synthesis from making two classes one
    ``isinstance`` check has to tell apart (pysnmp/pysnmp#145).
    """
    for symbol in document.values():
        if not isinstance(symbol, dict):
            continue

        for key in ("syntax", "type"):
            spec = _blob(symbol.get(key))

            if spec:
                yield spec


def _import_rows(module: str, document: dict[str, Any]) -> Iterator[tuple[Any, ...]]:
    """The ``import`` rows for one jsondoc, in name order.

    A reader synthesizing a class needs to know which module defines the type a
    syntax names, and the IMPORTS clause is where that is recorded. One row per
    imported symbol rather than per clause, because the lookup is by symbol.
    """
    imports = document.get("imports")

    if not isinstance(imports, dict):
        return

    rows = []

    for source, names in imports.items():
        if source == "class" or not isinstance(names, list):
            continue

        for name in names:
            if isinstance(name, str):
                rows.append((module, name, source))

    yield from sorted(rows, key=lambda row: row[1])


def _connect(path: str) -> sqlite3.Connection:
    """Create the database file and open it ready to be filled.

    The file is created through :py:func:`os.open` with 0666 for the same
    reason ``pysmi.writer.base`` does it: a corpus published from a build that
    ran under a restrictive umask is readable only by the uid that built it,
    which is invisible until a container running as another user answers 403
    for every module (pysnmp/mibs#365).
    """
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    if os.path.exists(path):
        os.unlink(path)

    os.close(os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666))

    connection = sqlite3.connect(path)

    # A published corpus is opened read-only, often with ``immutable=1``, so it
    # must be one file with nothing alongside it: DELETE rather than WAL, which
    # would leave a -wal a reader cannot replay and immutable=1 forbids.
    connection.execute("PRAGMA journal_mode = DELETE")
    connection.execute("PRAGMA synchronous = OFF")
    connection.execute(f"PRAGMA application_id = {APPLICATION_ID}")
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    for statement in SCHEMA:
        connection.execute(statement)

    return connection


def write_db(
    path: str,
    documents: "Iterable[tuple[str, dict[str, Any], int, int]]",
    tiers: dict[str, str],
    ranked: dict[str, str] | None = None,
    corpusVersion: str | None = None,
    corpusId: str | None = None,
) -> dict[str, int]:
    """Write a corpus database.

    Args:
        path: where to write it. An existing file there is replaced.
        documents: ``(module, jsondoc, tier, rfc)`` per module, as
            :py:func:`pysmi.corpus.index.read_documents` yields them.
        tiers: module name to the tier its namespace declared, used for the
            ``module`` table's own column.
        ranked: the OID-to-module projection to carry in ``oid_index``, as
            :py:func:`pysmi.corpus.index.rank_index` returns. Omitted leaves
            the table empty, which a reader treats as "no index" rather than
            as "no modules".
        corpusVersion: what to stamp the build as. Recorded verbatim; nothing
            here invents one, because a value we observed rather than were
            given would make two builds of one source tree differ.
        corpusId: a stable name for the corpus this is a build of, so a
            consumer can tell two corpora apart when both are version 3.

    Returns:
        How many rows each table received, keyed by table name.

    Raises:
        PySmiError: a document carried an OID that cannot be encoded.
    """
    connection = _connect(path)
    counts = dict.fromkeys(
        ("module", "type", "node", "symbol", "import", "oid_index", "meta"), 0
    )

    # Sorted by module name so the b-tree is filled in one order whatever order
    # the caller iterates in.
    corpus = sorted(documents, key=lambda x: x[0])

    try:
        # Type specifications first, ids assigned in sorted order so that two
        # builds of one source tree number them identically.
        specs = sorted({spec for _, doc, _, _ in corpus for spec in _type_specs(doc)})
        types = {spec: n for n, spec in enumerate(specs, start=1)}

        connection.executemany(
            "INSERT INTO type VALUES (?,?)", [(n, spec) for spec, n in types.items()]
        )
        counts["type"] = len(types)

        for module, document, _, _ in corpus:
            tier = tiers.get(module, DEFAULT_TIER)

            # Materialized before the module row is written, because that row
            # records how many nodes this module contributed and the only
            # honest source for that is what was inserted. INSERT OR REPLACE
            # over the (oid_key, module) key collapses a module that declares
            # one OID twice, so the batch length is not it either.
            nodes = list(_node_rows(module, document, types))
            stored = len({(row[0], row[1]) for row in nodes})

            connection.execute(
                "INSERT OR REPLACE INTO module VALUES (?,?,?,?,?,?,?)",
                _module_row(module, document, tier, stored),
            )
            counts["module"] += 1
            counts["node"] += stored

            if nodes:
                connection.executemany(_INSERT_NODE, nodes)

            for table, statement, rows in (
                ("symbol", _INSERT_SYMBOL, _symbol_rows(module, document, types)),
                ("import", _INSERT_IMPORT, _import_rows(module, document)),
            ):
                batch = list(rows)

                if batch:
                    connection.executemany(statement, batch)
                    counts[table] += len(batch)

        if ranked:
            connection.executemany(
                "INSERT OR REPLACE INTO oid_index VALUES (?,?,?)",
                [(oid_key(oid), oid, ranked[oid]) for oid in sorted(ranked, key=arcs)],
            )
            counts["oid_index"] = len(ranked)

        meta = {
            "schema_version": str(SCHEMA_VERSION),
            "producer": "pysmi",
            "modules": str(counts["module"]),
            "nodes": str(counts["node"]),
            "types": str(counts["type"]),
            "texts": "0",
        }

        if corpusVersion:
            meta["corpus_version"] = corpusVersion

        if corpusId:
            meta["corpus_id"] = corpusId

        connection.executemany(
            "INSERT OR REPLACE INTO meta VALUES (?,?)", sorted(meta.items())
        )
        counts["meta"] = len(meta)

        connection.commit()

        # Last, and in this order: ANALYZE so the query planner has statistics
        # without the reader having to run it against a read-only file, then
        # VACUUM so no free page survives to record how the file was filled.
        connection.execute("ANALYZE")
        connection.commit()
        connection.execute("VACUUM")

    finally:
        connection.close()

    return counts


def open_db(path: str) -> sqlite3.Connection:
    """Open a corpus database the way a consumer should.

    ``immutable=1`` tells SQLite the file cannot change, so it takes no locks
    and needs no writable directory -- which is what lets a corpus be mounted
    read-only from an image volume.

    Args:
        path: the database

    Returns:
        The open connection.

    Raises:
        PySmiError: the file is not a corpus, or is a schema version this
            pysmi does not know how to read.
    """
    uri = f"file:{os.path.abspath(path)}?immutable=1"
    connection = sqlite3.connect(uri, uri=True)

    try:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        application = connection.execute("PRAGMA application_id").fetchone()[0]

    except sqlite3.DatabaseError as exc:
        connection.close()
        raise error.PySmiError(f"not a corpus database: {path}") from exc

    if application != APPLICATION_ID:
        connection.close()
        raise error.PySmiError(
            f"not a corpus database: {path} carries application_id {application}"
        )

    if version != SCHEMA_VERSION:
        connection.close()
        raise error.PySmiError(
            f"corpus schema version {version} in {path}, "
            f"but this pysmi {pysmi_version} writes and reads {SCHEMA_VERSION}"
        )

    return connection
