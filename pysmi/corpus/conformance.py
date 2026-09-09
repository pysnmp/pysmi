#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A fixed corpus and the answers any reader of it must give.

pysnmp reads :doc:`/corpus-schema` with stdlib ``sqlite3`` and no pysmi
import, which is the point of the layering: the contract between the two
repositories is data rather than code (pysnmp/pysnmp#196). That leaves pysnmp
with a reader whose correctness nothing here can check, and pysmi with a writer
whose consumer nothing there can check.

This module closes that: :py:func:`build_fixture` writes a small corpus whose
content is fixed, and :py:data:`VECTORS` states what a reader must answer about
it. pysnmp runs the vectors against its own reader in its own CI, and a change
here that would break it fails there rather than in a corpus rebuild months
later.

The fixture is **built rather than shipped**. A committed ``.db`` would be a
second copy of the writer's output, free to drift from the writer that is
supposed to have produced it; generating it means the fixture is always this
tree's writer over this tree's documents. It is deterministic, so two calls
produce one file.

The vectors are plain data on purpose. A reader in another language runs them
by reading this module's JSON rendering rather than by importing it.
"""

import json
import os
from typing import Any, Final

from pysmi.corpus.db import oid_key, subtree_bound, write_db

#: The modules the fixture carries, as ``JsonCodeGen`` would render them.
#:
#: Small, synthetic, and chosen for the cases that break readers rather than
#: for realism:
#:
#: ``FIXTURE-MIB``
#:     The ordinary shape -- a MODULE-IDENTITY anchor, a table with a row and
#:     columns, a scalar, a TEXTUAL-CONVENTION, an IMPORTS clause. Its column
#:     OIDs include the ``.9``/``.10``/``.256`` neighbours that catch a reader
#:     comparing OIDs as strings or packing an arc into one byte.
#: ``SHADOW-MIB``
#:     Defines an OID ``FIXTURE-MIB`` also defines, so a reader has to get the
#:     winner from ``oid_index`` rather than from whichever ``node`` row it
#:     met first. This is the ``1.3.6.1.6.3.1`` collision in miniature.
#: ``SMIV1-MIB``
#:     Declares no MODULE-IDENTITY, which SMIv1 modules do not, so
#:     ``module.oid`` and ``module.revision`` are NULL. A reader that assumes
#:     either is set fails on a large part of any real corpus.
#: ``DEEP-MIB``
#:     An anchor far down a long OID, so ``find_module`` has to chop many arcs
#:     before it resolves -- the ≤20-lookups-per-trap budget, exercised.
DOCUMENTS: Final[dict[str, dict[str, Any]]] = {
    "FIXTURE-MIB": {
        "imports": {
            "class": "imports",
            "SNMPv2-SMI": ["OBJECT-TYPE", "MODULE-IDENTITY"],
            "SNMPv2-TC": ["TEXTUAL-CONVENTION"],
        },
        "fixtureMib": {
            "name": "fixtureMib",
            "oid": "1.3.6.1.4.1.99999",
            "class": "moduleidentity",
            "lastupdated": "2026-01-01 00:00",
            "revisions": [
                {"revision": "2026-01-01 00:00"},
                {"revision": "2025-06-01 00:00"},
            ],
        },
        "FixtureString": {
            "name": "FixtureString",
            "class": "textualconvention",
            "status": "current",
            "displayhint": "255a",
            "type": {"type": "OCTET STRING", "class": "type"},
        },
        "fixtureScalar": {
            "name": "fixtureScalar",
            "oid": "1.3.6.1.4.1.99999.1",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "current",
            "syntax": {"type": "Integer32", "class": "type"},
            "units": "seconds",
        },
        "fixtureTable": {
            "name": "fixtureTable",
            "oid": "1.3.6.1.4.1.99999.2",
            "class": "objecttype",
            "nodetype": "table",
            "maxaccess": "not-accessible",
            "status": "current",
        },
        "fixtureEntry": {
            "name": "fixtureEntry",
            "oid": "1.3.6.1.4.1.99999.2.1",
            "class": "objecttype",
            "nodetype": "row",
            "maxaccess": "not-accessible",
            "status": "current",
            "indices": [
                {"module": "FIXTURE-MIB", "object": "fixtureIndex", "implied": 0}
            ],
        },
        "fixtureIndex": {
            "name": "fixtureIndex",
            "oid": "1.3.6.1.4.1.99999.2.1.1",
            "class": "objecttype",
            "nodetype": "column",
            "maxaccess": "not-accessible",
            "status": "current",
            "syntax": {
                "type": "Integer32",
                "class": "type",
                "constraints": {"range": [{"min": 1, "max": 65535}]},
            },
        },
        "fixtureDescr": {
            "name": "fixtureDescr",
            "oid": "1.3.6.1.4.1.99999.2.1.9",
            "class": "objecttype",
            "nodetype": "column",
            "maxaccess": "read-only",
            "status": "current",
            "syntax": {"type": "FixtureString", "class": "type"},
        },
        "fixtureTenth": {
            "name": "fixtureTenth",
            "oid": "1.3.6.1.4.1.99999.2.1.10",
            "class": "objecttype",
            "nodetype": "column",
            "maxaccess": "read-write",
            "status": "current",
            "syntax": {"type": "Integer32", "class": "type"},
            "default": {"format": "decimal", "value": 7},
        },
        "fixtureBig": {
            "name": "fixtureBig",
            "oid": "1.3.6.1.4.1.99999.2.1.256",
            "class": "objecttype",
            "nodetype": "column",
            "maxaccess": "read-only",
            "status": "deprecated",
            "syntax": {
                "type": "INTEGER",
                "class": "type",
                "constraints": {"enumeration": {"up": 1, "down": 2}},
            },
        },
        "meta": {"schema": 1},
    },
    "SHADOW-MIB": {
        "shadowMib": {
            "name": "shadowMib",
            "oid": "1.3.6.1.4.1.99998",
            "class": "moduleidentity",
            "lastupdated": "2020-01-01 00:00",
            "revisions": [{"revision": "2020-01-01 00:00"}],
        },
        "shadowScalar": {
            "name": "shadowScalar",
            "oid": "1.3.6.1.4.1.99999.1",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "current",
            "syntax": {"type": "Integer32", "class": "type"},
        },
        "meta": {"schema": 1},
    },
    "SMIV1-MIB": {
        "smiv1Anchor": {
            "name": "smiv1Anchor",
            "oid": "1.3.6.1.4.1.99996",
            "class": "objectidentity",
        },
        "smiv1Scalar": {
            "name": "smiv1Scalar",
            "oid": "1.3.6.1.4.1.99996.1",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "mandatory",
            "syntax": {"type": "OCTET STRING", "class": "type"},
        },
        "meta": {"schema": 1},
    },
    "DEEP-MIB": {
        "deepMib": {
            "name": "deepMib",
            "oid": "1.3.6.1.4.1.99997.1.2.3.4.5.6.7",
            "class": "moduleidentity",
            "lastupdated": "2026-01-01 00:00",
            "revisions": [{"revision": "2026-01-01 00:00"}],
        },
        "deepScalar": {
            "name": "deepScalar",
            "oid": "1.3.6.1.4.1.99997.1.2.3.4.5.6.7.1",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "current",
            "syntax": {"type": "Integer32", "class": "type"},
        },
        "meta": {"schema": 1},
    },
}

#: The tier each fixture module's namespace declares.
TIERS: Final[dict[str, str]] = {
    "FIXTURE-MIB": "standard",
    "SHADOW-MIB": "vendor",
    "SMIV1-MIB": "vendor",
    "DEEP-MIB": "vendor",
}

#: The ranked OID projection the fixture carries in ``oid_index``.
#:
#: ``1.3.6.1.4.1.99999.1`` is defined by both ``FIXTURE-MIB`` and
#: ``SHADOW-MIB`` and is *not* an anchor of either, so it is absent here on
#: purpose: a reader resolving it must chop back to ``1.3.6.1.4.1.99999``.
RANKED: Final[dict[str, str]] = {
    "1.3.6.1.4.1.99999": "FIXTURE-MIB",
    "1.3.6.1.4.1.99998": "SHADOW-MIB",
    "1.3.6.1.4.1.99996": "SMIV1-MIB",
    "1.3.6.1.4.1.99997.1.2.3.4.5.6.7": "DEEP-MIB",
}

#: The corpus version the fixture is stamped with.
CORPUS_VERSION: Final = "conformance-1"

#: What a reader must answer about the fixture.
#:
#: Each entry is ``{"id", "why", "op", ...}``. ``op`` names the operation and
#: the remaining keys are its arguments and its expected answer. A harness
#: dispatches on ``op``; the operations are the four
#: :doc:`/corpus-schema` specifies, plus ``meta`` for the version gate.
#:
#: ``why`` is not decoration. A vector that fails should say what broke
#: without the reader's author having to reconstruct the intent.
VECTORS: Final[tuple[dict[str, Any], ...]] = (
    {
        "id": "meta-schema-version",
        "why": "A reader gates on the schema version before it trusts a table.",
        "op": "meta",
        "key": "schema_version",
        "expect": "1",
    },
    {
        "id": "meta-corpus-version",
        "why": "Corpus version is separate from schema version, and is the "
        "build's own, not something the writer invented.",
        "op": "meta",
        "key": "corpus_version",
        "expect": CORPUS_VERSION,
    },
    {
        "id": "meta-no-texts",
        "why": "core.db carries no prose; a reader asked for loadTexts must "
        "say so rather than silently return nothing.",
        "op": "meta",
        "key": "texts",
        "expect": "0",
    },
    {
        "id": "find-module-anchor",
        "why": "An OID that is an anchor resolves on the first lookup.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.99999",
        "expect": "FIXTURE-MIB",
    },
    {
        "id": "find-module-leaf-chops-back",
        "why": "A leaf is not in the index -- the index carries anchors -- so "
        "find_module must chop arcs until one resolves.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.99999.2.1.9",
        "expect": "FIXTURE-MIB",
    },
    {
        "id": "find-module-instance-oid",
        "why": "A trap carries an instance OID, which is a column OID plus "
        "index arcs and is in no MIB at all.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.99999.2.1.9.1.2.3",
        "expect": "FIXTURE-MIB",
    },
    {
        "id": "find-module-deep",
        "why": "Chopping has to survive a deep anchor without giving up early.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.99997.1.2.3.4.5.6.7.1",
        "expect": "DEEP-MIB",
    },
    {
        "id": "find-module-shadowed",
        "why": "Two modules define this OID. The winner comes from the ranked "
        "index, not from whichever node row the reader met first.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.99999.1",
        "expect": "FIXTURE-MIB",
    },
    {
        "id": "find-module-miss",
        "why": "An unresolvable OID is a miss, not an error: an unknown OID "
        "still decodes structurally as far as the longest known prefix.",
        "op": "find_module",
        "oid": "1.3.6.1.4.1.1",
        "expect": None,
    },
    {
        "id": "node-scalar",
        "why": "The ordinary lookup: everything needed to render a value.",
        "op": "node",
        "oid": "1.3.6.1.4.1.99999.1",
        "module": "FIXTURE-MIB",
        "expect": {
            "name": "fixtureScalar",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "current",
            "units": "seconds",
            "syntax": {"class": "type", "type": "Integer32"},
        },
    },
    {
        "id": "node-column-with-tc-syntax",
        "why": "A syntax naming a TEXTUAL-CONVENTION stays unresolved -- "
        "binding it to an implementation class is the reader's job.",
        "op": "node",
        "oid": "1.3.6.1.4.1.99999.2.1.9",
        "module": "FIXTURE-MIB",
        "expect": {
            "name": "fixtureDescr",
            "class": "objecttype",
            "nodetype": "column",
            "maxaccess": "read-only",
            "status": "current",
            "units": None,
            "syntax": {"class": "type", "type": "FixtureString"},
        },
    },
    {
        "id": "node-without-a-syntax",
        "why": "A table has no SYNTAX, so its type reference is null. A "
        "reader must answer none rather than look up a type id of null.",
        "op": "node",
        "oid": "1.3.6.1.4.1.99999.2",
        "module": "FIXTURE-MIB",
        "expect": {
            "name": "fixtureTable",
            "class": "objecttype",
            "nodetype": "table",
            "maxaccess": "not-accessible",
            "status": "current",
            "units": None,
            "syntax": None,
        },
    },
    {
        "id": "node-absent",
        "why": "An OID the corpus does not define is absent, not an error -- "
        "the same reason find_module misses rather than raises.",
        "op": "node",
        "oid": "1.3.6.1.4.1.99999.2.1.4242",
        "module": "FIXTURE-MIB",
        "expect": None,
    },
    {
        "id": "node-defval",
        "why": "DEFVAL survives into the corpus; agent-side support needs it.",
        "op": "defval",
        "oid": "1.3.6.1.4.1.99999.2.1.10",
        "module": "FIXTURE-MIB",
        "expect": {"format": "decimal", "value": 7},
    },
    {
        "id": "node-enumeration-constraints",
        "why": "Constraints travel with the syntax, so a reader can range- "
        "and enum-check without going back to the MIB text.",
        "op": "syntax",
        "oid": "1.3.6.1.4.1.99999.2.1.256",
        "module": "FIXTURE-MIB",
        "expect": {
            "class": "type",
            "type": "INTEGER",
            "constraints": {"enumeration": {"up": 1, "down": 2}},
        },
    },
    {
        "id": "node-row-indices",
        "why": "INDEX is what turns instance arcs into index values, and it "
        "is attributed to the module that defines each element.",
        "op": "indices",
        "oid": "1.3.6.1.4.1.99999.2.1",
        "module": "FIXTURE-MIB",
        "expect": [{"module": "FIXTURE-MIB", "object": "fixtureIndex", "implied": 0}],
    },
    {
        "id": "node-by-name",
        "why": "importSymbols(module, name) is pysnmp's usual way in, so the "
        "name lookup has to be indexed too.",
        "op": "node_by_name",
        "module": "FIXTURE-MIB",
        "name": "fixtureTenth",
        "expect": "1.3.6.1.4.1.99999.2.1.10",
    },
    {
        "id": "next-node-numeric-order",
        "why": "9 then 10 then 256. A reader comparing OIDs as text gets 10 "
        "before 9; one packing an arc into a byte loses 256 entirely.",
        "op": "walk",
        "start": "1.3.6.1.4.1.99999.2.1",
        "count": 5,
        "expect": [
            "1.3.6.1.4.1.99999.2.1.1",
            "1.3.6.1.4.1.99999.2.1.9",
            "1.3.6.1.4.1.99999.2.1.10",
            "1.3.6.1.4.1.99999.2.1.256",
        ],
    },
    {
        "id": "next-node-crosses-modules",
        "why": "A walk is over the corpus, not over one module: 99997 and "
        "99998 are different modules and the step between them is ordinary.",
        "op": "next_node",
        "oid": "1.3.6.1.4.1.99997.1.2.3.4.5.6.7.1",
        "expect": "1.3.6.1.4.1.99998",
    },
    {
        "id": "next-node-past-a-shadowed-oid",
        "why": "Two modules define 99999.1. A walk visits the OID once, not "
        "once per module, or a GETNEXT loop never terminates.",
        "op": "walk",
        "start": "1.3.6.1.4.1.99999",
        "count": 2,
        "expect": ["1.3.6.1.4.1.99999.1", "1.3.6.1.4.1.99999.2"],
    },
    {
        "id": "next-node-end-of-corpus",
        "why": "Running off the end is endOfMibView, not an error.",
        "op": "next_node",
        "oid": "1.3.6.1.4.1.99999.99",
        "expect": None,
    },
    {
        "id": "subtree-is-a-range",
        "why": "A prefix encodes to a byte prefix, so a subtree is a range "
        "the primary key serves rather than a scan of the corpus.",
        "op": "subtree",
        "oid": "1.3.6.1.4.1.99999.2",
        "expect": [
            "1.3.6.1.4.1.99999.2",
            "1.3.6.1.4.1.99999.2.1",
            "1.3.6.1.4.1.99999.2.1.1",
            "1.3.6.1.4.1.99999.2.1.9",
            "1.3.6.1.4.1.99999.2.1.10",
            "1.3.6.1.4.1.99999.2.1.256",
        ],
    },
    {
        "id": "textual-convention-is-not-a-node",
        "why": "A TC declares a type and has no place in the OID tree. A "
        "reader offering it as a node offers a symbol no MIB registers.",
        "op": "symbol",
        "module": "FIXTURE-MIB",
        "name": "FixtureString",
        "expect": {
            "class": "textualconvention",
            "status": "current",
            "displayhint": "255a",
            "type": {"class": "type", "type": "OCTET STRING"},
        },
    },
    {
        "id": "shared-syntax-is-one-identity",
        "why": "Two nodes with the same syntax must resolve to one type id, "
        "or a reader caching classes against it makes two classes that "
        "one isinstance check has to tell apart.",
        "op": "same_syntax",
        "left": ["FIXTURE-MIB", "1.3.6.1.4.1.99999.1"],
        "right": ["FIXTURE-MIB", "1.3.6.1.4.1.99999.2.1.10"],
        "expect": True,
    },
    {
        "id": "import-resolves-to-defining-module",
        "why": "Resolving a syntax type name needs the module that defines "
        "it, and IMPORTS is where that is recorded.",
        "op": "import_source",
        "module": "FIXTURE-MIB",
        "name": "TEXTUAL-CONVENTION",
        "expect": "SNMPv2-TC",
    },
    {
        "id": "module-tier",
        "why": "Tier is declared by the build's manifest, not inferred from "
        "the MIB, and it is what ranks a standard module above a vendor one.",
        "op": "module_field",
        "module": "FIXTURE-MIB",
        "field": "tier",
        "expect": "standard",
    },
    {
        "id": "module-newest-revision",
        "why": "The newest revision, not the first listed or the last.",
        "op": "module_field",
        "module": "FIXTURE-MIB",
        "field": "revision",
        "expect": "202601010000Z",
    },
    {
        "id": "module-identity-oid",
        "why": "A module that declares a MODULE-IDENTITY records its OID.",
        "op": "module_field",
        "module": "SHADOW-MIB",
        "field": "oid",
        "expect": "1.3.6.1.4.1.99998",
    },
    {
        "id": "module-without-identity-oid",
        "why": "An SMIv1 module declares no MODULE-IDENTITY, so the column is "
        "nullable and a reader must not assume it is set.",
        "op": "module_field",
        "module": "SMIV1-MIB",
        "field": "oid",
        "expect": None,
    },
    {
        "id": "module-without-identity-revision",
        "why": "Same module, same reason: no MODULE-IDENTITY means no "
        "REVISION and no LAST-UPDATED, so the revision is null rather than "
        "an empty string a reader might sort against.",
        "op": "module_field",
        "module": "SMIV1-MIB",
        "field": "revision",
        "expect": None,
    },
)


def build_fixture(path: str) -> str:
    """Write the conformance corpus.

    Deterministic: two calls produce byte-identical files, so a harness may
    cache it and a test may assert on its digest.

    Args:
        path: where to write it. An existing file there is replaced.

    Returns:
        The path written, for convenience in a fixture chain.
    """
    write_db(
        path,
        [(name, document, 0, 0) for name, document in DOCUMENTS.items()],
        TIERS,
        ranked=RANKED,
        corpusVersion=CORPUS_VERSION,
        corpusId="pysmi-conformance",
    )

    return path


def vectors_as_json() -> str:
    """The vectors as JSON, for a harness that is not written in Python.

    Returns:
        :py:data:`VECTORS` rendered as an indented JSON array.
    """
    return json.dumps(list(VECTORS), indent=2, sort_keys=True) + "\n"


def write_fixture(directory: str) -> tuple[str, str]:
    """Write the corpus and the vectors side by side.

    Args:
        directory: where both go

    Returns:
        ``(database, vectors)``, the two paths.
    """
    os.makedirs(directory, exist_ok=True)

    database = build_fixture(os.path.join(directory, "conformance.db"))
    vectors = os.path.join(directory, "vectors.json")

    with open(vectors, "w", encoding="utf-8", newline="") as fileObj:
        fileObj.write(vectors_as_json())

    return database, vectors


#: Reference queries, so a reader's author can see the intended shape.
#:
#: Not the only correct implementation -- a reader is free to prepare these
#: differently -- but every one of them is what
#: :doc:`/corpus-schema` describes, and
#: :py:data:`VECTORS` is answerable with nothing else.
QUERIES: Final[dict[str, str]] = {
    "meta": "SELECT value FROM meta WHERE key = ?",
    "find_module": "SELECT module FROM oid_index WHERE oid_key = ?",
    "node": (
        "SELECT name, class, nodetype, maxaccess, status, units, syntax, "
        "defval, indices, augments FROM node WHERE oid_key = ? AND module = ?"
    ),
    "node_by_name": "SELECT oid FROM node WHERE module = ? AND name = ?",
    "next_node": (
        "SELECT oid FROM node WHERE oid_key > ? ORDER BY oid_key, module LIMIT 1"
    ),
    "subtree": (
        "SELECT DISTINCT oid FROM node WHERE oid_key >= ? AND oid_key < ? "
        "ORDER BY oid_key"
    ),
    "symbol": (
        "SELECT class, status, displayhint, type FROM symbol "
        "WHERE module = ? AND name = ?"
    ),
    "type": "SELECT spec FROM type WHERE id = ?",
    "import_source": "SELECT source FROM import WHERE module = ? AND name = ?",
}


def run_vectors(connection: Any) -> list[str]:
    """Run every vector against an open corpus, using :py:data:`QUERIES`.

    This is the reference harness. pysnmp runs the same vectors against its
    own reader instead, which is the point -- but a failure here says the
    fixture and the writer disagree, which is a different bug from a reader
    that disagrees with both.

    Args:
        connection: an open corpus, as
            :py:func:`~pysmi.corpus.db.open_db` returns

    Returns:
        The ``id`` of every vector that did not answer as expected, in order.
        Empty when the corpus conforms.
    """
    failures = []

    def spec(identifier: Any) -> Any:
        if identifier is None:
            return None

        row = connection.execute(QUERIES["type"], (identifier,)).fetchone()

        return json.loads(row[0]) if row else None

    for vector in VECTORS:
        operation = vector["op"]

        if operation == "meta":
            row = connection.execute(QUERIES["meta"], (vector["key"],)).fetchone()
            answer = row[0] if row else None

        elif operation == "find_module":
            answer = None
            parts = vector["oid"].split(".")

            while parts:
                row = connection.execute(
                    QUERIES["find_module"], (oid_key(".".join(parts)),)
                ).fetchone()

                if row:
                    answer = row[0]
                    break

                parts.pop()

        elif operation in ("node", "syntax", "defval", "indices"):
            row = connection.execute(
                QUERIES["node"], (oid_key(vector["oid"]), vector["module"])
            ).fetchone()

            if row is None:
                answer = None

            elif operation == "syntax":
                answer = spec(row[6])

            elif operation == "defval":
                answer = json.loads(row[7]) if row[7] else None

            elif operation == "indices":
                answer = json.loads(row[8]) if row[8] else None

            else:
                answer = {
                    "name": row[0],
                    "class": row[1],
                    "nodetype": row[2],
                    "maxaccess": row[3],
                    "status": row[4],
                    "units": row[5],
                    "syntax": spec(row[6]),
                }

        elif operation == "node_by_name":
            row = connection.execute(
                QUERIES["node_by_name"], (vector["module"], vector["name"])
            ).fetchone()
            answer = row[0] if row else None

        elif operation == "next_node":
            row = connection.execute(
                QUERIES["next_node"], (oid_key(vector["oid"]),)
            ).fetchone()
            answer = row[0] if row else None

        elif operation == "walk":
            answer = []
            at = oid_key(vector["start"])

            for _ in range(vector["count"]):
                row = connection.execute(QUERIES["next_node"], (at,)).fetchone()

                if row is None:
                    break

                answer.append(row[0])
                at = oid_key(row[0])

        elif operation == "subtree":
            low = oid_key(vector["oid"])
            answer = [
                x[0]
                for x in connection.execute(
                    QUERIES["subtree"], (low, subtree_bound(low))
                )
            ]

        elif operation == "symbol":
            row = connection.execute(
                QUERIES["symbol"], (vector["module"], vector["name"])
            ).fetchone()
            answer = (
                None
                if row is None
                else {
                    "class": row[0],
                    "status": row[1],
                    "displayhint": row[2],
                    "type": spec(row[3]),
                }
            )

        elif operation == "same_syntax":
            ids = [
                connection.execute(QUERIES["node"], (oid_key(oid), module)).fetchone()[
                    6
                ]
                for module, oid in (vector["left"], vector["right"])
            ]
            answer = ids[0] is not None and ids[0] == ids[1]

        elif operation == "import_source":
            row = connection.execute(
                QUERIES["import_source"], (vector["module"], vector["name"])
            ).fetchone()
            answer = row[0] if row else None

        elif operation == "module_field":
            # The field is one of this module's own literals, never a caller's.
            row = connection.execute(
                f"SELECT {vector['field']} FROM module WHERE name = ?",  # noqa: S608
                (vector["module"],),
            ).fetchone()
            answer = row[0] if row else None

        else:  # pragma: no cover
            raise ValueError(f"unknown conformance operation {operation!r}")

        if answer != vector["expect"]:
            failures.append(vector["id"])

    return failures
