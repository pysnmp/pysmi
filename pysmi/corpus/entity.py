#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Which enterprise arcs a corpus registers under, and who holds each.

A corpus knows that ``CISCO-ENTITY-ALARM-MIB`` registers under
``1.3.6.1.4.1.9``. It does not know that ``1.3.6.1.4.1.9`` is Cisco. The
directory a module's file sits in is a filing convention and disagrees with the
registrations in practice -- pysnmp/mibs has an ``aironet`` directory holding
Cisco modules, and ``src/vendor/cisco/ALTIGA-*`` registering under Altiga's arc
-- so navigation built on the tree would publish a convention as though it were
a fact.

The registration is a fact, and it is published.
:py:mod:`pysmi.registry.pen` reads it; this projects the corpus onto it.
Measured over pysnmp/mibs: 351 distinct enterprise arcs, 350 of them named by
the registry, against 290 vendor directories. Those two numbers are the whole
argument for driving navigation from the registry rather than from the tree.

**An arc the registry does not name is reported as unregistered, never
guessed at.** pysnmp/mibs has exactly one -- ``1.3.6.1.4.1.1004849``, above
anything IANA has allocated -- and the honest rendering of it is that nobody
registered it.

This groups by **arc**, not by company. The registry maps arcs to registrants
and a company can hold several: pysnmp/mibs carries Cisco modules under
``1.3.6.1.4.1.9`` and, from the Altiga acquisition, under ``1.3.6.1.4.1.3076``,
which IANA still lists as "Altiga Networks, Inc.". Nothing in the registry
models an acquisition and pysmi does not infer one. A consumer that wants to
say two arcs are one company is saying it on its own account.

Owner contact
-------------

A registrant page is an accountability aid as well as navigation: who is
responsible for this arc, and how is it reported to. Two sources reach an
enterprise arc, and each arc carries both in precedence order with its source
named, so a reader can weigh a vendor's current support address against an
undated registration:

1. **The module's own ``CONTACT-INFO``.** What modules hold in practice is a
   corporate block -- company, department, postal address, phone, and a role
   mailbox such as ``cs-snmp@cisco.com``. It is the publisher's own statement
   of where to report a problem, and it is generally far fresher than the
   registration. It ranks first for that reason. It reaches a corpus only when
   the build carries texts, since ``JsonCodeGen`` gates ``organization`` and
   ``contactinfo`` behind the same switch as ``description`` -- see
   pysnmp/pysmi#277.

2. **The IANA PEN record.** Registrant, contact name, contact email. Second
   because it is undated and often stale: the registry records who registered
   an arc at the time they registered it, and arc 4 is still held against a
   ``berkeley.edu`` address from the era it was assigned. It carries the
   authority link, because a correction to a registration belongs at IANA.

A third source, the publishing RFC, applies to modules under the standard arcs
rather than under ``1.3.6.1.4.1``, so nothing here has one.

**Remediation is precedence, not a suppression list.** A registrant who does
not want an undated personal registration standing as the contact for their arc
publishes a module carrying current ``ORGANIZATION`` and ``CONTACT-INFO``, and
source 1 displaces source 2 on the next build. That needs no per-record
exclusion mechanism, and it improves the corpus.

Each source is rendered as that source publishes it, unnormalised. See
:py:mod:`pysmi.registry.pen`.
"""

import json
import logging
from collections.abc import Iterable
from typing import Any, Final, NamedTuple

from pysmi.corpus.index import oids_of
from pysmi.registry.pen import ENTERPRISES, Registrant

logger = logging.getLogger(__name__)

#: The artifact's own version, stamped into what is written.
SCHEMA_VERSION: Final = 1

#: How many arcs of ``1.3.6.1.4.1`` have to match before the next one is the
#: enterprise number.
_DEPTH: Final = len(ENTERPRISES.split("."))

_PREFIX: Final = f"{ENTERPRISES}."


#: A contact read from a module's own MODULE-IDENTITY.
MODULE: Final = "module"

#: A contact read from the IANA registration.
REGISTRY: Final = "registry"


class Contact(NamedTuple):
    """Who to report a problem with an arc to, and who says so.

    Every field is as its source publishes it. An email from the registry is
    ``davej&cisco.com`` because that is what the registry says.
    """

    #: :py:data:`MODULE` or :py:data:`REGISTRY`. Rendered, so a reader can
    #: tell a vendor's current support address from an undated registration.
    source: str

    #: The organization the source names.
    organization: str

    #: The contact as the source gives it -- a module's whole ``CONTACT-INFO``
    #: block, or the registry's contact name.
    contact: str

    #: The registry's contact email. Empty for a module, whose email is inside
    #: its ``CONTACT-INFO`` block and is left there -- rendering the block as
    #: published is the point, and picking an address out of it would be this
    #: module deciding which of several is the right one.
    email: str = ""

    #: The module this was read from. Empty for the registry.
    module: str = ""

    #: Where the source publishes it, and where a correction goes. Empty for a
    #: module: the correction is a new revision of the MIB.
    authority: str = ""


class Entity(NamedTuple):
    """One enterprise arc, and what the corpus holds under it."""

    #: The enterprise number, the arc under ``1.3.6.1.4.1``.
    number: int

    #: The organization the registry names, or ``""`` where it names none --
    #: an arc above anything allocated, or one the build was given no registry
    #: for. Either way a consumer renders it as unregistered rather than
    #: inventing a name.
    organization: str

    #: The modules the corpus holds under the arc, sorted. A module
    #: registering under more than one arc appears under each.
    modules: tuple[str, ...]

    #: Who to report a problem to, best source first. Empty where neither a
    #: registration nor a module under the arc says anything.
    contacts: tuple[Contact, ...] = ()

    @property
    def arc(self) -> str:
        """The OID this registration names, in full."""
        return f"{_PREFIX}{self.number}"


def enterprise_of(oid: str) -> int | None:
    """The enterprise number an OID registers under, if it registers under one.

    Args:
        oid: dotted decimal.

    Returns:
        The arc under ``1.3.6.1.4.1``, or ``None`` for an OID outside it --
        a standard or IETF registration, which has no registrant to name.
    """
    if not oid.startswith(_PREFIX):
        return None

    arc = oid[len(_PREFIX) :].split(".", 1)[0]

    return int(arc) if arc.isdigit() else None


def module_contact(module: str, document: "dict[str, Any]") -> Contact | None:
    """The contact one module's MODULE-IDENTITY states, if it states one.

    Args:
        module: the module's name.
        document: its jsondoc.

    Returns:
        The contact, or ``None`` where the document carries none -- which is
        every document in a corpus built without texts, since ``JsonCodeGen``
        gates ``organization`` and ``contactinfo`` behind the same switch as
        ``description``.
    """
    for data in document.values():
        if not isinstance(data, dict) or data.get("class") != "moduleidentity":
            continue

        organization = data.get("organization") or ""
        contactinfo = data.get("contactinfo") or ""

        if organization or contactinfo:
            return Contact(
                MODULE,
                organization,
                contactinfo,
                module=module,
            )

    return None


def _lastupdated(document: "dict[str, Any]") -> str:
    """A module's LAST-UPDATED, for choosing between two of them."""
    for data in document.values():
        if isinstance(data, dict) and data.get("class") == "moduleidentity":
            return str(data.get("lastupdated") or "")

    return ""


def _registry_contact(registrant: Registrant) -> Contact | None:
    """The registration's contact, if it carries one."""
    if not (registrant.organization or registrant.contact or registrant.email):
        return None

    return Contact(
        REGISTRY,
        registrant.organization,
        registrant.contact,
        registrant.email,
        authority=registrant.authority,
    )


def entities(
    documents: "Iterable[tuple[str, dict[str, Any], Any, Any]]",
    registry: dict[int, Registrant] | None = None,
) -> dict[int, Entity]:
    """Which enterprise arcs the corpus registers under, and who holds each.

    Args:
        documents: ``(module, jsondoc, tier, rfc)`` per module, as
            :py:func:`pysmi.corpus.index.read_documents` yields them.
        registry: the registration per enterprise number, as
            :py:func:`pysmi.registry.pen.load_registry` returns. Omitted leaves
            every arc unnamed, which is still the arc index -- the corpus knows
            what it registers under whether or not anybody told it whose that
            is.

    Returns:
        One :py:class:`Entity` per arc, keyed by enterprise number, each
        carrying its contacts best source first.
    """
    known = registry or {}
    found: dict[int, set[str]] = {}

    # The freshest module contact per arc, as (sort key, contact). Which
    # module speaks for an arc has to be decided rather than left to iteration
    # order, and the newest LAST-UPDATED is the defensible answer: a support
    # address from 2019 is worth more than one from 1996. The module name
    # breaks the tie so that two builds agree.
    speaking: dict[int, tuple[tuple[str, str], Contact]] = {}

    for module, document, *_ in documents:
        # The anchors, which is what a module registers arcs with -- the same
        # reading the OID index takes, so the two cannot disagree about what a
        # module claims.
        arcs = {
            number
            for oid, _rank in oids_of(document)
            if (number := enterprise_of(oid)) is not None
        }

        if not arcs:
            continue

        contact = module_contact(module, document)
        # Descending on the date, ascending on the name, by negating neither
        # and comparing the other way round below.
        rank = (_lastupdated(document), module)

        for number in arcs:
            found.setdefault(number, set()).add(module)

            if contact is None:
                continue

            standing = speaking.get(number)

            if standing is None or rank > standing[0]:
                speaking[number] = (rank, contact)

    entries = {}

    for number, modules in sorted(found.items()):
        registrant = known.get(number)
        contacts = [x[1] for x in (speaking.get(number),) if x is not None]

        if registrant is not None:
            fromRegistry = _registry_contact(registrant)

            if fromRegistry is not None:
                contacts.append(fromRegistry)

        entries[number] = Entity(
            number,
            registrant.organization if registrant is not None else "",
            tuple(sorted(modules)),
            tuple(contacts),
        )

    return entries


def as_document(found: dict[int, Entity]) -> dict[str, Any]:
    """The artifact, as plain data.

    Args:
        found: the entities, as :py:func:`entities` returns them.

    Returns:
        A ``meta`` block and an ``entity`` map keyed by the full arc, so a
        consumer holding an OID can look it up without rebuilding the prefix.
    """
    named = sum(1 for x in found.values() if x.organization)

    return {
        "meta": {
            "schema": SCHEMA_VERSION,
            "arcs": len(found),
            "named": named,
            "unregistered": len(found) - named,
        },
        "entity": {
            entity.arc: {
                "number": entity.number,
                "organization": entity.organization,
                "modules": list(entity.modules),
                "contacts": [x._asdict() for x in entity.contacts],
            }
            for entity in found.values()
        },
    }


def render_entities(found: dict[int, Entity]) -> str:
    """The artifact as it is written, ending in a newline.

    Compact: a generated artifact that nobody reads by eye. See
    pysnmp/pysmi#283.
    """
    return json.dumps(as_document(found), separators=(",", ":")) + "\n"


def counts(found: dict[int, Entity]) -> dict[str, int]:
    """How many arcs there are and how many the registry named, for the report.

    The unregistered count is the one to look at. Over pysnmp/mibs it should be
    one; a build where it jumps has either lost its registry or grown a module
    registering somewhere nobody allocated.
    """
    named = sum(1 for x in found.values() if x.organization)
    unregistered = len(found) - named

    logger.info(
        "enterprise arcs: %d, %d named by the registry, %d unregistered",
        len(found),
        named,
        unregistered,
        extra={"arcs": len(found), "named": named, "unregistered": unregistered},
    )

    return {"arcs": len(found), "named": named, "unregistered": unregistered}
