#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Which arcs of the registration tree get a page, and where the rest resolve.

A site rendering ``oid/<arc>/`` as a page per node, taken literally, is a page
per OID any module defines. Over pysnmp/mibs' corpus that is **98,903 pages**
and roughly 654 MB, against a GitHub Pages limit of 1 GB -- the OID tree alone
seventeen times the module pages it exists to lead to.

Crawl budget is the worse half of it. A hundred thousand URLs on a static site
means the pages that matter compete with 85,644 leaf-arc pages that each state
one object's syntax, which the module page already states in context.

The rule
--------

**A leaf arc gets no page.** It is an object inside a module, and the module
page renders it with an anchor:
``oid/1.3.6.1.4.1.9.9.138.1.2.5.1.2`` resolves to
``mib/CISCO-ENTITY-ALARM-MIB/#ceAlarmSeverity``.

**An arc at a module's anchor gets no page of its own either.** That arc *is*
the module: ``oid/1.3.6.1.4.1.9.9.138/`` resolves to
``mib/CISCO-ENTITY-ALARM-MIB/``.

**What remains is the structural tree** -- the arcs from the root down to each
module's anchor, exclusive. Over pysnmp/mibs that is 14,752 arcs counted with
the anchors and **1,493 without**, which is the set that actually gets pages,
and the whole site becomes about 7,200 pages rather than 100,000. A crawler
can finish that.

Why this is the right cut rather than the cheap one
---------------------------------------------------

The OID tree's job is navigation and accountability: walk the registration
tree, see who owns an arc, reach the module. The arcs *above* a module serve
that. Below the anchor you are inside one module, and the module page is the
better surface -- it has the object in the context of its table, its index, its
syntax and its description.

Resolving an arc that has no page
---------------------------------

The tree still has to answer for any OID a reader pastes from a trap, which is
the main way in. :py:func:`resolve` is that answer, as a longest-prefix lookup
rather than a table: emitting a stub page per unpaged arc would cost 85,644
files and put every one of them back in the crawlable surface, which is the
thing this exists to avoid. A site renders the lookup in the browser from the
published index and leaves the unpaged arcs out of ``sitemap.xml``.

See pysnmp/pysmi#292. Consumed by the site generator in pysnmp/pysmi#276.
"""

import logging
from typing import Final, NamedTuple

from pysmi.corpus.arcs import prefixes

logger = logging.getLogger(__name__)

#: The arc is a module's own anchor, so it resolves to that module's page.
MODULE: Final = "module"

#: The arc is below a module's anchor, so it is an object inside that module
#: and resolves to the module's page at the object's anchor.
OBJECT: Final = "object"


class Target(NamedTuple):
    """Where an arc with no page of its own resolves to."""

    #: The module whose page answers for the arc.
    module: str

    #: The descriptor to anchor at, for an object inside the module. Empty
    #: where the arc is the module itself, and where the corpus knows the
    #: module but not a name for that particular arc.
    anchor: str = ""

    #: :py:data:`MODULE` or :py:data:`OBJECT` -- why the arc has no page.
    #: A site renders the two differently: one is the module, the other is a
    #: thing inside it.
    reason: str = MODULE


def structural_arcs(ranked: dict[str, str]) -> tuple[str, ...]:
    """The arcs that get a page of their own.

    Args:
        ranked: the arcs modules register at, as
            :py:func:`pysmi.corpus.index.anchor_index` returns them -- what a
            module registers with, rather than every OID it defines. The whole
            OID index is accepted and gives the object tree, which is not what
            a page inventory is.

    Returns:
        The arcs from the root down to each anchor, exclusive of the anchors
        themselves, in tree order. An arc that is both a prefix of one anchor
        and an anchor in its own right is left out: it is a module, and the
        module page answers for it.
    """
    above: set[str] = set()

    for anchor in ranked:
        # Proper prefixes only. The anchor itself is the module.
        above.update(prefixes(anchor)[:-1])

    return tuple(
        sorted(
            above - set(ranked),
            key=lambda arc: tuple(int(x) for x in arc.split(".")),
        )
    )


def resolve(
    oid: str,
    ranked: dict[str, str],
    descriptors: dict[str, tuple[str, str]] | None = None,
) -> Target | None:
    """Where an arc with no page of its own resolves to.

    A longest-prefix lookup, which is the same shape a trap receiver already
    runs against the published index -- so a site can do it in the browser
    from ``index-v2.csv`` rather than being handed a table of 85,644 entries.

    Args:
        oid: the arc asked for, dotted decimal.
        ranked: the OID index, as :py:func:`structural_arcs` takes it.
        descriptors: OID to ``(name, module)``, as
            :py:func:`pysmi.corpus.arcs.descriptors` returns it. Supplies the
            anchor to land on within the module page; without it a caller gets
            the module and no fragment.

    Returns:
        The target, or ``None`` where no anchor in the index is a prefix of
        *oid* -- an OID this corpus cannot answer for, which is a better
        answer than the nearest module.
    """
    named = descriptors or {}

    for arc in reversed(prefixes(oid)):
        module = ranked.get(arc)

        if module is None:
            continue

        if arc == oid:
            return Target(module, "", MODULE)

        descriptor = named.get(oid)

        return Target(module, descriptor[0] if descriptor else "", OBJECT)

    return None


def counts(ranked: dict[str, str], structural: tuple[str, ...]) -> dict[str, int]:
    """How much tree a site is about to render, for the build report.

    ``structural`` is the number of pages the OID tree costs. ``anchors`` is
    what it would cost again if a module's own arc were given a page beside
    the module's, and the two together are the arc inventory
    :py:mod:`pysmi.corpus.arcs` names.
    """
    tally = {
        "structural": len(structural),
        "anchors": len(ranked),
        "arcs": len(structural) + len(ranked),
    }

    logger.info(
        "OID tree: %d arcs get a page, %d resolve to a module instead",
        tally["structural"],
        tally["anchors"],
        extra=tally,
    )

    return tally
