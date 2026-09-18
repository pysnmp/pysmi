#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Turning a page model into the HTML that is served.

**Everything is in the bytes.** No page here fetches anything: not the object
table, not the description, not the navigation. pysnmp/pysmi#284 measured the
alternative and it costs the same, while being unreadable to the AI crawlers
that do not run JavaScript -- to them, a client-rendered object table is a page
about a MIB module that does not say what the module defines.

URLs are relative to the site root, which every page carries as *root* --
``../../`` and so on. A site published under ``/mibs/`` on a project host works
without being told where it lives, and so does one opened from a local
directory.

See pysnmp/pysmi#276.
"""

from collections.abc import Iterable, Mapping, Sequence
from typing import Final, NamedTuple

from pysmi.corpus.arcs import Arc
from pysmi.corpus.buckets import Bucket, abbreviate
from pysmi.corpus.site import dates
from pysmi.corpus.site.html import (
    definitions,
    element,
    join,
    link,
    paragraphs,
    table,
    tag,
    text,
)
from pysmi.corpus.site.model import (
    ArcPage,
    Definition,
    EntityPage,
    ModulePage,
    Overview,
    Recent,
)
from pysmi.corpus.site.theme import Theme

#: Where each kind of page lives, under the site root.
MIB: Final = "mib"
ENTITY: Final = "entity"
OID: Final = "oid"
BROWSE: Final = "browse"

#: Rows beyond which a definition table gets its own scroll container rather
#: than stretching the page.

#: How many reverse dependencies a module page lists before it stops and gives
#: a count instead.
#:
#: This is the one list on a module page with no natural bound. Nearly every
#: module in a corpus imports ``SNMPv2-SMI``, and a large fraction import
#: ``IF-MIB``, so an unbounded list runs to an order of magnitude more bytes
#: than the page's own content -- a page about a base module that is mostly a
#: list of everything else. The count is the fact worth stating; the names past
#: the first few are not.
REVERSE: Final = 50

#: What a tier's module-count tile is called.
TIER_TILE: Final[dict[str, str]] = {
    "standard": "Standard modules",
    "draft": "Internet-Draft modules",
    "vendor": "Vendor modules",
}

#: What a tier is called inside the heading of its recent-revisions table.
TIER_RECENT: Final[dict[str, str]] = {
    "standard": "standard",
    "draft": "Internet-Draft",
    "vendor": "vendor",
}


def root_for(depth: int) -> str:
    """The prefix that reaches the site root from *depth* directories down."""
    return "../" * depth if depth else ""


def module_url(root: str, module: str) -> str:
    """Where a module's page is."""
    return f"{root}{MIB}/{module}/"


def entity_url(root: str, number: int) -> str:
    """Where a registrant's page is."""
    return f"{root}{ENTITY}/{number}/"


def arc_url(root: str, arc: str) -> str:
    """Where an arc's page is."""
    return f"{root}{OID}/{arc}/"


def _crumbs(root: str, trail: "Sequence[tuple[str, str]]") -> str:
    """The breadcrumb, last entry unlinked because it is this page."""
    written = [link(f"{root}{BROWSE}/", "Browse")]

    for label, href in trail[:-1]:
        written.append(link(href, label))

    if trail:
        written.append(element("span", trail[-1][0]))

    return join(written)


def _section(heading: str, content: str, *, note: str = "") -> str:
    """One ``<section>``, or nothing at all when it has nothing to say.

    A heading over an empty table is worse than no heading: it reads as a fact
    the corpus holds and is not showing.
    """
    if not content:
        return ""

    return tag(
        "section",
        join(
            (
                element("h2", heading),
                element("p", note, class_="note") if note else "",
                content,
            )
        ),
    )


def _defs(found: "Sequence[Definition]", *, syntax: bool = True) -> str:
    """A definition table, each row anchored by its descriptor.

    The cells carry no wrapping ``code`` or ``span``: the columns are fixed,
    so the stylesheet reaches them by position and the markup says only what
    is in them. It reads the same and it is 61 bytes a row smaller, which is a
    quarter off the module pages of a corpus whose definitions run to the
    hundreds of thousands. Measured on pysnmp/mibs, the markup around a
    definition came to more bytes than the definition.

    A theme replacing :py:data:`~pysmi.corpus.site.theme.STYLESHEET` styles
    ``.defs td`` by position, and ``.defs.typed`` is the five-column shape --
    Name, OID, Syntax, Access, Status -- against the three-column one.
    """
    headings = ["Name", "OID"]

    if syntax:
        headings += ["Syntax", "Access"]

    headings += ["Status"]

    rows = []
    anchors = []

    for item in found:
        anchors.append(item.name)
        cells = [
            text(item.name)
            + (element("div", item.kind, class_="desc") if item.kind else ""),
            text(item.oid),
        ]

        if syntax:
            cells += [text(item.syntax), text(item.access)]

        cells += [text(item.status)]

        if item.description:
            cells[0] += element("div", item.description, class_="desc")

        rows.append(cells)

    written = table(
        headings,
        rows,
        class_="defs typed" if syntax else "defs",
        anchors=anchors,
    )

    return written


def _imports(
    root: str, imports: "Mapping[str, tuple[str, ...]]", held: "Iterable[str]"
) -> str:
    """What this module imports, linked where the corpus holds the module."""
    inside = set(held)
    rows = []

    for module, symbols in imports.items():
        name = (
            link(module_url(root, module), module)
            if module in inside
            else element("span", module)
        )
        rows.append([name, tag("code", text(", ".join(symbols)))])

    return table(["From", "Symbols"], rows)


def _module_links(root: str, modules: "Iterable[str]") -> str:
    """A plain list of module links."""
    written = join(tag("li", link(module_url(root, x), x)) for x in modules)

    return tag("ul", written, class_="plain") if written else ""


def key_strip(root: str, found: "Sequence[Bucket]", here: str, base: str) -> str:
    """Every bucket of a list, on every page of that list.

    So any bucket is one hop from any other and crawl depth does not grow with
    the corpus (pysnmp/pysmi#284). The rendered label is clipped; the URL
    keeps the whole key.
    """
    if len(found) < 2:
        return ""

    written = []

    for bucket in found:
        label = abbreviate(bucket)
        href = f"{root}{base}/{bucket.key}/"

        written.append(
            tag(
                "li",
                element("span", label, class_="here")
                if bucket.key == here
                else link(href, label),
            )
        )

    return tag("nav", tag("ul", join(written), class_="keys"), class_="keys")


def module_html(
    page: ModulePage,
    theme: Theme,
    *,
    held: "Iterable[str]" = (),
    anchors: "Mapping[str, str] | None" = None,
    head: str = "",
) -> str:
    """One module's page.

    Args:
        page: the model, as :py:func:`~pysmi.corpus.site.model.module_page`
            builds it.
        theme: the frame to render into.
        held: the modules this corpus holds, so an import is linked only where
            the link would resolve.
        anchors: arc to module, so an arc below this one that is itself a
            module links to that module's page.
        head: extra ``<head>`` markup, which pysnmp/pysmi#284 fills in.
    """
    root = root_for(2)
    facts = [
        (
            "Registered at",
            join(tag("div", tag("span", text(x), class_="oid")) for x in page.anchors),
        ),
        ("Last updated", text(page.lastupdated)),
        ("Organization", text(page.organization)),
        ("Revisions", text(", ".join(page.revisions))),
        ("Namespace", text(page.provenance.get("namespace"))),
        ("Source file", tag("code", text(page.provenance.get("file")))),
        ("Digest", tag("code", text(page.provenance.get("digest")))),
    ]

    content = [
        definitions(facts, class_="facts"),
        _section("Description", paragraphs(page.description)),
        _section("Contact", paragraphs(page.contact)),
        _section(
            "Repairs",
            _repairs(page),
            note="This copy differs from the publisher's text. What was wrong, and what was changed:",
        ),
        _section("Imports", _imports(root, page.imports, held)),
        _section("Imported by", _reverse(root, page.importedBy)),
        _section(
            "Load order",
            _closure(page),
            note="Every file a consumer needs in order to load this module, dependencies first.",
        ),
        _section(
            "Under this module's arcs",
            _under(root, page.under, anchors),
            note="Where the registration tree carries on below this module.",
        ),
        _section("Textual conventions", _defs(page.types)),
        _section("Objects", _defs(page.objects)),
        _section("Notifications", _defs(page.notifications, syntax=False)),
        _section("Conformance", _defs(page.conformance, syntax=False)),
    ]

    return theme.render(
        title=f"{page.module} | {theme.corpus}",
        head=head,
        root=root,
        stylesheet=f"{root}style.css",
        heading=text(page.module),
        breadcrumb=_crumbs(root, ((page.module, ""),)),
        content=join(content),
        generator="PySMI",
    )


def _under(
    root: str, under: "Sequence[Arc]", anchors: "Mapping[str, str] | None"
) -> str:
    """The arcs below this module's own registrations.

    A module's anchor gets no arc page -- that arc *is* the module -- so this
    is the only thing linking down into the tree past it. Without it the
    structural arcs beneath a module are reachable from nothing, which
    pysnmp/pysmi#284 does not allow.
    """
    if not under:
        return ""

    registered = anchors or {}
    rows = []

    for arc in under:
        module = registered.get(arc.arc, "")
        href = module_url(root, module) if module else arc_url(root, arc.arc)

        rows.append(
            [
                link(href, arc.arc),
                text(arc.name),
                element("code", module) if module else "",
            ]
        )

    return table(["Arc", "Name", "Module"], rows)


def _reverse(root: str, modules: "Sequence[str]") -> str:
    """What imports this module, bounded.

    The count first, because for a base module that is the whole of what a
    reader learns from this section, and the names are what would otherwise
    make the page mostly a list of other modules. See :py:data:`REVERSE`.
    """
    if not modules:
        return element(
            "p", "Nothing in this corpus imports this module.", class_="note"
        )

    shown = modules[:REVERSE]
    note = f"{len(modules)} module(s) in this corpus import this one"

    if len(modules) > REVERSE:
        note += f"; the first {REVERSE} are listed"

    return join((element("p", f"{note}.", class_="note"), _module_links(root, shown)))


def _repairs(page: ModulePage) -> str:
    """What a patch on this module repaired, and the diff that did it.

    A diff says what changed and never what was wrong. pysnmp/pysmi#279 puts
    the defect in the patch header; this renders it beside the diff, because a
    reader has a right to know why the text served here differs from the
    publisher's.
    """
    if not page.defects and not page.patch:
        return ""

    written = []

    if page.defects:
        written.append(
            tag(
                "ul",
                join(
                    tag(
                        "li",
                        link(url, identifier) if url else element("code", identifier),
                    )
                    for identifier, url in page.defects
                ),
                class_="plain",
            )
        )

    if page.patch:
        written.append(element("pre", page.patch))

    return join(written)


def _closure(page: ModulePage) -> str:
    """The load order, and anything it needs that the corpus does not hold."""
    if not page.closure:
        return ""

    written = [element("pre", "\n".join(page.closure))]

    if page.missing:
        written.append(
            element(
                "p",
                "Not held by this corpus: " + ", ".join(page.missing),
                class_="note",
            )
        )

    return join(written)


def entity_html(
    page: EntityPage,
    theme: Theme,
    *,
    buckets: "Sequence[Bucket]" = (),
    here: str = "",
    head: str = "",
) -> str:
    """One registrant's page, or one bucket of a long module list."""
    root = root_for(3 if here else 2)
    base = f"{ENTITY}/{page.number}"
    shown = next(
        (x.entries for x in buckets if x.key == here),
        page.modules if not buckets else buckets[0].entries,
    )

    facts = [
        ("Enterprise number", text(page.number)),
        ("Arc", tag("span", text(page.arc), class_="oid")),
        ("Modules", text(len(page.modules))),
    ]

    content = [
        definitions(facts, class_="facts"),
        _section("Contacts", _contacts(page)),
        _section(
            "Modules",
            join(
                (
                    key_strip(root, buckets, here, base),
                    _module_links(root, shown),
                )
            ),
        ),
    ]

    title = page.organization or f"Enterprise {page.number}"

    return theme.render(
        title=f"{title} | {theme.corpus}",
        head=head,
        root=root,
        stylesheet=f"{root}style.css",
        heading=text(title),
        breadcrumb=_crumbs(
            root,
            (
                ("Registrants", f"{root}{ENTITY}/"),
                (title, ""),
            ),
        ),
        content=join(content),
        generator="PySMI",
    )


def _contacts(page: EntityPage) -> str:
    """Who to tell about a problem with an arc, and who says so."""
    rows = []

    for contact in page.contacts:
        authority = contact.get("authority") or ""
        where = contact.get("module") or contact.get("source") or ""

        rows.append(
            [
                text(contact.get("organization")),
                text(contact.get("contact")),
                tag("code", text(contact.get("email"))),
                link(authority, where) if authority else text(where),
            ]
        )

    return table(["Organization", "Contact", "Email", "Says"], rows)


def arc_html(
    page: ArcPage,
    theme: Theme,
    *,
    anchors: "Mapping[str, str] | None" = None,
    head: str = "",
) -> str:
    """One node of the registration tree, and its children."""
    root = root_for(2)
    registered = anchors or {}
    rows = []

    for child in page.children:
        module = registered.get(child.arc, "")
        href = module_url(root, module) if module else arc_url(root, child.arc)

        rows.append(
            [
                link(href, child.arc),
                text(child.name),
                element("code", module) if module else "",
                _says(child.source, child.reference),
            ]
        )

    facts = [
        ("Name", text(page.name)),
        ("Named by", _says(page.source, page.reference)),
        ("Children", text(len(page.children))),
    ]

    content = [
        definitions(facts, class_="facts"),
        _section("Under this arc", table(["Arc", "Name", "Module", "Named by"], rows)),
    ]

    return theme.render(
        title=f"{page.arc} | {theme.corpus}",
        head=head,
        root=root,
        stylesheet=f"{root}style.css",
        heading=text(page.arc),
        breadcrumb=_crumbs(root, (("OID tree", f"{root}{OID}/"), (page.arc, ""))),
        content=join(content),
        generator="PySMI",
    )


def _says(source: str, reference: str) -> str:
    """Which kind of fact a name is, and where it comes from.

    A registry, a cited standard and a name read off whichever MIB mentioned
    an arc are three different things, and a reader has to be able to tell
    them apart (pysnmp/pysmi#288).
    """
    if not source:
        return ""

    if reference.startswith(("http://", "https://")):
        return link(reference, source)

    return element("span", f"{source} - {reference}" if reference else source)


def listing_html(
    theme: Theme,
    *,
    heading: str,
    intro: str,
    entries: str,
    base: str,
    buckets: "Sequence[Bucket]" = (),
    here: str = "",
    depth: int = 1,
    head: str = "",
    summary: str = "",
    listing: str = "",
) -> str:
    """A list page: the browse index, the registrant list, or one bucket of either.

    Args:
        theme: the frame to render into.
        heading: the page's own heading, which is also its breadcrumb.
        intro: one line saying what the list holds, or ``""``.
        entries: the list itself, already rendered.
        base: where this list lives under the site root, for the key strip.
        buckets: every bucket of the list, so any one is one hop from any
            other.
        here: the bucket this page is, or ``""`` for the list's own root.
        depth: how many directories down the page sits, for relative URLs.
        head: extra ``<head>`` markup.
        summary: markup between the intro and the list -- what
            :py:func:`overview_html` renders for the entry point. Empty on a
            bucket page, which is a slice of a list rather than a front page.
        listing: a heading over the list itself. A page carrying a *summary*
            needs one: the list is then the last of several sections rather
            than the whole page, and without a heading it reads as a
            continuation of the section above it.
    """
    root = root_for(depth)

    content = [
        element("p", intro, class_="note") if intro else "",
        summary,
        element("h2", listing) if listing else "",
        key_strip(root, buckets, here, base),
        entries,
    ]

    return theme.render(
        title=f"{heading} | {theme.corpus}",
        head=head,
        root=root,
        stylesheet=f"{root}style.css",
        heading=text(heading),
        breadcrumb=_crumbs(root, ((heading, ""),)),
        content=join(content),
        generator="PySMI",
    )


def figure(count: int) -> str:
    """A count as a page writes it, grouped so the magnitude is readable."""
    return f"{count:,}"


def _tile(label: str, count: int) -> str:
    """One figure and what it counts.

    The figure first in the markup as well as on the page: it is what the
    reader is here for, and a screen reader announcing the label first would
    read the row as a sentence with the number at the end of it.
    """
    return tag(
        "li",
        join(
            (
                element("span", figure(count), class_="figure"),
                element("span", label, class_="label"),
            )
        ),
    )


def kpis(overview: Overview) -> str:
    """The corpus in figures.

    Each tile is a count the build already had. A tile whose count is zero is
    left out rather than rendered as ``0``: a build given no arc names holds
    no opinion about how many arcs there are, and "0 registrants" states one.
    """
    tiles = [
        (TIER_TILE.get(tier, f"{tier} modules"), count)
        for tier, count in overview.tiers.items()
    ]

    tiles += [
        ("Registrants", overview.registrants),
        # "OID arcs" rather than "named OID arcs": the arc index carries every
        # arc the corpus registers at and every prefix of one, and an arc no
        # registry and no MIB names is in it with an empty name.
        ("OID arcs", overview.arcs),
        ("Objects", overview.objects),
        ("Notifications", overview.notifications),
        ("Textual conventions", overview.types),
        ("Repaired modules", overview.repaired),
        ("Incomplete closures", overview.incomplete),
    ]

    written = join(_tile(label, count) for label, count in tiles if count)

    return tag("ul", written, class_="kpis") if written else ""


def _hero(overview: Overview) -> str:
    """The one figure the page leads with, and what dates the corpus.

    The module count rather than any of the others, because it is the figure
    a reader arrives holding a question about, and one per page -- a second
    number at the same size is two headlines and no lead.
    """
    if not overview.modules:
        return ""

    said = f"module{'' if overview.modules == 1 else 's'} in this corpus"

    if overview.revised:
        said += f", most recently revised {overview.revised}"

    return tag(
        "p",
        join(
            (
                element("span", figure(overview.modules), class_="figure"),
                element("span", said, class_="label"),
            )
        ),
        class_="hero",
    )


def recent_list(
    root: str,
    found: "Sequence[Recent]",
    *,
    dated: str = "revised",
    column: str = "Revised",
) -> str:
    """The most recently dated modules of one tier, newest first.

    Args:
        root: the prefix that reaches the site root.
        found: the rows, already ordered, as
            :py:meth:`pysmi.corpus.site.model.Tally.overview` ordered them.
        dated: which of :py:class:`~pysmi.corpus.site.model.Recent`'s dates
            the rows are ordered by, and so which one the table prints.
        column: what to call that date's column.
    """
    rows = [
        [
            link(module_url(root, x.module), x.module),
            text(getattr(x, dated)),
            text(x.organization),
            text(figure(x.definitions)),
        ]
        for x in found
    ]

    return table(
        ["Module", column, "Organization", "Definitions"],
        rows,
        class_="recent",
    )


class _Axis(NamedTuple):
    """One kind of date the recent lists can be ordered by.

    Two of these exist: the date a module's publisher last revised it, which
    every corpus has, and the date the publishing distribution last changed
    it, which only a build given
    :py:mod:`~pysmi.corpus.site.dates` has. They render identically and say
    different things, which is the whole reason the entry point offers both.
    """

    #: Per tier, the rows, newest first.
    rows: "Mapping[str, tuple[Recent, ...]]"

    #: Per tier, how many modules this axis has a date for, which is the pool
    #: :py:attr:`rows` holds the newest few of.
    held: "Mapping[str, int]"

    #: The :py:class:`~pysmi.corpus.site.model.Recent` field holding the date.
    dated: str

    #: That date's column heading.
    column: str

    #: What the tab is called.
    label: str

    #: The past participle for "the ten most recently ... of".
    verb: str

    #: What the date is, to finish "The date is ...".
    said: str

    #: What the pool is, to finish "the 486 standard module(s) this ...".
    pool: str

    #: The id the tab's radio input carries, which its label points at.
    name: str


#: The axis every corpus has. The dates are the publishers' own, so this is
#: what the industry did rather than what this distribution did.
PUBLISHED: Final = _Axis(
    rows={},
    held={},
    dated="revised",
    column="Revised",
    label="Revised by publisher",
    verb="revised",
    said="the one the module itself carries",
    pool="corpus holds",
    name="recent-published",
)

#: The axis a distribution supplies. See :py:mod:`pysmi.corpus.site.dates`.
CHANGED: Final = _Axis(
    rows={},
    held={},
    dated="changed",
    column="Changed",
    label=dates.LABEL,
    verb="changed",
    # The pool is never "this corpus holds": a distribution may date a
    # fraction of a tier -- pysnmp/mibs tracks the modules in its own tree and
    # not the standard ones it takes from pysmi -- and a note counting what it
    # does not track would claim it dated modules it never saw.
    said="the day this distribution last changed the module, which is not a "
    "date the module itself carries",
    pool="distribution tracks",
    name="recent-changed",
)


def _recent_sections(
    root: str, overview: Overview, axis: _Axis, *, tabbed: bool
) -> str:
    """Per tier, the modules this axis dates most recently.

    Args:
        root: the prefix that reaches the site root.
        overview: the figures, for how many modules each tier holds.
        axis: which date to order and print.
        tabbed: whether a tab label above already says which date this is. It
            does when both axes are offered, and then the heading names only
            the tier; a lone axis has to say it in the heading itself.
    """
    sections = []

    for tier, found in axis.rows.items():
        named = TIER_RECENT.get(tier, tier)
        held = axis.held.get(tier, 0)

        if len(found) >= held:
            note = (
                f"The {figure(held)} {named} module(s) this {axis.pool}, "
                f"newest first. The date is {axis.said}."
            )

        else:
            note = (
                f"The {figure(len(found))} most recently {axis.verb} of the "
                f"{figure(held)} {named} module(s) this {axis.pool}. The "
                f"date is {axis.said}."
            )

        sections.append(
            _section(
                f"{named[:1].upper()}{named[1:]} modules"
                if tabbed
                else f"Recently {axis.verb} {named} modules",
                recent_list(root, found, dated=axis.dated, column=axis.column),
                note=note,
            )
        )

    return join(sections)


def _switch(root: str, overview: Overview, offered: "Sequence[_Axis]") -> str:
    """The recent lists of every axis, one shown at a time.

    A radio per axis and a label pointing at it, which is a tab that needs no
    script: the stylesheet shows the panel whose radio is checked. Every panel
    is in the markup either way, so a reader with no CSS sees both lists under
    their own headings and a crawler reads all of it -- the page states the
    same facts whatever runs.

    Every axis in *offered* has rows, which is what makes checking the first
    of them right: see :py:func:`overview_html`.
    """
    controls = []
    panels = []

    for index, axis in enumerate(offered):
        controls.append(
            tag(
                "input",
                type="radio",
                name="recent",
                id=axis.name,
                checked=index == 0 or None,
            )
        )
        panels.append(
            tag(
                "div",
                _recent_sections(root, overview, axis, tabbed=True),
                class_=f"panel {axis.name}",
            )
        )

    return tag(
        "div",
        join(
            (
                *controls,
                tag(
                    "nav",
                    join(
                        element("label", x.label, for_=x.name, class_="tab")
                        for x in offered
                    ),
                    class_="tabs",
                    aria_label="Which date the lists are ordered by",
                ),
                *panels,
            )
        ),
        class_="switch",
    )


def overview_html(root: str, overview: Overview, *, label: str = "") -> str:
    """The entry point's figures, and what the corpus changed most recently.

    One list of recent modules per tier, ordered by the date their publishers
    last revised them. A build given a distribution's own dates -- see
    :py:mod:`pysmi.corpus.site.dates` -- offers those as a second tab, since
    "what has this distribution done lately" is a question the publishers'
    dates cannot answer.

    Args:
        root: the prefix that reaches the site root, since the module links
            in the recent tables are relative like every other link here.
        overview: the figures, as
            :py:meth:`pysmi.corpus.site.model.Tally.overview` totalled them.
        label: what to call the distribution's own dates, from
            ``site.changed.label``. :py:data:`pysmi.corpus.site.dates.LABEL`
            otherwise.

    Returns:
        Markup for the entry point, or ``""`` for a corpus of no modules.
    """
    if not overview.modules:
        return ""

    figures = tag("section", join((_hero(overview), kpis(overview))), class_="overview")
    published = PUBLISHED._replace(rows=overview.latest, held=overview.tiers)
    changed = CHANGED._replace(
        rows=overview.latestChanged,
        held=overview.datedChanged,
        label=label or dates.LABEL,
    )

    # An axis nothing is dated on is not offered. A tab strip over an empty
    # panel is worse than no tab strip: a corpus whose modules carry no
    # REVISION at all -- which the publishers' axis reads, and plenty of
    # vendor text has none -- would open on a blank list, with the populated
    # one hidden behind a control nothing suggests pressing.
    offered = [x for x in (published, changed) if x.rows]

    if not offered:
        return figures

    if len(offered) == 1:
        return join(
            (figures, _recent_sections(root, overview, offered[0], tabbed=False))
        )

    return join((figures, _switch(root, overview, offered)))


def module_list(root: str, modules: "Iterable[str]") -> str:
    """The entries of a module list page."""
    return _module_links(root, modules)


def entity_list(root: str, pages: "Iterable[EntityPage]") -> str:
    """The entries of the registrant list."""
    rows = [
        [
            link(entity_url(root, x.number), x.number),
            text(x.organization),
            text(len(x.modules)),
        ]
        for x in pages
    ]

    return table(["PEN", "Organization", "Modules"], rows)
