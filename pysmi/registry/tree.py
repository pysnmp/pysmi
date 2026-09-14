#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The top of the registration tree, cited rather than fetched.

:py:mod:`pysmi.registry.smi` names the arcs under ``1.3.6.1`` and
:py:mod:`pysmi.registry.pen` names the enterprise arcs. Between them they
leave about seventeen arcs unnamed in a corpus the size of pysnmp/mibs -- the
top arcs ``0``, ``1``, ``1.0`` and ``1.2``, and the ``1.3.111``,
``1.0.8802`` and ``1.2.840.10006`` chains that IEEE publishes its 802 MIBs
under. ``LLDP-MIB`` registers at ``1.0.8802.1.1.2`` and is among the most
widely polled MIBs there is, so a tree that cannot name the path to it is
missing the part a reader walks.

**There is no feed to render them from.** Probed 2026-09-11: ITU-T's OID
registry at ``oid.itu.int`` does not answer over http or https,
``itu.int/en/ITU-T/oid/`` is a 404, and IEEE's registration authority
publishes HTML landing pages and PDFs. So a small table with a standard
reference per entry is the honest implementation, and pretending it is a data
source would not be.

These are defined in ITU-T X.660 / ISO-IEC 9834-1 and have not changed in
decades, which is what makes a table tolerable here where it would not be for
anything that moves.

**A name from this table is not a registration**, and a consumer must be able
to tell them apart. :py:data:`SOURCE` is what says so, and
:py:mod:`pysmi.corpus.arcs` carries it through to the artifact, so a page can
render a cited standard differently from an IANA registration and differently
again from a name read off whichever MIB mentioned an arc.
"""

from typing import Final, NamedTuple

#: What names an arc here -- a standard, cited. Not a registry, and not
#: something any build fetched.
SOURCE: Final = "standard"

#: The standard that defines the top of the tree, for the arcs that have no
#: more specific citation.
X660: Final = "ITU-T X.660 / ISO-IEC 9834-1"


class CitedArc(NamedTuple):
    """An arc named from a standard rather than from a registry."""

    #: The arc, dotted decimal.
    arc: str

    #: What it is called, as the standard names it.
    name: str

    #: The standard that names it. Rendered, because a cited name and a
    #: registered one are different kinds of fact.
    reference: str


def _table(*entries: CitedArc) -> dict[str, CitedArc]:
    """Key the entries by arc, refusing a duplicate."""
    known: dict[str, CitedArc] = {}

    for entry in entries:
        if entry.arc in known:
            raise ValueError(f"duplicate cited arc: {entry.arc}")

        known[entry.arc] = entry

    return known


#: Every arc pysmi names from a standard. Small on purpose, since an arc a
#: registry names belongs in the registry and this exists only for the ones no
#: registry publishes.
CITED: Final[dict[str, CitedArc]] = _table(
    CitedArc("0", "itu-t", X660),
    CitedArc("0.0", "recommendation", X660),
    CitedArc("1", "iso", X660),
    CitedArc("1.0", "standard", X660),
    CitedArc("1.1", "registration-authority", X660),
    CitedArc("1.2", "member-body", X660),
    CitedArc("1.3", "identified-organization", X660),
    CitedArc("2", "joint-iso-itu-t", X660),
    # The member-body chain ANSI and the ISO 10006 work register under.
    CitedArc("1.2.840", "us", "ISO 3166-1 country code, under ITU-T X.660"),
    CitedArc("1.2.840.10006", "ieee802dot3", "IEEE 802.3"),
    # IEEE's own identified-organization arc, which its 802.1 MIBs sit under.
    CitedArc("1.3.111", "ieee", "IEEE registration authority, under ITU-T X.660"),
    CitedArc("1.3.111.2", "standards-association-numbered-series-standards", "IEEE"),
    CitedArc("1.3.111.2.802", "lan-man-stds", "IEEE 802"),
    CitedArc("1.3.111.2.802.1", "ieee802dot1", "IEEE 802.1"),
    CitedArc("1.3.111.2.802.3", "ieee802dot3", "IEEE 802.3"),
    # The ISO standard arc IEEE 802.1AB registers LLDP-MIB under.
    CitedArc("1.0.8802", "iso8802", "ISO-IEC 8802"),
    CitedArc("1.0.8802.1", "ieee802dot1", "IEEE 802.1"),
    CitedArc("1.0.8802.1.1", "ieee802dot1mibs", "IEEE 802.1"),
    CitedArc("1.0.8802.17", "ieee802dot17", "IEEE 802.17"),
    CitedArc("1.0.8802.17.1", "ieee802dot17mibs", "IEEE 802.17"),
)
