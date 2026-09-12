#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The crawl surface: head metadata, JSON-LD, sitemap, robots.txt, llms.txt.

Written only when the manifest says this build is producing a **distribution
site** rather than a subtree somebody else will assemble -- which is what
``base_url`` declares. Without it there is nothing to put in a canonical link
or a sitemap entry, and guessing an origin would publish a site claiming to
live somewhere it does not.

Why the generator emits robots.txt
----------------------------------

It is policy, and policy is configuration, which a manifest carries perfectly
well. Making every downstream distribution hand-write a ``robots.txt`` that
correctly excludes its own ``asn1/`` and ``json/`` trees from search crawlers
while admitting agents is asking each of them to re-derive what the generator
already knows: which paths it wrote, what is a page and what is raw data, and
where the sitemap is.

What the generator cannot do is decide where the file lands. On GitHub Pages a
*project* site cannot serve its own ``robots.txt`` -- crawlers read it only
from the host root, which belongs to a different repository. So PySMI produces
the file and the deployment places it.

Why ``lastmod`` is a module's own revision date
-----------------------------------------------

A corpus rebuilt on every push that stamps every page with today's date
teaches a crawler the field is noise. The date a module page's content last
changed is the date the *module* last changed, which the module states itself
in ``LAST-UPDATED`` and its ``REVISION`` clauses. A page listing modules takes
the newest date among them.

So no build clock reaches a sitemap, and two builds of one corpus produce the
same one -- which is the same property every other corpus artifact has.

See pysnmp/pysmi#284.
"""

import datetime
import logging
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Final, NamedTuple

from pysmi import jsonio
from pysmi.corpus.site.html import element, tag

logger = logging.getLogger(__name__)

#: URLs per sitemap file. The protocol's own limit is 50,000 and 50 MB, and
#: this build is nowhere near either -- but a downstream corpus may be, and
#: exceeding it fails silently, so the index is emitted regardless and each
#: tree gets its own file.
PER_SITEMAP: Final = 50000

#: The artifacts a crawl policy may name, mapped to the path each one occupies
#: under the published root.
#:
#: A policy names artifacts rather than paths because the paths are the
#: generator's to choose: a distribution saying "keep search engines out of
#: the raw JSON" should not have to know whether that tree is called ``json``
#: or something else this release renamed it to.
ARTIFACTS: Final[dict[str, str]] = {
    "asn1": "/asn1/",
    "notexts": "/notexts/",
    "texts": "/texts/",
    "json": "/json/",
    "index": "/index.csv",
    "index-v2": "/index-v2.csv",
    "standard": "/standard.txt",
    "closure": "/closure.json",
    "entity-index": "/entity.json",
    "arcs": "/arcs.json",
    "core-db": "/core.db",
    "report": "/report.json",
    "site": "/",
}

#: What a page's ``lastmod`` falls back to when nothing it describes carries a
#: readable date. Absent rather than invented: a sitemap entry with no
#: ``lastmod`` says "I do not know", which is true, where one carrying the
#: build date says something false.
UNDATED: Final = ""

#: Matches the date a jsondoc revision is rendered as -- ``YYYY-MM-DD HH:MM``.
#: Shape only; :py:func:`newest` then checks it is a real calendar date.
_STAMP: Final = re.compile(r"^(\d{4}-\d{2}-\d{2})")


class Crawl(NamedTuple):
    """What a distribution build declares about the site it is publishing."""

    #: The site's origin and path, without a trailing slash --
    #: ``https://mibs.pysnmp.com``. Every canonical link and sitemap entry is
    #: built from it. This is what makes a build a distribution site.
    base: str

    #: One paragraph saying what this corpus is, for ``llms.txt``.
    description: str = ""

    #: Per user-agent, which artifacts to allow and disallow, keyed
    #: ``allow`` and ``disallow`` and naming :py:data:`ARTIFACTS`. ``*`` is
    #: the catch-all agent.
    #:
    #: A search engine and an agent want opposite policies over the same
    #: tree: to the first, 460 MB of ``asn1/`` and ``json/`` across 11,000
    #: files is crawl budget spent on files with no indexing value; to the
    #: second they are the point. One policy cannot serve both, which is why
    #: this is per-agent and why the agent list is configuration -- crawler
    #: names change faster than releases.
    policy: Mapping[str, Mapping[str, Sequence[str]]] = {}

    def url(self, path: str) -> str:
        """The absolute URL of a path relative to the site root."""
        return f"{self.base.rstrip('/')}/{path.lstrip('/')}"


def newest(dates: "Iterable[str]") -> str:
    """The latest of the dates given, as ``YYYY-MM-DD``.

    Anything that is not a date is dropped rather than ranked, for the reason
    :py:func:`pysmi.corpus.index.read_stamp` gives: ``HPR-MIB`` carries
    ``970514000000Z`` -- year 9705, month 14 -- and comparing it as a number
    would make it the newest date there will ever be.
    """
    found = ""

    for date in dates:
        match = _STAMP.match(date or "")

        if not match:
            continue

        try:
            datetime.date.fromisoformat(match.group(1))

        except ValueError:
            # Shaped like a date and not one. HPR-MIB carries 970514000000Z --
            # year 9705, month 14 -- and month 14 compares above every real
            # date there will ever be, so the module carrying it would set the
            # lastmod of every page that lists it, for good.
            logger.debug(
                "unreadable revision %s ignored for lastmod",
                date,
                extra={"revision": date},
            )
            continue

        found = max(found, match.group(1))

    return found


def head(
    *,
    title: str,
    description: str = "",
    canonical: str = "",
    jsonld: "Mapping[str, Any] | None" = None,
) -> str:
    """The ``<head>`` markup a page carries beyond its title and stylesheet.

    Args:
        title: the page's own title, which the frame renders separately; this
            is here only for the JSON-LD.
        description: one line for ``meta name="description"``, clipped by the
            caller.
        canonical: the page's absolute URL.
        jsonld: the structured description of what the page is about.

    Returns:
        Markup ending in a newline, or ``""`` when there is nothing to say.
    """
    written = []

    if description:
        written.append(tag("meta", name="description", content=description))

    if canonical:
        written.append(tag("link", rel="canonical", href=canonical))

    if jsonld:
        # Compact, and escaped for a script element rather than for HTML:
        # inside <script> the only sequence that can end it is "</", and a
        # DESCRIPTION containing one would otherwise close the element.
        written.append(
            tag(
                "script",
                jsonio.dumps(jsonld).replace("</", "<\\/").replace("<!--", "<\\!--"),
                type="application/ld+json",
            )
        )

    return "\n".join(written) + "\n" if written else ""


def module_jsonld(
    module: str,
    url: str,
    *,
    oid: str = "",
    organization: str = "",
    revised: str = "",
    description: str = "",
    terms: "Iterable[tuple[str, str]] | None" = None,
    corpus: str = "",
    distribution: str = "",
) -> dict[str, Any]:
    """A MIB module as structured data.

    A module is a published artifact with an identifier, a publisher and a
    revision date -- a ``Dataset`` -- and where terms are given it is also the
    ``DefinedTermSet`` they belong to.

    **The identifiers are the OIDs**, which is the whole point: an OID is a
    globally unique identifier that already exists, and a consumer holding one
    should be able to match it without reading prose.

    *terms* is normally empty and *distribution* is what replaces it. Listing
    every definition here was the same duplication the page itself stopped
    making: over pysnmp/mibs it was 750,139 nodes and 90 MB of JSON-LD
    restating what ``json/`` already holds in a form built for the purpose.
    ``distribution`` points a consumer at that document instead, which is what
    ``Dataset`` is for.

    Args:
        module: the module name, which is its ``name``.
        url: the page's absolute URL.
        oid: the arc the module registers at, as its own identifier.
        organization: the ORGANIZATION clause, as the publisher.
        revised: the newest revision, as ``YYYY-MM-DD``.
        description: the module's DESCRIPTION.
        terms: ``(name, oid)`` per thing the module defines, for a caller that
            wants them. Names and identifiers only, and no
            ``inDefinedTermSet`` back-reference -- nesting under
            ``hasDefinedTerm`` already says a term belongs to this set.
        distribution: the URL of the module's own machine-readable document,
            which is where a consumer should go for the definitions.
        corpus: what the corpus is called, as the containing collection.

    Returns:
        The JSON-LD node.
    """
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": ["DefinedTermSet", "Dataset"] if terms else "Dataset",
        "name": module,
        "url": url,
    }

    if oid:
        node["identifier"] = f"urn:oid:{oid}"

    if organization:
        node["publisher"] = {"@type": "Organization", "name": organization}

    if revised:
        node["dateModified"] = revised

    if description:
        node["description"] = description

    if corpus:
        node["isPartOf"] = {"@type": "Dataset", "name": corpus}

    defined = [
        {
            "@type": "DefinedTerm",
            "name": name,
            "identifier": f"urn:oid:{termOid}" if termOid else name,
        }
        for name, termOid in terms or ()
    ]

    if defined:
        node["hasDefinedTerm"] = defined

    if distribution:
        node["distribution"] = {
            "@type": "DataDownload",
            "encodingFormat": "application/json",
            "contentUrl": distribution,
        }

    return node


def collection_jsonld(
    name: str, url: str, *, description: str = "", items: int = 0
) -> dict[str, Any]:
    """A list page as structured data: a collection, and how big it is."""
    node: dict[str, Any] = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": name,
        "url": url,
    }

    if description:
        node["description"] = description

    if items:
        node["numberOfItems"] = items

    return node


def sitemap(entries: "Iterable[tuple[str, str]]") -> str:
    """One sitemap file, from ``(url, lastmod)`` pairs.

    A pair with no ``lastmod`` is written without one. See :py:data:`UNDATED`.
    """
    written = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url, date in entries:
        inner = element("loc", url)

        if date:
            inner += element("lastmod", date)

        written.append(tag("url", inner))

    written.append("</urlset>")

    return "\n".join(written) + "\n"


def sitemap_index(entries: "Iterable[tuple[str, str]]") -> str:
    """The sitemap index, from ``(url, lastmod)`` pairs of sitemap files."""
    written = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for url, date in entries:
        inner = element("loc", url)

        if date:
            inner += element("lastmod", date)

        written.append(tag("sitemap", inner))

    written.append("</sitemapindex>")

    return "\n".join(written) + "\n"


def robots(crawl: Crawl, sitemaps: "Iterable[str]") -> str:
    """``robots.txt``, from the policy the manifest declares.

    An artifact the policy names that this build did not produce is skipped
    rather than written: a rule about a tree that is not there is a rule
    nobody can act on, and it would read as though the tree existed.
    """
    written = []

    for agent, rules in crawl.policy.items():
        written.append(f"User-agent: {agent}")

        for verb, key in (("Allow", "allow"), ("Disallow", "disallow")):
            for artifact in rules.get(key) or ():
                path = ARTIFACTS.get(artifact)

                if path is None:
                    logger.warning(
                        "crawl policy names %r, which is not an artifact",
                        artifact,
                        extra={"artifact": artifact},
                    )
                    continue

                written.append(f"{verb}: {path}")

        written.append("")

    for url in sitemaps:
        written.append(f"Sitemap: {url}")

    if written and written[-1] != "":
        written.append("")

    return "\n".join(written)


def llms(
    crawl: Crawl,
    sections: "Iterable[tuple[str, Sequence[tuple[str, str]]]]",
    name: str = "MIB corpus",
) -> str:
    """``llms.txt``: what this corpus is, and where the data actually is.

    A convention rather than a mechanism -- no major AI crawler is documented
    as consuming it. It is emitted, and nothing depends on it. What reaches an
    AI crawler is server-rendered HTML and a ``robots.txt`` that admits it.

    Args:
        crawl: the site's declaration.
        sections: ``(heading, [(label, url), ...])`` in the order they are
            written.
        name: what the corpus is called, as the title.
    """
    written = [f"# {name}"]

    if crawl.description:
        written.append("")
        written.append(f"> {' '.join(crawl.description.split())}")

    for heading, links in sections:
        if not links:
            continue

        written.append("")
        written.append(f"## {heading}")
        written.append("")

        for label, url in links:
            written.append(f"- [{label}]({url})")

    return "\n".join(written) + "\n"


def clip(prose: str, width: int = 300) -> str:
    """One line of prose, for a meta description.

    Whitespace collapsed, because a DESCRIPTION arrives with the publisher's
    line breaks in it and a meta tag is one line.
    """
    flat = " ".join((prose or "").split())

    if len(flat) <= width:
        return flat

    cut = flat[: width - 1]

    return cut[: cut.rfind(" ")].rstrip(",;:") + "…" if " " in cut else cut + "…"
