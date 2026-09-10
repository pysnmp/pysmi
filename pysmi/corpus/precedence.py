#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The precedence rule, published as data so that a second copy cannot drift.

"Newest MODULE-IDENTITY revision wins, configured order breaks ties only" is
implemented three times, in two repositories that cannot import each other.
pysmi ranks a module found in several sources
(:py:func:`~pysmi.compiler.rank_by_revision`) and ranks modules anchored at
the same OID (:py:func:`~pysmi.corpus.index.rank_index`). pysnmp ranks the
same module found in several MIB directories, and again when several corpora
carry it. pysmi is an optional dependency of pysnmp, so pysnmp cannot import
the rule at runtime; pysmi cannot import pysnmp at all.

That leaves the agreement unchecked in both directions, and the disagreement
does not surface where it is caused. It surfaces when a trap decodes against
the wrong definition of a module, long after whichever side moved.

This module closes it the way :py:mod:`pysmi.corpus.conformance` closes the
reader contract: :py:data:`VECTORS` states the decisions, pysnmp asserts its
own implementations against the same file in its own CI, and
:py:func:`run_vectors` asserts pysmi's here. A change on either side that
would break the other fails in whichever project moved.

The vectors are plain data on purpose -- a reader in another language runs
them by reading this module's JSON rendering rather than by importing it.
Revisions are given in the normalised ``YYYYMMDDHHMMZ`` form that comparison
actually happens in, except in the ``normalise_revision`` vectors, which are
what pins that normalisation itself.
"""

import json
import os
from typing import Any, Final

from pysmi.compiler import (
    PRECEDENCE_EQUAL_REVISIONS,
    PRECEDENCE_NEWEST_REVISION,
    PRECEDENCE_NO_REVISION,
    rank_by_revision,
)
from pysmi.corpus.index import rank_index
from pysmi.mibinfo import normalise_revision

#: The OID every ``oid_precedence`` vector contends over.
#:
#: One arc, claimed by every candidate, so that nothing but the ranking rule
#: can decide it.
CONTESTED: Final = "1.3.6.1.4.1.99999.1"

#: Where a module that does not anchor :py:data:`CONTESTED` anchors instead.
ELSEWHERE: Final = "1.3.6.1.4.1.99999"


def _document(
    *,
    revision: str | None = None,
    anchor: str | None = "moduleidentity",
    obsolete: bool = False,
) -> dict[str, Any]:
    """A jsondoc carrying just enough to rank, and nothing else.

    Keyword Args:
        revision: the MODULE-IDENTITY revision. Ignored when *anchor* is
            ``None``, since the only place a module states one is a
            MODULE-IDENTITY, which is itself an anchor.
        anchor: how the module claims :py:data:`CONTESTED` --
            ``"moduleidentity"`` to register the arc as its own,
            ``"objectidentity"`` to register it while being anchored
            elsewhere, or ``None`` for a module carrying no anchor at all,
            which reaches the arc only by defining an object at it.
        obsolete: whether every object the module defines is obsolete.

    Returns:
        The module as ``JsonCodeGen`` would emit it, reduced to the fields
        :py:func:`~pysmi.corpus.index.module_rank` and
        :py:func:`~pysmi.corpus.index.oids_of` read.
    """
    # Every module defines an object, because "obsolete" is a property of the
    # objects: a module carrying none is not obsolete, it is empty. Where the
    # object sits depends on whether an anchor has already taken the arc --
    # a module with any anchor is read off its anchors alone, so an object at
    # CONTESTED would be invisible there and misleading here.
    document: dict[str, Any] = {
        "object": {
            "name": "object",
            "oid": CONTESTED if anchor is None else f"{CONTESTED}.1",
            "class": "objecttype",
            "nodetype": "scalar",
            "maxaccess": "read-only",
            "status": "obsolete" if obsolete else "current",
            "syntax": {"type": "Integer32", "class": "type"},
        }
    }

    if anchor is None:
        return document

    document["identity"] = {
        "name": "identity",
        "oid": CONTESTED if anchor == "moduleidentity" else ELSEWHERE,
        "class": "moduleidentity",
        "lastupdated": revision,
    }

    if anchor == "objectidentity":
        document["registration"] = {
            "name": "registration",
            "oid": CONTESTED,
            "class": "objectidentity",
            "status": "current",
        }

    return document


#: What every implementation of the precedence rule must answer.
#:
#: Each entry is ``{"id", "why", "op", ...}``. ``op`` names the operation and
#: the remaining keys are its arguments and its expected answer:
#:
#: ``normalise_revision``
#:     ``stamp`` to the normalised form comparison happens in, or ``null``
#:     where the stamp cannot be placed. Everything below rides on this: two
#:     implementations that agree on the ranking and disagree on the
#:     normalisation resolve differently anyway.
#: ``module_precedence``
#:     ``candidates``, in configured order, to the order they rank in and
#:     which rule put the winner first. This is the rule pysnmp implements in
#:     ``MibBuilder._candidates`` and in ``CompositeMibCorpus.best_by_revision``.
#: ``oid_precedence``
#:     ``modules``, each with its tier and publishing RFC, to the module that
#:     owns :py:data:`CONTESTED`. The corpus rule, which carries terms the
#:     module-name rule has nowhere to put.
#:
#: ``why`` is not decoration. A vector that fails should say what broke
#: without the reader's author having to reconstruct the intent.
VECTORS: Final[tuple[dict[str, Any], ...]] = (
    # Normalisation comes first because the ranking is a string comparison
    # over its output. A candidate whose stamp is widened differently, or
    # accepted where it should be refused, loses or wins every contest it
    # takes part in -- and does so consistently, which is what makes it look
    # like a ranking bug rather than a parsing one.
    {
        "id": "revision-wide-form-is-unchanged",
        "why": "The form RFC 2578 prefers is already what comparison wants.",
        "op": "normalise_revision",
        "stamp": "202401010000Z",
        "expect": "202401010000Z",
    },
    {
        "id": "revision-short-form-below-70-is-2000s",
        "why": "RFC 2578 Section 2: two-digit years under 70 are 2000s.",
        "op": "normalise_revision",
        "stamp": "0210160000Z",
        "expect": "200210160000Z",
    },
    {
        "id": "revision-short-form-from-70-is-1900s",
        "why": (
            "The pivot. Widened the other way, a 1999 revision sorts above a "
            "2002 one and the older copy wins for good."
        ),
        "op": "normalise_revision",
        "stamp": "9908190000Z",
        "expect": "199908190000Z",
    },
    {
        "id": "revision-that-is-not-a-date-is-refused",
        "why": (
            "HPR-MIB ships LAST-UPDATED 970514000000Z -- thirteen characters, "
            "read wide as year 9705 month 14. Ranked rather than refused it "
            "sorts above every date there will ever be."
        ),
        "op": "normalise_revision",
        "stamp": "970514000000Z",
        "expect": None,
    },
    {
        "id": "revision-of-the-wrong-length-is-refused",
        "why": "Neither of the two forms RFC 2578 admits.",
        "op": "normalise_revision",
        "stamp": "2024010100Z",
        "expect": None,
    },
    # The module-name rule. Three of the four implementations are this one.
    {
        "id": "module-newest-revision-beats-configured-order",
        "why": (
            "The whole rule in one case: the copy configured second wins "
            "because it is newer."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": "202001010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
        ],
        "expect": {
            "winner": 1,
            "order": [1, 0],
            "rule": PRECEDENCE_NEWEST_REVISION,
        },
    },
    {
        "id": "module-newest-revision-when-already-first",
        "why": (
            "The rule has to be applied, not skipped, when it agrees with "
            "configured order -- otherwise the reported rule is wrong even "
            "though the winner is right."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202001010000Z"},
        ],
        "expect": {
            "winner": 0,
            "order": [0, 1],
            "rule": PRECEDENCE_NEWEST_REVISION,
        },
    },
    {
        "id": "module-equal-revisions-fall-to-configured-order",
        "why": "Nothing to choose between them, so the caller's order stands.",
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
        ],
        "expect": {
            "winner": 0,
            "order": [0, 1],
            "rule": PRECEDENCE_EQUAL_REVISIONS,
        },
    },
    {
        "id": "module-one-undated-candidate-disables-the-comparison",
        "why": (
            "An undated copy cannot be placed against a dated one, so a "
            "single undated candidate leaves the whole decision to source "
            "order -- the dated one does not win by default."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": None},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
        ],
        "expect": {
            "winner": 0,
            "order": [0, 1],
            "rule": PRECEDENCE_NO_REVISION,
        },
    },
    {
        "id": "module-all-undated-candidates-fall-to-configured-order",
        "why": (
            "The usual case for the SMI modules themselves, which carry no "
            "MODULE-IDENTITY at all."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "SNMPv2-SMI", "revision": None},
            {"module": "SNMPv2-SMI", "revision": None},
        ],
        "expect": {
            "winner": 0,
            "order": [0, 1],
            "rule": PRECEDENCE_NO_REVISION,
        },
    },
    {
        "id": "module-newest-of-three-wins-and-the-losers-keep-their-order",
        "why": (
            "The losers are reported as shadowed copies, so their order is "
            "part of the answer and not only the winner's identity."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": "202001010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "201501010000Z"},
        ],
        "expect": {
            "winner": 1,
            "order": [1, 0, 2],
            "rule": PRECEDENCE_NEWEST_REVISION,
        },
    },
    {
        "id": "module-ties-among-the-newest-keep-configured-order",
        "why": (
            "The sort is stable: two copies sharing the newest revision are "
            "ranked against each other by the caller's order, not by chance."
        ),
        "op": "module_precedence",
        "candidates": [
            {"module": "EXAMPLE-MIB", "revision": "202001010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
            {"module": "EXAMPLE-MIB", "revision": "202406010000Z"},
        ],
        "expect": {
            "winner": 1,
            "order": [1, 2, 0],
            "rule": PRECEDENCE_NEWEST_REVISION,
        },
    },
    {
        "id": "module-a-single-candidate-is-not-a-contest",
        "why": (
            "Nothing was passed over, so no rule applies and none should be "
            "reported. A reader naming one here reports a precedence "
            "decision that was never taken."
        ),
        "op": "module_precedence",
        "candidates": [{"module": "EXAMPLE-MIB", "revision": "202406010000Z"}],
        "expect": {"winner": 0, "order": [0], "rule": ""},
    },
    # The corpus rule. Same principle, more terms, because a corpus knows
    # things a directory of files does not.
    {
        "id": "oid-newest-revision-wins",
        "why": "The module-name rule, reached through the corpus ranking.",
        "op": "oid_precedence",
        "modules": [
            {
                "module": "OLD-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2020-01-01 00:00"),
            },
            {
                "module": "NEW-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2024-06-01 00:00"),
            },
        ],
        "expect": "NEW-MIB",
    },
    {
        "id": "oid-obsolete-loses-to-live-however-new-it-is",
        "why": (
            "Obsolete outranks revision. A module whose every object is "
            "obsolete describes an arc nobody should decode against, and "
            "being republished later does not change that."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "OBSOLETE-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2024-06-01 00:00", obsolete=True),
            },
            {
                "module": "LIVE-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2020-01-01 00:00"),
            },
        ],
        "expect": "LIVE-MIB",
    },
    {
        "id": "oid-lower-tier-wins-over-a-newer-revision",
        "why": (
            "TIERS is (standard, draft, vendor). A vendor module "
            "republished yesterday does not displace the standard definition "
            "of an arc."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "VENDOR-MIB",
                "tier": 2,
                "rfc": 0,
                "document": _document(revision="2024-06-01 00:00"),
            },
            {
                "module": "STANDARD-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2020-01-01 00:00"),
            },
        ],
        "expect": "STANDARD-MIB",
    },
    {
        "id": "oid-module-identity-anchor-beats-object-identity",
        "why": (
            "How strongly a module claims the arc sits between tier and "
            "revision, and MODULE-IDENTITY is the strongest claim there is: "
            "a module whose own identity is the arc owns it over one that "
            "registers it with an OBJECT-IDENTITY while being anchored "
            "elsewhere, even a newer one."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "IDENTITY-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(
                    revision="2020-01-01 00:00", anchor="moduleidentity"
                ),
            },
            {
                "module": "REGISTERING-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(
                    revision="2024-06-01 00:00", anchor="objectidentity"
                ),
            },
        ],
        "expect": "IDENTITY-MIB",
    },
    {
        "id": "oid-higher-rfc-breaks-an-equal-revision",
        "why": (
            "Two modules published on one day are ordered by the RFC number "
            "that carries them, later winning."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "EARLIER-MIB",
                "tier": 0,
                "rfc": 1213,
                "document": _document(revision="2024-06-01 00:00"),
            },
            {
                "module": "LATER-MIB",
                "tier": 0,
                "rfc": 3418,
                "document": _document(revision="2024-06-01 00:00"),
            },
        ],
        "expect": "LATER-MIB",
    },
    {
        "id": "oid-module-name-makes-the-rule-total",
        "why": (
            "Two candidates alike in every term still have to resolve the "
            "same way on every machine, so the name is the last term. "
            "Without it the winner is whichever the corpus happened to walk "
            "first, and a rebuild can change it."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "B-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2024-06-01 00:00"),
            },
            {
                "module": "A-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2024-06-01 00:00"),
            },
        ],
        "expect": "A-MIB",
    },
    {
        "id": "oid-anchorless-module-loses-to-an-anchored-one",
        "why": (
            "A module with no anchor at all is read off its ordinary "
            "definitions, below every anchor, so a TEXTUAL-CONVENTIONS-only "
            "or SMIv1 module cannot take an arc from the module that "
            "registered it. It carries no revision either -- the only place "
            "a module states one is a MODULE-IDENTITY, which is an anchor -- "
            "so this is also where the corpus rule parts from the "
            "module-name rule: an undated candidate loses here instead of "
            "disabling the comparison, because a corpus has no source order "
            "to fall back to."
        ),
        "op": "oid_precedence",
        "modules": [
            {
                "module": "SMIV1-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(anchor=None),
            },
            {
                "module": "ANCHORED-MIB",
                "tier": 0,
                "rfc": 0,
                "document": _document(revision="2020-01-01 00:00"),
            },
        ],
        "expect": "ANCHORED-MIB",
    },
)


def vectors_as_json() -> str:
    """The vectors as JSON, for a harness that is not written in Python.

    Returns:
        :py:data:`VECTORS` rendered as an indented JSON array.
    """
    return json.dumps(list(VECTORS), indent=2, sort_keys=True) + "\n"


def write_vectors(directory: str) -> str:
    """Write the vectors where another project's harness can read them.

    Args:
        directory: where the file goes

    Returns:
        The path written.
    """
    os.makedirs(directory, exist_ok=True)

    path = os.path.join(directory, "precedence.json")

    with open(path, "w", encoding="utf-8", newline="") as fileObj:
        fileObj.write(vectors_as_json())

    return path


def run_vectors() -> list[str]:
    """Answer every vector with pysmi's own implementations.

    The point of running them here as well as in pysnmp: a vector states what
    both sides must do, so it has to be checked against this side too or it
    only ever constrains the other one.

    Returns:
        The ``id`` of each vector that was answered wrongly, empty when all
        of them were answered right.
    """
    failures: list[str] = []

    for vector in VECTORS:
        operation = vector["op"]
        answer: Any

        if operation == "normalise_revision":
            answer = normalise_revision(vector["stamp"])

        elif operation == "module_precedence":
            order, rule = rank_by_revision(
                [x["revision"] for x in vector["candidates"]]
            )
            answer = {"winner": order[0], "order": order, "rule": rule}

        elif operation == "oid_precedence":
            answer = rank_index(
                (x["module"], x["document"], x["tier"], x["rfc"])
                for x in vector["modules"]
            ).get(CONTESTED)

        else:  # pragma: no cover
            raise ValueError(f"unknown precedence operation {operation!r}")

        if answer != vector["expect"]:
            failures.append(vector["id"])

    return failures
