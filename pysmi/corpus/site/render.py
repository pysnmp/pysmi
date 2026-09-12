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
from typing import Final

from pysmi.corpus.arcs import Arc
from pysmi.corpus.buckets import Bucket, abbreviate
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
from pysmi.corpus.site.model import ArcPage, Definition, EntityPage, ModulePage
from pysmi.corpus.site.theme import Theme

#: Where each kind of page lives, under the site root.
MIB: Final = "mib"
ENTITY: Final = "entity"
OID: Final = "oid"
BROWSE: Final = "browse"

#: Rows beyond which a definition table gets its own scroll container rather
#: than stretching the page.
WIDE: Final = 12

#: How many reverse dependencies a module page lists before it stops and gives
#: a count instead.
#:
#: This is the one list on a module page with no natural bound. 1,461 modules
#: in pysnmp/mibs import ``IF-MIB`` and 5,400 import ``SNMPv2-SMI``, which is
#: 400 KB of links on a page whose own content is 40 KB -- a page about a
#: base module that is mostly a list of everything else. The count is the fact
#: worth stating; the names past the first few are not.
REVERSE: Final = 50


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
        return element("section", "") if False else ""

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
    """A definition table, each row anchored by its descriptor."""
    headings = ["Name", "OID"]

    if syntax:
        headings += ["Syntax", "Access"]

    headings += ["Status"]

    rows = []

    for item in found:
        cells = [
            join(
                (
                    tag("code", text(item.name), id=item.name),
                    element("div", item.kind, class_="desc") if item.kind else "",
                )
            ),
            tag("span", text(item.oid), class_="oid"),
        ]

        if syntax:
            cells += [tag("code", text(item.syntax)), text(item.access)]

        cells += [text(item.status)]

        if item.description:
            cells[0] += element("div", item.description, class_="desc")

        rows.append(cells)

    written = table(headings, rows, class_="defs")

    return tag("div", written, class_="wide") if len(found) > WIDE else written


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
) -> str:
    """A list page: the browse index, the registrant list, or one bucket of either."""
    root = root_for(depth)

    content = [
        element("p", intro, class_="note") if intro else "",
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
