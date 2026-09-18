#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""What each page of the site states, read off the corpus the build produced.

Separate from the rendering so that what a page *says* can be tested without
parsing HTML, and so that a distribution replacing the templates is replacing
presentation rather than deciding which facts survive.

Every page is a projection of artifacts the build already has -- the jsondoc
tree, the import closure, the entity index, the arc names, the provenance
table. Nothing here re-reads a MIB or recompiles anything.

See pysnmp/pysmi#276.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, NamedTuple

from pysmi.corpus.arcs import Arc, prefixes
from pysmi.corpus.namespace import DEFAULT_TIER, TIERS

#: jsondoc classes that are a module's own definitions rather than its
#: structure, in the order a page renders them.
DEFINED: Final[tuple[str, ...]] = (
    "objectidentity",
    "objecttype",
    "notificationtype",
)

#: jsondoc classes carrying a module's conformance statements.
CONFORMANCE: Final[tuple[str, ...]] = (
    "objectgroup",
    "notificationgroup",
    "modulecompliance",
    "agentcapabilities",
)

#: jsondoc classes for a type a module defines. ``textualconvention`` is what
#: a TEXTUAL-CONVENTION comes out as; ``type`` is a plain type assignment,
#: which is rarer and belongs in the same table.
TYPES: Final[tuple[str, ...]] = ("textualconvention", "type")

#: How many recently revised modules the front page lists per tier.
#:
#: The list answers "what moved lately", which a handful of rows answers and a
#: longer one does not: past the first few the reader is reading an arbitrary
#: slice of a corpus whose modules were nearly all revised on some date or
#: other. The whole corpus stays one hop away through the range keys.
RECENT: Final[int] = 10

#: What a jsondoc class is called on a page.
KIND: Final[dict[str, str]] = {
    "moduleidentity": "MODULE-IDENTITY",
    "objectidentity": "OBJECT-IDENTITY",
    "objecttype": "OBJECT-TYPE",
    "notificationtype": "NOTIFICATION-TYPE",
    "objectgroup": "OBJECT-GROUP",
    "notificationgroup": "NOTIFICATION-GROUP",
    "modulecompliance": "MODULE-COMPLIANCE",
    "agentcapabilities": "AGENT-CAPABILITIES",
    "textualconvention": "TEXTUAL-CONVENTION",
    "type": "type",
}


class Definition(NamedTuple):
    """One thing a module defines, as its row on the module page."""

    #: The descriptor, which is also the page anchor.
    name: str

    #: Its OID, or ``""`` for a type, which has none.
    oid: str

    #: What it is, from :py:data:`~pysmi.corpus.site.model.KIND`.
    kind: str

    #: The SYNTAX, rendered flat -- ``Integer32 (0..255)``, ``INTEGER
    #: {up(1), down(2)}``. ``""`` where the definition has none.
    syntax: str

    #: MAX-ACCESS, or ``""``.
    access: str

    #: STATUS, or ``""``.
    status: str

    #: DESCRIPTION, or ``""`` where the build carried no texts.
    description: str


class ModulePage(NamedTuple):
    """One module: everything the corpus holds about it."""

    module: str
    #: The arcs this module registers at, ascending. Empty for a module that
    #: registers nothing, such as a TEXTUAL-CONVENTIONS-only module.
    anchors: tuple[str, ...]
    organization: str
    contact: str
    lastupdated: str
    revisions: tuple[str, ...]
    description: str
    #: Namespace, file and digest, as the provenance table records them.
    provenance: Mapping[str, str]
    #: Module name to the symbols imported from it.
    imports: Mapping[str, tuple[str, ...]]
    #: The modules in this corpus that import this one.
    importedBy: tuple[str, ...]
    #: The files a consumer needs in order to load this module.
    closure: tuple[str, ...]
    #: What the closure needs and the corpus does not hold.
    missing: tuple[str, ...]
    #: The arcs directly below this module's own registrations, which is how
    #: the tree carries on past it. A module's anchor gets no arc page of its
    #: own -- that arc *is* the module -- so without this the structural arcs
    #: under it are reachable from nothing. See pysnmp/pysmi#284 on orphans.
    under: tuple[Arc, ...]

    #: The defects a patch on this module repairs, as ``(id, url)``.
    defects: tuple[tuple[str, str], ...]
    #: The patch itself, as a unified diff, or ``""``.
    patch: str
    types: tuple[Definition, ...]
    objects: tuple[Definition, ...]
    notifications: tuple[Definition, ...]
    conformance: tuple[Definition, ...]


class EntityPage(NamedTuple):
    """One registrant, and what the corpus holds under its arc."""

    number: int
    arc: str
    organization: str
    #: ``(source, organization, contact, email, module, authority)`` rows.
    contacts: tuple[Mapping[str, str], ...]
    modules: tuple[str, ...]


class ArcPage(NamedTuple):
    """One node of the registration tree."""

    arc: str
    name: str
    source: str
    reference: str
    #: Child arcs, ascending, each with the name the arc index gives it.
    children: tuple[Arc, ...]
    #: The module registered at this arc, where one is. A page is written only
    #: for arcs where none is -- an arc that *is* a module resolves to the
    #: module page instead -- so this is what the parent's child rows read.
    module: str = ""


class Recent(NamedTuple):
    """One module's row in a recently revised list."""

    module: str

    #: The newest date the module itself carries -- its LAST-UPDATED or the
    #: latest REVISION -- as ``YYYY-MM-DD``.
    revised: str

    #: The ORGANIZATION the MODULE-IDENTITY names, or ``""``.
    organization: str

    #: How many OBJECT-TYPEs and NOTIFICATION-TYPEs it defines, so a row says
    #: how much moved rather than only that something did.
    definitions: int

    #: The date the publishing distribution last changed it, as
    #: :py:mod:`pysmi.corpus.site.dates` supplied it, or ``""`` where none
    #: was supplied for this module. Independent of :py:attr:`revised`: a
    #: module taken today carries whatever revision its publisher last set.
    changed: str = ""


class Overview(NamedTuple):
    """What the corpus holds, as the entry point states it.

    Every figure is something the build computed while writing the pages. A
    front page that asked a question the build had not already answered would
    be a second pass over the corpus for the sake of a headline.
    """

    #: Modules published, which is the figure the page leads with.
    modules: int

    #: Modules per tier, in :py:data:`pysmi.corpus.namespace.TIERS` order and
    #: holding only the tiers this corpus has modules in.
    tiers: Mapping[str, int]

    #: Enterprise arcs the corpus registers under, or 0 for a build that
    #: wrote no registrant pages.
    registrants: int

    #: Nodes in the arc index, or 0 for a build given no arc names.
    arcs: int

    #: OBJECT-TYPEs and OBJECT-IDENTITYs across the corpus.
    objects: int

    #: NOTIFICATION-TYPEs across the corpus.
    notifications: int

    #: TEXTUAL-CONVENTIONs and type assignments across the corpus.
    types: int

    #: Modules served with a patch applied to the publisher's text.
    repaired: int

    #: Modules whose import closure names something the corpus does not hold.
    incomplete: int

    #: The newest date any module in the corpus carries, as ``YYYY-MM-DD``.
    revised: str

    #: Per tier, the most recently revised modules, newest first. Same keys
    #: and same order as :py:attr:`tiers`, a tier none of whose modules
    #: carries a readable date aside.
    latest: Mapping[str, tuple[Recent, ...]]

    #: Per tier, the modules the distribution changed most recently, newest
    #: first. Empty for a build given no dates, and a tier whose modules were
    #: all supplied without one is left out -- which is what makes this list
    #: honest on a corpus whose standard tier comes from somewhere the
    #: distribution does not track.
    latestChanged: Mapping[str, tuple[Recent, ...]] = {}

    #: Per tier, how many modules the distribution supplied a date for, which
    #: is the pool :py:attr:`latestChanged` is the newest few of. Not
    #: :py:attr:`tiers`: a distribution may date a fraction of a tier, and
    #: "the ten most recent of the 6,982 it tracks" and "of the 6,982 this
    #: corpus holds" are different claims.
    datedChanged: Mapping[str, int] = {}


def tier_name(rank: int) -> str:
    """What a tier rank is called, as a namespace declares it.

    ``read_documents`` yields the rank rather than the name, since ranking is
    what the index wants it for. A page states the name.
    """
    return TIERS[rank] if 0 <= rank < len(TIERS) else DEFAULT_TIER


class Tally:
    """Running counts over the module pages a build renders.

    Accumulated as the pages are written rather than in a pass of its own: the
    figures are sums over the models the build already built, and reading the
    jsondoc tree again to total them is a second parse of the whole corpus for
    numbers that were on hand.
    """

    def __init__(self) -> None:
        """A tally holding nothing, which is a corpus of no modules."""
        self.modules = 0
        self.objects = 0
        self.notifications = 0
        self.types = 0
        self.repaired = 0
        self.incomplete = 0
        self.tiers: dict[str, int] = {}
        #: Per tier, one row per module carrying a date of either kind. A
        #: module with a publisher revision and no distribution date, or the
        #: other way about, is in here once and reaches only the list it has
        #: a date for.
        self.dated: dict[str, list[Recent]] = {}

    def add(
        self,
        page: ModulePage,
        *,
        tier: str = DEFAULT_TIER,
        revised: str = "",
        changed: str = "",
    ) -> None:
        """One module's page, counted.

        Args:
            page: the model, as
                :py:func:`~pysmi.corpus.site.model.module_page` built it.
            tier: the tier its namespace declared, from
                :py:func:`~pysmi.corpus.site.model.tier_name`.
            revised: the newest date the module carries, as
                :py:func:`pysmi.corpus.site.crawl.newest` read it. A module
                carrying none is counted and is not listed as a recent
                revision, since there is no date to place it by.
            changed: the date the publishing distribution last changed it, as
                :py:mod:`pysmi.corpus.site.dates` supplied it. Same rule: a
                module supplied without one is counted and is not listed
                under a date it does not have.
        """
        self.modules += 1
        self.tiers[tier] = self.tiers.get(tier, 0) + 1
        self.objects += len(page.objects)
        self.notifications += len(page.notifications)
        self.types += len(page.types)

        if page.defects or page.patch:
            self.repaired += 1

        if page.missing:
            self.incomplete += 1

        if revised or changed:
            self.dated.setdefault(tier, []).append(
                Recent(
                    module=page.module,
                    revised=revised,
                    organization=page.organization,
                    definitions=len(page.objects) + len(page.notifications),
                    changed=changed,
                )
            )

    def overview(
        self, *, registrants: int = 0, arcs: int = 0, recent: int = RECENT
    ) -> Overview:
        """The figures as the entry point states them.

        Args:
            registrants: enterprise arcs the corpus registers under.
            arcs: nodes in the arc index.
            recent: how many modules each tier's recent list holds.

        Returns:
            The overview. Tiers come out in
            :py:data:`pysmi.corpus.namespace.TIERS` order rather than in the
            order the modules happened to be read, so two builds of one
            corpus state it the same way.
        """
        ordered = [x for x in TIERS if self.tiers.get(x)]
        ordered += [x for x in sorted(self.tiers) if x not in TIERS]
        rows = [y for x in self.dated.values() for y in x]
        published = self._newest(ordered, "revised", recent)
        supplied = self._newest(ordered, "changed", recent)

        return Overview(
            modules=self.modules,
            tiers={x: self.tiers[x] for x in ordered},
            registrants=registrants,
            arcs=arcs,
            objects=self.objects,
            notifications=self.notifications,
            types=self.types,
            repaired=self.repaired,
            incomplete=self.incomplete,
            revised=max((x.revised for x in rows), default=""),
            latest={x: y for x, (y, _) in published},
            latestChanged={x: y for x, (y, _) in supplied},
            datedChanged={x: y for x, (_, y) in supplied},
        )

    def _newest(
        self, ordered: "Sequence[str]", dated: str, recent: int
    ) -> "list[tuple[str, tuple[tuple[Recent, ...], int]]]":
        """Per tier, the *recent* newest rows on one axis, and the pool's size.

        A row with no date of this kind is left out rather than sorted to the
        end: a list of the ten most recent is ten modules that have a date,
        not ten rows of which some are blank. The count is how many rows the
        tier had before the list was cut to *recent*, so a note can say what
        the few were the newest of.
        """
        found = []

        for tier in ordered:
            rows = [x for x in self.dated.get(tier, ()) if getattr(x, dated)]

            if rows:
                found.append(
                    (
                        tier,
                        (
                            tuple(
                                sorted(
                                    rows,
                                    key=lambda y: (
                                        _descending(getattr(y, dated)),
                                        y.module,
                                    ),
                                )[:recent]
                            ),
                            len(rows),
                        ),
                    )
                )

        return found


def _descending(date: str) -> tuple[int, ...]:
    """A ``YYYY-MM-DD`` as a sort key placing the latest date first."""
    return tuple(-int(x) for x in date.split("-") if x.isdigit())


def _flatten(syntax: Any) -> str:
    """A SYNTAX as one line, the way a MIB writes it.

    jsondoc renders a type as a nested object and a table cell wants a string:
    ``Integer32 (1..5)``, ``OCTET STRING (SIZE(0..255))``,
    ``INTEGER {up(1), down(2), testing(3)}``.

    Named values come out in value order rather than in whatever order the
    document happens to list them, so two builds of one module agree and a
    reader can find a number.
    """
    if not isinstance(syntax, dict):
        return ""

    written = str(syntax.get("type") or "")
    constraints = syntax.get("constraints")

    if isinstance(constraints, dict):
        named = constraints.get("enumeration")

        if isinstance(named, dict) and named:
            return f"{written} {{{_named(named)}}}".strip()

        spelled = _bounds(constraints.get("range"))

        if spelled:
            written += f" ({spelled})"

        spelled = _bounds(constraints.get("size"))

        if spelled:
            written += f" (SIZE({spelled}))"

    bits = syntax.get("bits")

    if isinstance(bits, dict) and bits:
        written += f" {{{_named(bits)}}}"

    return written.strip()


def _named(values: Mapping[str, Any]) -> str:
    """Named numbers as ``up(1), down(2)``, in value order."""
    return ", ".join(
        f"{label}({number})"
        for label, number in sorted(values.items(), key=lambda x: (x[1], x[0]))
    )


def _bounds(ranges: Any) -> str:
    """Range or size constraints as ``0..255``, or ``0 | 4..8`` for several."""
    if isinstance(ranges, dict):
        ranges = [ranges]

    if not isinstance(ranges, list):
        return ""

    written = []

    for bound in ranges:
        if not isinstance(bound, dict):
            continue

        low, high = bound.get("min"), bound.get("max")

        if low is None and high is None:
            continue

        written.append(f"{low}" if low == high else f"{low}..{high}")

    return " | ".join(written)


def _definition(name: str, data: Mapping[str, Any]) -> Definition:
    """One jsondoc entry as a page row."""
    return Definition(
        name=name,
        oid=str(data.get("oid") or ""),
        kind=KIND.get(str(data.get("class")), str(data.get("class") or "")),
        syntax=_flatten(data.get("syntax")),
        access=str(data.get("maxaccess") or ""),
        status=str(data.get("status") or ""),
        description=str(data.get("description") or ""),
    )


def _sorted(found: Iterable[Definition]) -> tuple[Definition, ...]:
    """Definitions in OID order, then by name for the ones with no OID."""
    return tuple(
        sorted(
            found,
            key=lambda x: (
                tuple(int(y) for y in x.oid.split(".")) if x.oid else (),
                x.name,
            ),
        )
    )


def module_page(
    module: str,
    document: Mapping[str, Any],
    *,
    anchors: "Iterable[str] | None" = None,
    provenance: "Mapping[str, str] | None" = None,
    importedBy: "Iterable[str] | None" = None,
    closure: "Iterable[str] | None" = None,
    missing: "Iterable[str] | None" = None,
    defects: "Iterable[tuple[str, str]] | None" = None,
    patch: str = "",
    under: "Iterable[Arc] | None" = None,
) -> ModulePage:
    """Everything the corpus holds about one module, as its page states it.

    Args:
        module: the module name.
        document: its jsondoc, as ``JsonCodeGen`` emits it. Read for
            everything the module itself says; a build that carried texts
            gives a page with prose on it and one that did not gives the same
            page without.
        anchors: the arcs this module registers at, as
            :py:func:`~pysmi.corpus.index.anchor_index` picks them out.
        provenance: its row of the provenance table.
        importedBy: the modules in this corpus that import it.
        closure: the files needed to load it, and *missing* what is not held.
        defects: what a patch on it repairs, as ``(identifier, url)``.
        patch: the patch itself, as a unified diff.
        under: the arcs directly below its registrations, so the tree does
            not stop at a module page.

    Returns:
        The page model.
    """
    identity: Mapping[str, Any] = {}
    types: list[Definition] = []
    objects: list[Definition] = []
    notifications: list[Definition] = []
    conforms: list[Definition] = []
    imports: dict[str, tuple[str, ...]] = {}

    for name, data in document.items():
        if not isinstance(data, dict):
            continue

        kind = data.get("class")

        if kind == "imports":
            imports = {
                str(x): tuple(y)
                for x, y in sorted(data.items())
                if x != "class" and isinstance(y, list)
            }

        elif kind == "moduleidentity":
            identity = data

        elif kind in TYPES:
            types.append(_definition(name, data))

        elif kind == "notificationtype":
            notifications.append(_definition(name, data))

        elif kind in CONFORMANCE:
            conforms.append(_definition(name, data))

        elif kind in DEFINED:
            objects.append(_definition(name, data))

    revisions = tuple(
        str(x.get("revision"))
        for x in identity.get("revisions") or []
        if isinstance(x, dict) and x.get("revision")
    )

    return ModulePage(
        module=module,
        anchors=tuple(anchors or ()),
        organization=str(identity.get("organization") or ""),
        contact=str(identity.get("contactinfo") or ""),
        lastupdated=str(identity.get("lastupdated") or ""),
        revisions=revisions,
        description=str(identity.get("description") or ""),
        provenance=dict(provenance or {}),
        imports=imports,
        importedBy=tuple(sorted(importedBy or ())),
        closure=tuple(closure or ()),
        missing=tuple(missing or ()),
        under=tuple(under or ()),
        defects=tuple(defects or ()),
        patch=patch,
        types=_sorted(types),
        objects=_sorted(objects),
        notifications=_sorted(notifications),
        conformance=_sorted(conforms),
    )


def imported_by(
    documents: "Iterable[tuple[str, Mapping[str, Any]]]",
) -> dict[str, tuple[str, ...]]:
    """Which modules import each module, from the import clauses themselves.

    The reverse of what every jsondoc already states, which nothing else in a
    corpus build computes -- the closure runs the other way. A page saying
    "nothing in this corpus imports this" is a fact about the corpus and is
    worth stating.
    """
    found: dict[str, set[str]] = {}

    for module, document in documents:
        data = document.get("imports")

        if not isinstance(data, dict):
            continue

        for other in data:
            if other != "class":
                found.setdefault(str(other), set()).add(module)

    return {module: tuple(sorted(x)) for module, x in found.items()}


def entity_page(arc: str, record: Mapping[str, Any]) -> EntityPage:
    """One registrant, from its row of the entity index."""
    contacts = [x for x in record.get("contacts") or [] if isinstance(x, dict)]

    return EntityPage(
        number=int(record.get("number") or 0),
        arc=arc,
        organization=str(record.get("organization") or ""),
        contacts=tuple(contacts),
        modules=tuple(sorted(str(x) for x in record.get("modules") or [])),
    )


def children_of(found: Mapping[str, Arc]) -> dict[str, tuple[Arc, ...]]:
    """The arcs directly below each arc, in tree order.

    One pass over the arc index, since both the OID tree's pages and the
    module pages need it and walking every arc twice to build the same map is
    the kind of cost that only shows at corpus scale.
    """
    children: dict[str, list[Arc]] = {}

    for arc in found.values():
        path = prefixes(arc.arc)

        if len(path) > 1:
            children.setdefault(path[-2], []).append(arc)

    return {
        parent: tuple(
            sorted(kids, key=lambda x: tuple(int(y) for y in x.arc.split(".")))
        )
        for parent, kids in children.items()
    }


def arc_pages(
    found: Mapping[str, Arc],
    structural: "Iterable[str]",
    anchors: Mapping[str, str],
    children: "Mapping[str, tuple[Arc, ...]] | None" = None,
) -> dict[str, ArcPage]:
    """One page per structural arc, each carrying its children.

    Args:
        found: the arc names, as :py:func:`pysmi.corpus.arcs.arcs` returns
            them.
        structural: the arcs that get a page, as
            :py:func:`pysmi.corpus.pages.structural_arcs` picks them out.
        anchors: arc to the module registered there, so a child row can link
            to a module page rather than to an arc page that does not exist.
        children: the child map, as
            :py:func:`~pysmi.corpus.site.model.children_of` builds it. Built
            here when not given.

    Returns:
        One :py:class:`ArcPage` per structural arc, keyed by arc.
    """
    below = children if children is not None else children_of(found)

    return {
        arc: ArcPage(
            arc=arc,
            name=found[arc].name if arc in found else "",
            source=found[arc].source if arc in found else "",
            reference=found[arc].reference if arc in found else "",
            children=below.get(arc, ()),
            module=anchors.get(arc, ""),
        )
        for arc in structural
    }
