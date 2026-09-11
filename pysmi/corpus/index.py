#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Deciding which module owns an OID, and rendering that as an index.

:py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_index` records the complete
fact: every module that defines a given OID, all of them. A consumer that
resolves an OID to *one* module to load -- splunk-connect-for-snmp does
exactly this, on every trap -- needs a winner instead, and a winner is a lossy
projection of that fact. This module computes the projection; ``gen_index()``
keeps recording the fact.

The rule ranks a module by five terms, best first:

1. **Live before obsolete.** A module whose every OBJECT-TYPE and
   NOTIFICATION-TYPE is ``obsolete`` loses to one that still defines
   something.
2. **Tier.** Standard, then Internet-Draft, then vendor. This is the one term
   that is not a property of the MIB text: it is declared per source
   namespace by the build's manifest, because "standard" is a statement about
   where a module comes from -- see :py:mod:`pysmi.corpus.namespace`.
3. **Owner before mention.** A MODULE-IDENTITY on an arc outranks an
   OBJECT-IDENTITY on that same arc. ``CLAB-DEF-MIB`` registers
   ``clabTopoMib`` so its siblings can hang objects off it, but
   ``CLAB-TOPO-MIB`` is the module that arc belongs to.
4. **Newest revision.** The latest MODULE-IDENTITY REVISION, read through
   ``normalise_revision`` -- the same check the
   compiler applies when it chooses between two copies of one module, so a
   stamp that is not a date cannot win here either.
5. **RFC number, then module name.** The later RFC wins, which settles the
   SMI root arcs: RFC1065-SMI, RFC1155-SMI and SNMPv2-SMI define them
   identically, none of the three carries a MODULE-IDENTITY to compare, and
   without this term the winner is whichever name sorts first -- which is how
   RFC1065-SMI came to own ten arcs that RFC 2578 defines. Supersession
   cannot decide it, since RFC 1155 is STD 16 and still an Internet
   Standard; publication order can. A module no RFC publishes ranks below
   every module one does, and the module name is the final tie-break, so the
   rule is total.

Adapted from ``index.py`` in pysnmp/mibs, which is where this rule was worked
out; the difference is that the tier arrives declared rather than inferred
from a directory layout, and that revisions go through
``normalise_revision``. See pysnmp/pysmi#182 and pysnmp/mibs#352.
"""

import csv
import io
import logging
import os
from collections.abc import Iterable, Iterator
from typing import Any, Final

from pysmi import jsonio
from pysmi.mibinfo import normalise_revision

logger = logging.getLogger(__name__)

#: Classes that make a module the owner of an arc rather than a mention of
#: it, and how they rank against each other.
ANCHOR_RANK: Final[dict[str, int]] = {"moduleidentity": 0, "objectidentity": 1}

#: Rank given to an OID taken from a module that has no anchor at all, whose
#: OIDs are read off its ordinary definitions instead.
ANCHOR_RANK_FALLBACK: Final[int] = 2

#: Classes whose ``status`` says whether a module still defines anything
#: current.
OBJECT_CLASSES: Final[tuple[str, ...]] = ("objecttype", "notificationtype")


def arcs(oid: str) -> tuple[int, ...]:
    """Sort key placing an OID after every prefix of it, numerically.

    Args:
        oid: dotted-decimal OID

    Returns:
        Its arcs as integers, or an empty tuple for anything that is not one.
    """
    try:
        return tuple(int(arc) for arc in oid.split("."))

    except ValueError:
        return ()


def read_stamp(stamp: str) -> str | None:
    """Read a revision as written in a jsondoc, as a sortable stamp.

    Two spellings reach here. ``JsonCodeGen`` renders a revision as
    ``YYYY-MM-DD HH:MM``, having already made an ExtUTCTime of it; a caller
    ranking modules from some other source may hand over the raw
    ``YYMMDDHHMMZ`` or ``YYYYMMDDHHMMZ`` the MIB carries. Both reduce to
    digits and are then read as a date by
    ``normalise_revision``, which is what refuses the
    ones that are not dates.

    Args:
        stamp: the revision as written

    Returns:
        ``YYYYMMDDHHMMZ``, or ``None`` for anything that does not denote a
        date.
    """
    digits = "".join(x for x in stamp if x.isdigit())

    if len(digits) not in (10, 12):
        return None

    return normalise_revision(digits + "Z")


def newest_revision(document: dict[str, Any]) -> str:
    """The latest MODULE-IDENTITY revision in a jsondoc, as a sortable stamp.

    Every revision goes through :py:func:`read_stamp`, so a stamp that is not
    a date is dropped rather than ranked. ``HPR-MIB``'s ``970514000000Z`` --
    year 9705, month 14 -- is the case that matters: reducing it to digits
    and comparing the number, which is what the index implementation in
    pysnmp/mibs does, makes it sort above every date there will ever be, and
    the module carrying it wins every collision it takes part in, for good.

    LAST-UPDATED counts alongside the REVISION clauses. It is a revision by
    any reading, and a module carrying one without any REVISION clause would
    otherwise rank as though it had never been dated.

    Args:
        document: a module as ``JsonCodeGen`` emits it

    Returns:
        The newest readable revision as ``YYYYMMDDHHMMZ``, or an empty string
        when the module carries none that can be placed.
    """
    newest = ""

    for data in document.values():
        if not isinstance(data, dict) or data.get("class") != "moduleidentity":
            continue

        stamps: list[Any] = []

        revisions = data.get("revisions")

        if isinstance(revisions, list):
            stamps.extend(
                x.get("revision") if isinstance(x, dict) else x for x in revisions
            )

        stamps.append(data.get("lastupdated"))

        for stamp in stamps:
            if not isinstance(stamp, str):
                continue

            normalised = read_stamp(stamp)

            if normalised is None:
                logger.debug(
                    "unreadable revision %s ignored for ranking",
                    stamp,
                    extra={"revision": stamp},
                )
                continue

            newest = max(newest, normalised)

    return newest


def revision_rank(document: dict[str, Any]) -> int:
    """The newest readable revision as a number that sorts newest first.

    Args:
        document: a module as ``JsonCodeGen`` emits it

    Returns:
        The negated stamp, so that a later date sorts lower, and 0 for a
        module carrying no revision that can be placed -- which sorts after
        every module that does.
    """
    newest = newest_revision(document)

    # normalise_revision returns YYYYMMDDHHMM and a "Z", having parsed it as
    # a date, so the leading twelve characters are digits.
    return -int(newest[:12]) if newest else 0


def module_rank(
    module: str,
    document: dict[str, Any],
    *,
    tier: int = 0,
    rfc: int = 0,
) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """How a module ranks for an OID it defines, lower winning.

    Returned in two halves because the anchor term sits between them: how
    strongly a module claims an arc is a property of the OID rather than of
    the module, and :py:func:`oids_of` reports it per OID.

    Args:
        module: module name
        document: the module as ``JsonCodeGen`` emits it

    Keyword Args:
        tier: where the namespace supplying the module ranks; see
            :py:data:`pysmi.corpus.namespace.TIERS`
        rfc: the RFC that publishes it, or 0

    Returns:
        The terms ranking above the anchor, and those ranking below it, with
        the module name last so that the rule is total. Both revision and
        RFC number are negated, so that the later of each sorts first in a
        rule where lower wins throughout.
    """
    statuses = [
        data.get("status")
        for data in document.values()
        if isinstance(data, dict) and data.get("class") in OBJECT_CLASSES
    ]

    obsolete = 1 if statuses and all(x == "obsolete" for x in statuses) else 0

    return (obsolete, tier), (revision_rank(document), -rfc, module)


def oids_of(document: dict[str, Any]) -> list[tuple[str, int]]:
    """Every OID a module claims, with how strongly it claims it.

    A module's anchors -- its MODULE-IDENTITY and any OBJECT-IDENTITY -- are
    what it registers arcs with, so those are what the index carries. A
    module with no anchor at all is read off its ordinary definitions
    instead, at a rank below every anchor, so that a TEXTUAL-CONVENTIONS-only
    module cannot take an arc from the module that registered it.

    Args:
        document: a module as ``JsonCodeGen`` emits it

    Returns:
        ``(oid, anchor rank)`` pairs, in document order.
    """
    anchors = [
        (data["oid"], ANCHOR_RANK[data["class"]])
        for data in document.values()
        if isinstance(data, dict)
        and data.get("class") in ANCHOR_RANK
        and isinstance(data.get("oid"), str)
    ]

    if anchors:
        return anchors

    return [
        (data["oid"], ANCHOR_RANK_FALLBACK)
        for data in document.values()
        if isinstance(data, dict)
        and "class" in data
        and isinstance(data.get("oid"), str)
    ]


def rank_index(
    documents: Iterable[tuple[str, dict[str, Any], int, int]],
) -> dict[str, str]:
    """Resolve every OID the given modules define to the one that owns it.

    Args:
        documents: ``(module, jsondoc, tier, rfc)`` for each module in the
            corpus. Order does not affect the result -- that is the point of
            the rule.

    Returns:
        OID to module name, for every OID any of them defines.
    """
    best: dict[str, tuple[Any, ...]] = {}
    winner: dict[str, str] = {}

    for module, document, tier, rfc in documents:
        prefix, suffix = module_rank(module, document, tier=tier, rfc=rfc)

        for oid, anchor in oids_of(document):
            rank = (*prefix, anchor, *suffix)

            if oid not in best or rank < best[oid]:
                best[oid] = rank
                winner[oid] = module

    return winner


def render_index(index: dict[str, str]) -> str:
    """Render an OID-to-module mapping as the published CSV.

    ``MODULE,OID`` per row, ordered by OID numerically, which is the shape
    splunk-connect-for-snmp parses into its ``mib_map``.

    Args:
        index: OID to module name

    Returns:
        The CSV text, newline-terminated.
    """
    out = io.StringIO()

    for oid in sorted(index, key=arcs):
        out.write(f"{index[oid]},{oid}\n")

    return out.getvalue()


def read_index(text: str) -> Iterator[tuple[str, str]]:
    """Read a published index back, as ``(module, oid)`` pairs.

    Rows that are not two fields are skipped: the file is a published
    artifact that has been edited by hand, and one malformed row should not
    cost the rest of it.

    Args:
        text: the CSV as :py:func:`render_index` writes it

    Yields:
        ``(module, oid)`` for each usable row.
    """
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2 and row[0] and row[1]:
            yield row[0], row[1]


def merge_frozen(
    frozen: Iterable[tuple[str, str]],
    ranked: dict[str, str],
    modules: Iterable[str],
) -> tuple[dict[str, str], int, int]:
    """Replay a frozen index, dropping what is gone and adding what is new.

    The legacy index answers consumers that key on the module name a given
    OID resolves to, so the one thing it must not do is change an answer it
    has already given -- including the answers now known to be wrong, which
    is what makes it a freeze rather than a stale copy. Everything else is
    fair game:

    * a row whose module is no longer compiled is dropped, because it names a
      module the corpus cannot serve;
    * an OID the snapshot never carried is added from the ranked index,
      because a caller that had no answer for it cannot be broken by getting
      one.

    Without the second rule a module added to the corpus would never reach
    the legacy index, and a consumer that has not moved to the ranked one
    would keep resolving nothing for it.

    Args:
        frozen: the snapshot, as :py:func:`read_index` yields it
        ranked: the ranked index, for OIDs the snapshot does not carry
        modules: the modules this build compiled

    Returns:
        The merged index, how many rows were dropped, and how many were
        added.
    """
    compiled = set(modules)
    kept: dict[str, str] = {}
    dropped = 0

    for module, oid in frozen:
        if module not in compiled:
            dropped += 1
            continue

        kept[oid] = module

    added = 0

    for oid, module in ranked.items():
        if oid not in kept:
            kept[oid] = module
            added += 1

    return kept, dropped, added


def read_documents(
    directory: str,
    tiers: dict[str, int],
    rfcs: dict[str, int],
    modules: "Iterable[str] | None" = None,
) -> Iterator[tuple[str, dict[str, Any], int, int]]:
    """Read a directory of jsondoc files as :py:func:`rank_index` takes them.

    Args:
        directory: where ``JsonCodeGen`` output was written
        tiers: module name to tier rank, for modules whose namespace declared
            one. A module not named here ranks as tier 0, which is what a
            corpus of standard modules alone should be.
        rfcs: module name to publishing RFC number
        modules: the modules to read, where the caller knows which ones this
            build produced. Everything in the directory otherwise -- which
            makes an index of a tree left there by an earlier build with a
            different input set, naming modules this corpus does not carry.

    Yields:
        ``(module, jsondoc, tier, rfc)`` per file, in sorted file order.
    """
    wanted = None if modules is None else set(modules)

    for filename in sorted(os.listdir(directory)):
        if not filename.endswith(".json"):
            continue

        module = filename[: -len(".json")]

        if wanted is not None and module not in wanted:
            continue

        with open(os.path.join(directory, filename), encoding="utf-8") as fileObj:
            try:
                document = jsonio.loads(fileObj.read())

            except ValueError as exc:
                # A document that will not parse is skipped rather than
                # failing the index: the rest of the corpus is still
                # indexable, and the build report is where a bad document
                # gets stated.
                logger.warning(
                    "cannot read %s for indexing: %s",
                    filename,
                    exc,
                    extra={"file": filename, "error": str(exc)},
                )
                continue

        if not isinstance(document, dict):
            continue

        yield module, document, tiers.get(module, 0), rfcs.get(module, 0)
