#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""What every arc in a corpus is called, and who says so.

:py:mod:`pysmi.corpus.index` ranks modules to decide which one owns an arc.
The rule is total and works for arcs a module actually registers; for the arcs
*above* those it has nothing good to choose from, so it picks whichever module
happened to mention the arc on its way past. Measured against pysnmp/mibs'
index:

=================  ===========================  ======================
arc                is                           attributed to
=================  ===========================  ======================
``1.3``            ``identified-organization``  ``OCCAM-ETHERLIKE-MIB``
``1.3.6``          ``dod``                      ``OCCAM-ETHERLIKE-MIB``
``1.3.6.1.6``      ``snmpv2``                   ``RAPID-CITY``
``1.3.6.1.6.3``    ``snmpModules``              ``RAPID-CITY``
``1.2``            ISO member-body              ``IEEE802dot11-MIB``
``0.0``            ITU-T recommendation         ``DLSW-MIB``
=================  ===========================  ======================

A tree that says ``snmpModules`` belongs to a Nortel enterprise MIB is wrong in
a way that matters, and no ranking over MIB text can fix it, because the fact
is not in the MIB text. Twenty-five arcs are claimed by nothing at all, and a
tree still has to render a path through them -- ``1.3.6.1.4.1.9`` is one of
them, since no module registers Cisco's bare arc, only what hangs beneath it.

Where a name comes from
-----------------------

Four sources, strongest first, and **every name carries which one named it**,
so a reader can tell an IANA registration from a cited standard from a name
read off whichever MIB mentioned the arc:

:py:data:`REGISTRY`
    IANA -- ``smi-numbers`` for the ``1.3.6.1`` subtree, the Private
    Enterprise Numbers registry for an enterprise arc.

:py:data:`STANDARD`
    A standard, cited. See :py:mod:`pysmi.registry.tree`: there is no feed for
    these arcs, and pretending otherwise would not make one.

:py:data:`MODULE`
    A module's own descriptor for the arc, which is what the index has always
    used. Weakest, and now labelled as what it is.

**An arc nothing names says so** rather than borrowing a name. That is a
better answer than a wrong one, and it is the honest rendering of an arc that
is registered to nobody.

Scope
-----

The arc set comes from the corpus's own index rather than from a prefix
filter. Of pysnmp/mibs' 95,462 index rows, 97.0% sit under ``1.3.6.1.4.1`` and
2.3% under ``1.3.6.1.2.1`` -- but IEEE publishes its 802.1 MIBs under
``1.3.111.2.802.1`` and ``LLDP-MIB`` registers under ``1.0.8802.1.1.2``. A
``1.3.6.1`` filter drops both, and LLDP is among the most widely polled MIBs
there is.

The set is the **registration tree** rather than every OID a module defines:
the index's own arcs and every prefix of them. Over pysnmp/mibs that is about
6,700 arcs instead of 95,000, and the difference is objects -- an object's arc
is a thing inside a module, which the module already renders in context, not a
node anybody navigates to. Every prefix is named too, since a tree renders the
path down to a node and not only the node. Arc depth in that corpus runs from
2 to 20, so nothing here assumes a fixed one.
"""

import json
import logging
from collections.abc import Iterable
from typing import Any, Final, NamedTuple

from pysmi.registry.pen import ENTERPRISES, Registrant, authority_url
from pysmi.registry.smi import ArcName
from pysmi.registry.tree import CITED

logger = logging.getLogger(__name__)

#: The artifact's own version, stamped into what is written.
SCHEMA_VERSION: Final = 1

#: Named by a registry -- IANA's ``smi-numbers``, or the enterprise registry.
REGISTRY: Final = "registry"

#: Named by a standard, cited. No feed publishes these arcs.
STANDARD: Final = "standard"

#: Named by a module's own descriptor, which is what the OID index has always
#: used and the weakest of the three.
MODULE: Final = "module"

_PREFIX: Final = f"{ENTERPRISES}."

#: How many unregistered enterprise numbers the warning names before it stops
#: and gives a count. A build against no registry at all has hundreds of them,
#: and a log line is not the artifact -- ``arcs.json`` carries every one.
_SHOWN: Final = 10


class Arc(NamedTuple):
    """One arc of the registration tree, and what names it."""

    #: The arc, dotted decimal.
    arc: str

    #: What it is called, or ``""`` where nothing names it.
    name: str

    #: :py:data:`REGISTRY`, :py:data:`STANDARD` or :py:data:`MODULE`, or
    #: ``""`` where nothing names it. Rendered, because the three are
    #: different kinds of fact.
    source: str = ""

    #: Where the name comes from -- a URL for a registry, a standard's
    #: designation for a citation, a module name for a descriptor.
    reference: str = ""


def prefixes(oid: str) -> list[str]:
    """Every arc on the path to *oid*, itself included, shortest first.

    A tree renders the path down to a node, not only the node, so an arc's
    ancestors are as much a part of the inventory as the arc is.
    """
    parts = oid.split(".")

    return [".".join(parts[: depth + 1]) for depth in range(len(parts))]


def _descriptors(
    documents: "Iterable[tuple[str, dict[str, Any], Any, Any]]",
) -> dict[str, tuple[str, str]]:
    """The descriptor each module gives each OID it defines.

    Returns:
        ``(name, module)`` per OID. The module with the alphabetically first
        name wins a contested arc, which is arbitrary and deterministic -- a
        descriptor is the weakest source here and two builds must still agree.
    """
    named: dict[str, tuple[str, str]] = {}

    for module, document, *_ in documents:
        for data in document.values():
            if not isinstance(data, dict):
                continue

            oid = data.get("oid")
            name = data.get("name")

            if not isinstance(oid, str) or not isinstance(name, str):
                continue

            if not oid or not name:
                continue

            standing = named.get(oid)

            if standing is None or module < standing[1]:
                named[oid] = (name, module)

    return named


def arcs(
    documents: "Iterable[tuple[str, dict[str, Any], Any, Any]]",
    ranked: dict[str, str] | None = None,
    smi: "dict[str, ArcName] | None" = None,
    enterprises: dict[int, Registrant] | None = None,
) -> dict[str, Arc]:
    """Name every arc the corpus reaches.

    Args:
        documents: ``(module, jsondoc, tier, rfc)`` per module, as
            :py:func:`pysmi.corpus.index.read_documents` yields them. Read for
            the descriptors modules give their own arcs.
        ranked: the OID index, as
            :py:func:`pysmi.corpus.index.rank_index` returns it. The arc set
            comes from here and from every prefix of it, which is the
            registration tree rather than every object a module defines --
            over pysnmp/mibs that is about 6,700 arcs instead of 95,000, and
            an object's own arc is a thing inside a module rather than a node
            of the tree.
        smi: arc name per arc, as
            :py:func:`pysmi.registry.smi.parse_smi_numbers` returns. Omitted
            leaves the ``1.3.6.1`` subtree to the weaker sources.
        enterprises: the registration per enterprise number, as
            :py:func:`pysmi.registry.pen.load_registry` returns. Names the
            bare enterprise arcs, which no module registers.

    Returns:
        One :py:class:`Arc` per arc, in tree order, each carrying what named
        it. An arc nothing names is present with an empty name rather than
        absent: the tree still renders a path through it.
    """
    descriptors = _descriptors(documents)
    registry = smi or {}
    holders = enterprises or {}

    reached: set[str] = set()

    for oid in ranked or {}:
        reached.update(prefixes(oid))

    found: dict[str, Arc] = {}

    for arc in sorted(reached, key=lambda x: tuple(int(y) for y in x.split("."))):
        named = registry.get(arc)

        if named is not None:
            found[arc] = Arc(arc, named.name, REGISTRY, named.authority)
            continue

        number = _enterprise(arc)

        if number is not None and number in holders:
            holder = holders[number]

            if holder.organization:
                found[arc] = Arc(
                    arc, holder.organization, REGISTRY, authority_url(number)
                )
                continue

        cited = CITED.get(arc)

        if cited is not None:
            found[arc] = Arc(arc, cited.name, STANDARD, cited.reference)
            continue

        descriptor = descriptors.get(arc)

        if descriptor is not None:
            found[arc] = Arc(arc, descriptor[0], MODULE, descriptor[1])
            continue

        found[arc] = Arc(arc, "")

    return found


def _enterprise(arc: str) -> int | None:
    """The enterprise number *arc* is, where it is a bare enterprise arc."""
    if not arc.startswith(_PREFIX):
        return None

    rest = arc[len(_PREFIX) :]

    return int(rest) if rest.isdigit() else None


def unregistered(found: dict[str, Arc]) -> tuple[int, ...]:
    """The enterprise numbers no registrant in the PEN registry named.

    A corpus that commits a *reduced* PEN snapshot -- the registrants its own
    arcs use, rather than all 66,807 -- names every enterprise arc it has
    until it gains a module under an arc the snapshot predates. Then one
    registrant page goes nameless, and nothing about the build says so: the
    arc is still in the index, still reachable, still rendered, just blank.

    This is the build saying so. It is not a failure -- an arc can be
    registered to nobody, and IANA's registry has gaps of its own -- it is a
    prompt to refresh the snapshot.

    Args:
        found: the arcs, as :py:func:`arcs` returns them.

    Returns:
        The enterprise numbers, ascending, whose arc the registry did not
        name. An arc a module named is still counted: the module's own
        descriptor says what the vendor calls its subtree, not who registered
        it, and it is the registrant a refresh would supply.
    """
    missing = []

    for arc in found.values():
        number = _enterprise(arc.arc)

        if number is not None and arc.source != REGISTRY:
            missing.append(number)

    return tuple(sorted(missing))


def as_document(found: dict[str, Arc]) -> dict[str, Any]:
    """The artifact, as plain data."""
    counted: dict[str, int] = {}

    for arc in found.values():
        counted[arc.source or "unnamed"] = counted.get(arc.source or "unnamed", 0) + 1

    return {
        "meta": {
            "schema": SCHEMA_VERSION,
            "arcs": len(found),
            "by-source": dict(sorted(counted.items())),
        },
        "arc": {
            arc.arc: {
                "name": arc.name,
                "source": arc.source,
                "reference": arc.reference,
            }
            for arc in found.values()
        },
    }


def render_arcs(found: dict[str, Arc]) -> str:
    """The artifact as it is written, ending in a newline."""
    return json.dumps(as_document(found), separators=(",", ":")) + "\n"


def counts(found: dict[str, Arc]) -> dict[str, int]:
    """How many arcs there are and where their names came from.

    The unnamed count is the one to look at. It should fall as registries are
    supplied, and an arc nothing names is a gap in the inventory rather than a
    failure -- a corpus can perfectly well reach an arc registered to nobody.
    """
    counted = as_document(found)["meta"]["by-source"]
    missing = unregistered(found)
    tally = {"arcs": len(found), **counted, "unregistered-enterprises": len(missing)}

    logger.info(
        "arc names: %d arcs, %s",
        len(found),
        ", ".join(f"{v} from {k}" for k, v in sorted(counted.items())),
        extra={"arcs": len(found), "sources": counted},
    )

    if missing:
        shown = ", ".join(str(x) for x in missing[:_SHOWN])
        more = f" and {len(missing) - _SHOWN} more" if len(missing) > _SHOWN else ""

        logger.warning(
            "%d enterprise arc(s) no PEN registrant names: %s%s",
            len(missing),
            shown,
            more,
            extra={"unregistered": list(missing)},
        )

    return tally
