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
from pysmi.corpus.site import crawl as site_crawl
from pysmi.corpus.site import model, render
from pysmi.corpus.site.theme import Theme

logger = logging.getLogger(__name__)

#: The artifact's own version, so a consumer can tell one layout from another.
SCHEMA_VERSION: Final = 1

#: Where the stylesheet lands, which every page links to by relative path.
STYLESHEET: Final = "style.css"


class PageSizes(NamedTuple):
    """How long each kind of list gets before it splits into buckets.

    One number would do if the lists were alike, and they are not. The module
    list is the site's front door and a reader scrolling it wants few pages;
    a registrant's list is reached by someone already narrowed to one vendor,
    and Cisco's 1,341 modules at the same size would be three pages of 500
    links each. Measured over pysnmp/mibs, 500 and 200 are the sizes that
    fall out. See pysnmp/pysmi#287.
    """

    #: ``browse/``, the module list.
    browse: int = SIZE

    #: A registrant's module list, and the registrant list itself.
    entity: int = SIZE

    @classmethod
    def of(cls, declared: "int | Mapping[str, int] | PageSizes | None") -> "PageSizes":
        """Page sizes from a number, a mapping, or nothing.

        A manifest may say one number for every list or name them
        individually, and a caller passing neither gets the defaults.

        Raises:
            ValueError: a list was named that has no page size, or a size is
                not a positive number. Refused rather than ignored: a
                manifest saying ``entities`` where the key is ``entity``
                would otherwise publish a site silently paginated wrong.
            TypeError: *declared* is neither a number nor a mapping.
        """
        if declared is None:
            return cls()

        if isinstance(declared, PageSizes):
            return declared

        if isinstance(declared, int) and not isinstance(declared, bool):
            return cls(browse=declared, entity=declared)

        if not isinstance(declared, Mapping):
            raise TypeError(
                f"a page size is a number or an object naming "
                f"{', '.join(cls._fields)}, not {type(declared).__name__}"
            )

        unknown = sorted(set(declared) - set(cls._fields))

        if unknown:
            raise ValueError(
                f"no such list: {', '.join(unknown)}; "
                f"expected some of {', '.join(cls._fields)}"
            )

        for name, value in declared.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"page size for {name} is not a positive number")

        return cls(**dict(declared))


class SiteReport(NamedTuple):
    """What a site build wrote."""

    modules: int
    entities: int
    arcs: int
    listings: int
    bytes: int
    #: Sitemap files written, the index aside. Zero for a build that declared
    #: no ``base_url`` and so is a subtree rather than a distribution site.
    sitemaps: int = 0
    #: Whether the crawl surface was written at all.
    crawlable: bool = False

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
            "sitemaps": self.sitemaps,
            "crawlable": int(self.crawlable),
        }


class _Writer:
    """Writes pages under one root, counting bytes as it goes."""

    def __init__(self, directory: str) -> None:
        self.directory = directory
        self.bytes = 0
        #: Every page written, as ``(path, lastmod)``, in the order written.
        #: The sitemap is this list; nothing walks the tree again to find out
        #: what is in it, and nothing can list a URL that was not written.
        self.written: list[tuple[str, str]] = []

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

    def page(self, path: str, content: str, lastmod: str = "") -> None:
        """One page, written as ``index.html`` under a directory.

        Directory URLs rather than ``.html`` files, so a link is
        ``mib/IF-MIB/`` and stays that whether the host serves an index file
        or rewrites for one.
        """
        self.write(f"{path}/index.html" if path else "index.html", content)
        self.written.append((f"{path}/" if path else "", lastmod))


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
    size: "int | Mapping[str, int] | PageSizes | None" = None,
    crawl: "site_crawl.Crawl | None" = None,
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
        size: entries per bucket, as
            :py:meth:`~pysmi.corpus.site.PageSizes.of` takes it -- one
            number for every list, or a mapping naming them.
        crawl: what this build declares about the site it publishes. Given,
            the whole crawl surface is written -- canonical links, JSON-LD,
            the sitemap index, ``robots.txt`` and ``llms.txt``. Omitted, the
            pages are written without it, which is what a build producing a
            subtree somebody else will assemble wants. See
            pysnmp/pysmi#284.

    Returns:
        What was written.
    """
    started = time.time()
    sizes = PageSizes.of(size)
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
    dated: dict[str, str] = {}
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

        revised = site_crawl.newest((page.lastupdated, *page.revisions))
        path = f"{render.MIB}/{module}"

        writer.page(
            path,
            render.module_html(
                page,
                theme,
                held=held,
                anchors=registered,
                head=_module_head(crawl, theme, page, path, revised),
            ),
            revised,
        )
        dated[module] = revised
        written += 1

    listings = _write_browse(writer, theme, held, sizes.browse, dated, crawl)
    registrants = _write_entities(
        writer, theme, entities or {}, sizes.entity, dated, crawl
    )
    listings += registrants[1]
    tree = _write_tree(writer, theme, names, registered, below, crawl)

    sitemaps = (
        _write_crawl(writer, crawl, len(held), registrants[0], theme.corpus)
        if crawl
        else 0
    )

    report = SiteReport(
        modules=written,
        entities=registrants[0],
        arcs=tree,
        listings=listings,
        bytes=writer.bytes,
        sitemaps=sitemaps,
        crawlable=crawl is not None,
    )

    logger.info(
        "site: %d pages, %.1f MB in %.1fs",
        report.pages,
        report.bytes / 1e6,
        time.time() - started,
        extra=report.counts(),
    )

    return report


def _module_head(
    crawl: "site_crawl.Crawl | None",
    theme: Theme,
    page: model.ModulePage,
    path: str,
    revised: str,
) -> str:
    """A module page's head metadata, or nothing for a non-distribution build.

    The description comes from the module's own DESCRIPTION where it has one
    -- a build carrying no texts has none -- and falls back to what the page
    demonstrably is. Either beats a generated sentence that says nothing.
    """
    if crawl is None:
        return ""

    url = crawl.url(path + "/")
    described = site_crawl.clip(page.description) or (
        f"{page.module}: {len(page.objects)} object(s), "
        f"{len(page.notifications)} notification(s)"
        f"{', registered at ' + page.anchors[0] if page.anchors else ''}."
    )

    return site_crawl.head(
        title=page.module,
        description=described,
        canonical=url,
        jsonld=site_crawl.module_jsonld(
            page.module,
            url,
            oid=page.anchors[0] if page.anchors else "",
            organization=page.organization,
            revised=revised,
            description=site_crawl.clip(page.description, 1000),
            terms=[
                (x.name, x.oid)
                for x in (*page.objects, *page.notifications, *page.types)
            ],
            corpus=theme.corpus,
        ),
    )


def _listing_head(
    crawl: "site_crawl.Crawl | None",
    name: str,
    path: str,
    described: str,
    items: int,
) -> str:
    """A list page's head metadata: what it collects, and how much of it."""
    if crawl is None:
        return ""

    url = crawl.url(path)

    return site_crawl.head(
        title=name,
        description=site_crawl.clip(described),
        canonical=url,
        jsonld=site_crawl.collection_jsonld(
            name, url, description=site_crawl.clip(described), items=items
        ),
    )


def _write_crawl(
    writer: _Writer,
    crawl: "site_crawl.Crawl",
    modules: int,
    entities: int,
    corpus: str,
) -> int:
    """The sitemap index, ``robots.txt`` and ``llms.txt``.

    The sitemap is built from what the writer recorded rather than by walking
    the tree, so it cannot list a URL this build did not write -- which is the
    failure that makes a sitemap worse than none.

    One file per tree, and the index emitted regardless. At 7,346 URLs one
    file is well inside the protocol's 50,000 and 50 MB, but a downstream
    corpus may not be and exceeding it fails silently.
    """
    trees: dict[str, list[tuple[str, str]]] = {}

    for path, date in writer.written:
        tree = path.split("/", 1)[0] or "root"
        trees.setdefault(tree, []).append((crawl.url(path), date))

    files: list[tuple[str, str]] = []

    for tree, entries in sorted(trees.items()):
        for part, chunk in enumerate(
            [
                entries[at : at + site_crawl.PER_SITEMAP]
                for at in range(0, len(entries), site_crawl.PER_SITEMAP)
            ]
        ):
            name = f"sitemap-{tree}.xml" if part == 0 else f"sitemap-{tree}-{part}.xml"
            writer.write(name, site_crawl.sitemap(chunk))
            files.append(
                (crawl.url(name), site_crawl.newest(date for _url, date in chunk))
            )

    writer.write("sitemap.xml", site_crawl.sitemap_index(files))
    writer.write("robots.txt", site_crawl.robots(crawl, [crawl.url("sitemap.xml")]))
    writer.write(
        "llms.txt",
        site_crawl.llms(
            crawl,
            (
                (
                    "Browse",
                    [
                        (f"All {modules} modules", crawl.url("browse/")),
                        *(
                            [(f"{entities} registrants", crawl.url("entity/"))]
                            if entities
                            else []
                        ),
                        ("OID tree", crawl.url("oid/")),
                    ],
                ),
                (
                    "Bulk data",
                    [
                        ("Sitemap index", crawl.url("sitemap.xml")),
                        ("ASN.1 sources, one file per module", crawl.url("asn1/")),
                        ("jsondoc documents", crawl.url("json/")),
                        ("OID index", crawl.url("index-v2.csv")),
                    ],
                ),
            ),
            corpus,
        ),
    )

    return len(files)


def _write_browse(
    writer: _Writer,
    theme: Theme,
    held: "Sequence[str]",
    size: int,
    dated: "Mapping[str, str]",
    crawl: "site_crawl.Crawl | None" = None,
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
            head=_listing_head(
                crawl,
                "Modules",
                f"{render.BROWSE}/{bucket.key}/" if bucket.key else f"{render.BROWSE}/",
                f"MIB modules {bucket.low} to {bucket.high}."
                if bucket.key
                else f"All {len(held)} MIB module(s) in this corpus.",
                len(bucket.entries),
            ),
        )

        writer.page(
            f"{render.BROWSE}/{bucket.key}" if bucket.key else render.BROWSE,
            page,
            site_crawl.newest(dated.get(x, "") for x in bucket.entries),
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
                head=_listing_head(
                    crawl,
                    "Modules",
                    f"{render.BROWSE}/",
                    f"All {len(held)} MIB module(s) in this corpus, "
                    f"in {len(found)} ranges.",
                    len(held),
                ),
            ),
            site_crawl.newest(dated.values()),
        )
        written += 1

    return written


def _write_entities(
    writer: _Writer,
    theme: Theme,
    entities: "Mapping[str, Mapping[str, Any]]",
    size: int,
    dated: "Mapping[str, str]",
    crawl: "site_crawl.Crawl | None" = None,
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
                render.entity_html(
                    page,
                    theme,
                    buckets=held,
                    here=bucket.key,
                    head=_listing_head(
                        crawl,
                        page.organization or f"Enterprise {page.number}",
                        f"{render.ENTITY}/{page.number}/{bucket.key}/"
                        if bucket.key
                        else f"{render.ENTITY}/{page.number}/",
                        f"{len(page.modules)} MIB module(s) registered under "
                        f"{page.arc}"
                        + (f" by {page.organization}" if page.organization else "")
                        + ".",
                        len(bucket.entries),
                    ),
                ),
                site_crawl.newest(dated.get(x, "") for x in bucket.entries),
            )

        if len(held) > 1:
            writer.page(
                f"{render.ENTITY}/{page.number}",
                render.entity_html(
                    page,
                    theme,
                    buckets=held,
                    here="",
                    head=_listing_head(
                        crawl,
                        page.organization or f"Enterprise {page.number}",
                        f"{render.ENTITY}/{page.number}/",
                        f"{len(page.modules)} MIB module(s) registered under "
                        f"{page.arc}.",
                        len(page.modules),
                    ),
                ),
                site_crawl.newest(dated.get(x, "") for x in page.modules),
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
                head=_listing_head(
                    crawl,
                    "Registrants",
                    f"{render.ENTITY}/{bucket.key}/"
                    if bucket.key
                    else f"{render.ENTITY}/",
                    f"{len(found)} enterprise arc(s) this corpus registers under.",
                    len(bucket.entries),
                ),
            ),
            site_crawl.newest(dated.values()),
        )
        listings += 1

    # A bucketed list still needs something at entity/ itself: every
    # registrant page's breadcrumb points there, and so does llms.txt. The
    # module list has had this since it was written; this one did not, and the
    # corpus it is built for buckets at 356 registrants where the fixtures did
    # not bucket at all -- 369 breadcrumbs pointed at a page nothing wrote.
    if len(listed) > 1:
        writer.page(
            render.ENTITY,
            render.listing_html(
                theme,
                heading="Registrants",
                intro=f"{len(found)} enterprise arc(s) this corpus registers "
                f"under, in {len(listed)} ranges.",
                entries="",
                base=render.ENTITY,
                buckets=listed,
                here="",
                depth=1,
                head=_listing_head(
                    crawl,
                    "Registrants",
                    f"{render.ENTITY}/",
                    f"{len(found)} enterprise arc(s) this corpus registers under.",
                    len(found),
                ),
            ),
            site_crawl.newest(dated.values()),
        )
        listings += 1

    return len(found), listings


def _write_tree(
    writer: _Writer,
    theme: Theme,
    arcs: "Mapping[str, Arc]",
    anchors: "Mapping[str, str]",
    below: "Mapping[str, tuple[Arc, ...]]",
    crawl: "site_crawl.Crawl | None" = None,
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
            f"{render.OID}/{arc}",
            render.arc_html(
                page,
                theme,
                anchors=anchors,
                head=_listing_head(
                    crawl,
                    page.arc,
                    f"{render.OID}/{arc}/",
                    f"OID {page.arc}"
                    + (f", {page.name}" if page.name else "")
                    + f": {len(page.children)} registered arc(s) beneath it.",
                    len(page.children),
                ),
            ),
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
            head=_listing_head(
                crawl,
                "OID tree",
                f"{render.OID}/",
                f"The registration tree above the modules this corpus holds: "
                f"{len(structural)} node(s).",
                len(top),
            ),
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
