#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Writing the whole site, from the corpus the build just produced.

Three trees and an entry point, named so that nothing collides with a corpus
path -- ``asn1/``, ``json/`` and the indexes are published beside these:

============================  =========================================
``mib/<MODULE>/``             one module, everything the corpus holds
``entity/<PEN>/``             one registrant, and its modules
``oid/<arc>/``                one node of the registration tree
``browse/``                   the entry point, and the module list
============================  =========================================

**The page inventory is bounded.** A page per OID would be 98,903 of them over
pysnmp/mibs; :py:mod:`pysmi.corpus.pages` cuts the OID tree to the arcs above
the modules, and :py:mod:`pysmi.corpus.buckets` splits the long lists by range
key rather than by page number, so an added module does not renumber every
page after it. What is left is about 7,200 pages, which a crawler can finish.

See pysnmp/pysmi#276.
"""

import logging
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, NamedTuple

from pysmi.corpus import pages as corpus_pages
from pysmi.corpus.arcs import Arc
from pysmi.corpus.buckets import SIZE, Bucket, buckets
from pysmi.corpus.site import model, render
from pysmi.corpus.site.theme import Theme

logger = logging.getLogger(__name__)

#: The artifact's own version, so a consumer can tell one layout from another.
SCHEMA_VERSION: Final = 1

#: Where the stylesheet lands, which every page links to by relative path.
STYLESHEET: Final = "style.css"


class SiteReport(NamedTuple):
    """What a site build wrote."""

    modules: int
    entities: int
    arcs: int
    listings: int
    bytes: int

    @property
    def pages(self) -> int:
        """Every page written, the stylesheet aside."""
        return self.modules + self.entities + self.arcs + self.listings

    def counts(self) -> dict[str, int]:
        """The tally a build report carries."""
        return {
            "schema": SCHEMA_VERSION,
            "pages": self.pages,
            "modules": self.modules,
            "entities": self.entities,
            "arcs": self.arcs,
            "listings": self.listings,
            "bytes": self.bytes,
        }


class _Writer:
    """Writes pages under one root, counting bytes as it goes."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.bytes = 0

    def write(self, path: str, content: str) -> None:
        """One file, at *path* relative to the site root.

        UTF-8 with explicit newlines, like every other artifact a corpus
        writes: two builds of one corpus produce the same bytes whatever
        platform they ran on.
        """
        where = os.path.join(self.directory, *path.split("/"))
        os.makedirs(os.path.dirname(where), exist_ok=True)

        data = content.encode("utf-8")

        with open(where, "wb") as fileObj:
            fileObj.write(data)

        self.bytes += len(data)

    def page(self, path: str, content: str) -> None:
        """One page, written as ``index.html`` under a directory.

        Directory URLs rather than ``.html`` files, so a link is
        ``mib/IF-MIB/`` and stays that whether the host serves an index file
        or rewrites for one.
        """
        self.write(f"{path}/index.html" if path else "index.html", content)


def build_site(
    directory: str,
    documents: "Iterable[tuple[str, Mapping[str, Any], Any, Any]]",
    *,
    theme: "Theme | None" = None,
    anchors: "Mapping[str, str] | None" = None,
    arcs: "Mapping[str, Arc] | None" = None,
    entities: "Mapping[str, Mapping[str, Any]] | None" = None,
    provenance: "Mapping[str, Mapping[str, str]] | None" = None,
    closure: "Mapping[str, Mapping[str, Sequence[str]]] | None" = None,
    patches: "Mapping[str, tuple[tuple[tuple[str, str], ...], str]] | None" = None,
    size: int = SIZE,
) -> SiteReport:
    """Render the corpus as a browsable site.

    Args:
        directory: the site root. Written into, never read from.
        documents: ``(module, jsondoc, tier, rfc)`` per module, as
            :py:func:`pysmi.corpus.index.read_documents` yields them. The
            module set is whatever this gives, which is the corpus the
            manifest declared -- a namespace a build resolves against without
            publishing contributes no pages.
        theme: the frame to render into. The built-in one otherwise.
        anchors: arc to module, as
            :py:func:`pysmi.corpus.index.anchor_index` returns it. Without it
            no OID tree is written: a tree whose nodes cannot say which module
            registered them is a tree of numbers.
        arcs: the arc names, as :py:func:`pysmi.corpus.arcs.arcs` returns
            them.
        entities: the entity index, as
            :py:func:`pysmi.corpus.entity.as_document` writes it. Without it
            no registrant pages are written.
        provenance: where each module came from.
        closure: the load order per module.
        patches: per module, the defects a patch repairs and the diff.
        size: entries per bucket in a long list.

    Returns:
        What was written.
    """
    started = time.time()
    theme = theme or Theme()
    writer = _Writer(directory)
    writer.write(STYLESHEET, theme.stylesheet)

    held = []
    models: list[tuple[str, Mapping[str, Any]]] = []

    for module, document, *_ in documents:
        held.append(module)
        models.append((module, document))

    held.sort()
    reverse = model.imported_by(models)
    registered = dict(anchors or {})
    byModule: dict[str, list[str]] = {}

    for arc, module in registered.items():
        byModule.setdefault(module, []).append(arc)

    written = 0
    names = dict(arcs or {})
    below = model.children_of(names) if names else {}

    for module, document in models:
        origin = (provenance or {}).get(module) or {}
        needs = (closure or {}).get(module) or {}
        defects, diff = (patches or {}).get(module) or ((), "")

        page = model.module_page(
            module,
            document,
            anchors=sorted(
                byModule.get(module, ()),
                key=lambda x: tuple(int(y) for y in x.split(".")),
            ),
            provenance=origin,
            importedBy=reverse.get(module, ()),
            closure=needs.get("files") or (),
            missing=needs.get("missing") or (),
            defects=defects,
            patch=diff,
            under=[
                child
                for arc in byModule.get(module, ())
                for child in below.get(arc, ())
            ],
        )

        writer.page(
            f"{render.MIB}/{module}",
            render.module_html(page, theme, held=held, anchors=registered),
        )
        written += 1

    listings = _write_browse(writer, theme, held, size)
    registrants = _write_entities(writer, theme, entities or {}, size)
    listings += registrants[1]
    tree = _write_tree(writer, theme, names, registered, below)

    report = SiteReport(
        modules=written,
        entities=registrants[0],
        arcs=tree,
        listings=listings,
        bytes=writer.bytes,
    )

    logger.info(
        "site: %d pages, %.1f MB in %.1fs",
        report.pages,
        report.bytes / 1e6,
        time.time() - started,
        extra=report.counts(),
    )

    return report


def _write_browse(
    writer: _Writer, theme: Theme, held: "Sequence[str]", size: int
) -> int:
    """The entry point and the module list, bucketed where it is long."""
    found = buckets(held, size)
    written = 0

    for bucket in found:
        entries = render.module_list(
            render.root_for(2 if bucket.key else 1), bucket.entries
        )
        page = render.listing_html(
            theme,
            heading="Modules",
            intro=f"{len(held)} module(s) in this corpus.",
            entries=entries,
            base=render.BROWSE,
            buckets=found,
            here=bucket.key,
            depth=2 if bucket.key else 1,
        )

        writer.page(
            f"{render.BROWSE}/{bucket.key}" if bucket.key else render.BROWSE, page
        )
        written += 1

    # A bucketed list still needs something at browse/ itself: it is the entry
    # point every page's header links to, and a crawler starts there.
    if len(found) > 1:
        writer.page(
            render.BROWSE,
            render.listing_html(
                theme,
                heading="Modules",
                intro=f"{len(held)} module(s) in this corpus, in {len(found)} ranges.",
                entries="",
                base=render.BROWSE,
                buckets=found,
                here="",
                depth=1,
            ),
        )
        written += 1

    return written


def _write_entities(
    writer: _Writer,
    theme: Theme,
    entities: "Mapping[str, Mapping[str, Any]]",
    size: int,
) -> tuple[int, int]:
    """One page per registrant, plus the registrant list."""
    if not entities:
        return 0, 0

    found = sorted(
        (model.entity_page(arc, record) for arc, record in entities.items()),
        key=lambda x: x.number,
    )

    for page in found:
        # A registrant holding no module still gets a page: it is in the
        # entity index because the corpus registers under its arc, and the
        # registrant list links to it either way. buckets() of nothing is
        # nothing, so without this the link is a 404.
        held = buckets(page.modules, size) or (Bucket("", "", "", ()),)

        for bucket in held:
            writer.page(
                f"{render.ENTITY}/{page.number}/{bucket.key}"
                if bucket.key
                else f"{render.ENTITY}/{page.number}",
                render.entity_html(page, theme, buckets=held, here=bucket.key),
            )

        if len(held) > 1:
            writer.page(
                f"{render.ENTITY}/{page.number}",
                render.entity_html(page, theme, buckets=held, here=""),
            )

    listed = buckets([str(x.number) for x in found], size, order=int)
    byNumber = {str(x.number): x for x in found}
    listings = 0

    for bucket in listed:
        writer.page(
            f"{render.ENTITY}/{bucket.key}" if bucket.key else render.ENTITY,
            render.listing_html(
                theme,
                heading="Registrants",
                intro=f"{len(found)} enterprise arc(s) this corpus registers under.",
                entries=render.entity_list(
                    render.root_for(2 if bucket.key else 1),
                    [byNumber[x] for x in bucket.entries],
                ),
                base=render.ENTITY,
                buckets=listed,
                here=bucket.key,
                depth=2 if bucket.key else 1,
            ),
        )
        listings += 1

    return len(found), listings


def _write_tree(
    writer: _Writer,
    theme: Theme,
    arcs: "Mapping[str, Arc]",
    anchors: "Mapping[str, str]",
    below: "Mapping[str, tuple[Arc, ...]]",
) -> int:
    """One page per structural arc: the path down to every module.

    An arc at a module's anchor gets none -- that arc *is* the module, and the
    module page answers for it. An arc below one is an object, which the
    module page renders in context. See pysnmp/pysmi#292.
    """
    if not arcs or not anchors:
        return 0

    structural = corpus_pages.structural_arcs(dict(anchors))
    found = model.arc_pages(arcs, structural, anchors, below)

    for arc, page in found.items():
        writer.page(
            f"{render.OID}/{arc}", render.arc_html(page, theme, anchors=anchors)
        )

    # The root of the tree, so oid/ is not a 404 the breadcrumb points at.
    top = [x for x in structural if "." not in x]

    writer.page(
        render.OID,
        render.listing_html(
            theme,
            heading="OID tree",
            intro=f"{len(structural)} node(s) above the modules this corpus holds.",
            entries=render.module_list(render.root_for(1), ())
            or _roots(render.root_for(1), top, arcs),
            base=render.OID,
            depth=1,
        ),
    )

    return len(found)


def _roots(root: str, top: "Sequence[str]", arcs: "Mapping[str, Arc]") -> str:
    """The top-level arcs, as the OID tree's own index."""
    from pysmi.corpus.site.html import link, table, text

    rows = [
        [
            link(render.arc_url(root, arc), arc),
            text(arcs[arc].name if arc in arcs else ""),
        ]
        for arc in top
    ]

    return table(["Arc", "Name"], rows)


def bucket_keys(entries: "Iterable[str]", size: int = SIZE) -> tuple[Bucket, ...]:
    """The buckets a list of that length splits into.

    Exposed so that pysnmp/pysmi#284 can enumerate the URLs this build writes
    without rendering them again.
    """
    return buckets(entries, size)
