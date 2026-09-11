#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Splitting a long list page into buckets whose URL is the range they cover.

A site rendering a corpus has lists too long for one page: every module it
holds, every module one registrant published, the children of a wide OID node.
Splitting them is not the question. What the pieces are *called* is.

Why not first letters
---------------------

A to Z is the obvious index and it fails on MIB names, which are dominated by
vendor prefixes rather than spread across the alphabet. Measured over
pysnmp/mibs' corpus:

======================================  =======  ==================
list                                    buckets  largest
======================================  =======  ==================
all 5,510 modules, by first letter      25       ``C`` at 1,708
Cisco's 1,353 modules, by first letter  7        ``C`` at 1,280
Cisco's, by first seven characters      38       ``CISCO-I`` at 166
======================================  =======  ==================

Inside a registrant essentially every name shares a prefix: 1,224 of Cisco's
1,353 modules begin ``CISCO-``. No fixed prefix length gives even buckets, and
the length that would work differs between the global list and one registrant.

Why not page numbers
--------------------

``page/4/`` is stable only while the list is. Adding one module shifts the
contents of every later page, so every already-crawled URL past the insertion
point serves different content and reports a fresh ``lastmod``. A corpus that
means to be crawled cannot afford that on every build. A range key disturbs
only the bucket the new entry lands in.

What this does instead
----------------------

Partition the sorted list into equal-count runs of the page size, and label
each run with the shortest prefix that distinguishes its first entry from the
previous run's last -- and likewise its last entry against the next run's
first. The label length falls out of the local density, so dense regions get
long labels and sparse ones get two characters:

.. code-block:: text

   AT..CISCO-DIAMETER-SG-C            200
   CISCO-DIAMETER-SG-M..CISCO-HC      200
   CISCO-HE..CISCO-LICENSE-MG         200
   CISCO-LICENSE-MI..CISCO-PRI        200
   CISCO-PRO..CISCO-TM                200
   CISCO-TN..CISCO-WDS-IDS-C          200
   CISCO-WDS-IDS-M..RP                153

That is Cisco's 1,353 modules at 200 per page. The whole corpus at 500 gives
twelve buckets, ``A1..BASIS-R`` through ``ZYXEL-ES-R..ZYXEL-Z``.

The separator is ASCII
----------------------

:py:data:`SEPARATOR` is ``..`` rather than an en dash. An en dash
percent-encodes to ``%E2%80%93``, which works and is a needless hazard in a
string that crawlers, server logs, shell history, spreadsheets and copy-paste
all handle. A plain ``-`` will not do either: module names are full of hyphens
and ``CISCO-LR-CISCO-PTO`` is ambiguous. ``..`` cannot occur in a module name,
which :rfc:`2578` defines as letters, digits and hyphens, nor in an arc number.

:py:func:`parse_key` reads a key back, and ``tests/test_corpus_buckets.py``
holds the two to a round trip rather than to a convention, because the
generator writes these and the client-side navigation parses them.

Sorted how
----------

Case-sensitive byte order, which is what :py:func:`sorted` gives and what the
labels above were computed with. Module names are mixed case, and a display
sort that differed from the sort the labels imply would put entries in buckets
whose range excludes them.

An OID node's children sort numerically instead, which *order* is for: there
``10`` follows ``9``. Labels are then the numbers in full, since a shortest
distinguishing prefix of a decimal number is not a number.

See pysnmp/pysmi#287. Consumed by the site generator in pysnmp/pysmi#276 and
parsed back by the browser-side navigation in pysnmp/pysmi#293.
"""

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any, Final, NamedTuple

logger = logging.getLogger(__name__)

#: What separates the two halves of a range key. ASCII, and impossible in a
#: module name or an arc number, so a key parses back without escaping.
SEPARATOR: Final = ".."

#: The shortest label, in characters. One character would do to distinguish
#: most boundaries and reads as an initial rather than as a range: ``A..B``
#: says less about what is in the bucket than ``A1..BASIS-R`` does.
MINIMUM: Final = 2

#: Entries per bucket where a caller names none. A corpus of 200 modules and
#: one of 50,000 want different numbers, which is why the site generator takes
#: this from its manifest rather than from here.
SIZE: Final = 500

#: How many characters of each half :py:func:`abbreviate` renders. The key
#: strip lists every bucket on every bucket page, and
#: ``CISCO-LICENSE-MI..CISCO-PRI`` is 27 characters. The URL keeps the whole
#: label; only the rendering is clipped.
RENDERED: Final = 12

#: What :py:func:`abbreviate` puts where it clipped.
ELLIPSIS: Final = "…"


class Bucket(NamedTuple):
    """One page of a bucketed list, and the range of entries it holds."""

    #: The URL segment -- ``low``, the separator, then ``high``. ``""`` for a
    #: list short enough not to be bucketed, which keeps its unbucketed URL.
    key: str

    #: The low end of the range, as a label. ``""`` when unbucketed.
    low: str

    #: The high end. ``""`` when unbucketed.
    high: str

    #: The entries this bucket holds, in the order they are rendered.
    entries: tuple[str, ...]


def _identity(text: str) -> Any:
    """Byte order, which is the default ordering."""
    return text


def _common(left: str, right: str) -> int:
    """How many leading characters *left* and *right* share."""
    shared = 0

    for one, other in zip(left, right):
        if one != other:
            break

        shared += 1

    return shared


def _label(entry: str, neighbour: str, minimum: int, within: str = "") -> str:
    """The shortest prefix of *entry* that *neighbour* does not also have.

    *neighbour* is ``""`` at the outer edges of the list, where there is
    nothing to distinguish from and the minimum decides the length.

    *within* is the other end of *entry*'s own run, given for the high end of
    a range and not the low. Without it a run whose two ends are far apart
    alphabetically, sitting next to a neighbour that is further still, gets a
    high label shorter than its own low -- ``CISCO-E..CI``, which sorts
    backwards and tells a reader nothing. Distinguishing the last entry from
    the first as well makes the label say where the run ends:
    ``CISCO-E..CISCO-ENTITY-F``.
    """
    length = max(minimum, _common(entry, neighbour) + 1)

    if within:
        length = max(length, _common(entry, within) + 1)

    return entry[:length]


def buckets(
    entries: Iterable[str],
    size: int = SIZE,
    *,
    order: "Callable[[str], Any] | None" = None,
    shorten: "bool | None" = None,
    minimum: int = MINIMUM,
) -> tuple[Bucket, ...]:
    """Split a list into buckets keyed by the range each covers.

    Args:
        entries: what the list holds. Sorted here rather than taken as sorted,
            so that the labels and the contents cannot disagree. Duplicates
            are dropped: a list of pages holds each entry once, and two runs
            sharing a boundary value would give two buckets one key.
        size: entries per bucket. A list of *size* or fewer comes back as one
            bucket with no key, which is a list that keeps its unbucketed URL
            and renders no key strip.
        order: a sort key, for a list that is not in byte order -- an OID
            node's children sort numerically, where ``10`` follows ``9``.
            Defaults to byte order.
        shorten: whether labels are shortest distinguishing prefixes.
            Defaults to true for byte order and false otherwise, since the
            shortest distinguishing prefix of a decimal number is not a
            number. A caller wanting whole labels in byte order says so.
        minimum: the shortest label. See :py:data:`MINIMUM`.

    Returns:
        The buckets, in list order. Their keys are unique and strictly
        increasing, and every entry is in exactly one of them.

    Raises:
        ValueError: *size* is not positive. A zero page size is a division by
            zero dressed as a setting.
    """
    if size < 1:
        raise ValueError(f"a bucket holds at least one entry, not {size}")

    ordered = sorted(set(entries), key=order or _identity)

    if not ordered:
        return ()

    if len(ordered) <= size:
        return (Bucket("", "", "", tuple(ordered)),)

    clipped = (order is None) if shorten is None else shorten
    runs = [ordered[at : at + size] for at in range(0, len(ordered), size)]
    found = []

    for index, run in enumerate(runs):
        before = runs[index - 1][-1] if index else ""
        after = runs[index + 1][0] if index + 1 < len(runs) else ""

        if clipped:
            low = _label(run[0], before, minimum)
            high = _label(run[-1], after, minimum, run[0])

        else:
            low, high = run[0], run[-1]

        found.append(Bucket(f"{low}{SEPARATOR}{high}", low, high, tuple(run)))

    return tuple(found)


def parse_key(key: str) -> "tuple[str, str] | None":
    """Read a range key back into its two labels.

    The other half of what :py:func:`buckets` writes, and the reason the
    separator is what it is: the generator writes these and the browser parses
    them, so the two have to agree exactly.

    Args:
        key: a URL segment, as :py:attr:`Bucket.key` gives it.

    Returns:
        The low and high labels, or ``None`` where *key* is not a range key --
        an unbucketed list's empty key among them.
    """
    low, separator, high = key.partition(SEPARATOR)

    if not separator or not low or not high:
        return None

    return low, high


def locate(
    name: str,
    found: Sequence[Bucket],
    order: "Callable[[str], Any] | None" = None,
) -> "Bucket | None":
    """Which bucket an entry belongs to.

    The buckets partition the range and their keys ascend, so this is the last
    bucket whose low end does not exceed *name* -- which answers for an entry
    that was not in the list the buckets were built from, and is what a
    browser resolving a name to a page needs.

    Args:
        name: the entry to place.
        found: the buckets, as :py:func:`buckets` returns them.
        order: the ordering they were built with.

    Returns:
        The bucket, or ``None`` where *name* sorts before all of them. An
        unbucketed list's single bucket answers for everything.
    """
    rank = order or _identity
    answer = None

    for bucket in found:
        if not bucket.key:
            return bucket

        if rank(bucket.low) <= rank(name):
            answer = bucket

        else:
            break

    return answer


def successors(
    key: str,
    found: Sequence[Bucket],
    order: "Callable[[str], Any] | None" = None,
) -> tuple[Bucket, ...]:
    """The buckets that now cover what *key* used to.

    A bucket that outgrows the page size splits, and that renames a key. It is
    the one case where a range URL moves, and static hosting serves no
    redirects -- so the generator emits the retired key as a small page
    carrying a canonical link and a meta refresh to these.

    Args:
        key: a key from an earlier build.
        found: this build's buckets.
        order: the ordering they were built with.

    Returns:
        The buckets whose range overlaps *key*'s, contiguous and in list
        order. Empty where *key* is not a range key, or where nothing covers
        it any more.
    """
    bounds = parse_key(key)

    if bounds is None or not found:
        return ()

    if not found[0].key:
        return (found[0],)

    low, high = bounds
    rank = order or _identity
    first = None
    last = None

    for index, bucket in enumerate(found):
        if rank(bucket.low) <= rank(low):
            first = index

        if rank(bucket.low) <= rank(high):
            last = index

    if last is None:
        return ()

    return tuple(found[(0 if first is None else first) : last + 1])


def retired(
    before: Iterable[str],
    found: Sequence[Bucket],
    order: "Callable[[str], Any] | None" = None,
) -> dict[str, tuple[str, ...]]:
    """The keys an earlier build had that this one does not, and what replaced them.

    Args:
        before: the keys the previous build wrote.
        found: this build's buckets.
        order: the ordering they were built with.

    Returns:
        Per retired key, the keys that now cover its range -- empty where
        nothing does, which is still worth knowing: the URL is crawled and
        has to answer something.
    """
    current = {bucket.key for bucket in found}
    gone = {}

    for key in before:
        if key in current:
            continue

        gone[key] = tuple(x.key for x in successors(key, found, order))

    if gone:
        logger.info(
            "bucket keys: %d retired, %d of them with no successor",
            len(gone),
            sum(1 for x in gone.values() if not x),
            extra={"retired": sorted(gone)},
        )

    return gone


def _clip(text: str, width: int) -> str:
    """*text*, no longer than *width*, marked where it was cut."""
    if len(text) <= width:
        return text

    return text[: max(1, width - 1)] + ELLIPSIS


def abbreviate(bucket: Bucket, width: int = RENDERED) -> str:
    """The key as the strip renders it, clipped.

    Every bucket is listed on every bucket page, so any bucket is one hop from
    any other and crawl depth does not grow with the corpus. That only works
    if the strip fits, and a label runs to 27 characters. The URL keeps the
    whole label; this is the rendering.

    Args:
        bucket: the bucket to render.
        width: characters per half. See :py:data:`RENDERED`.

    Returns:
        The clipped key, or ``""`` for an unbucketed list -- which renders no
        key strip at all.
    """
    if not bucket.key:
        return ""

    return f"{_clip(bucket.low, width)}{SEPARATOR}{_clip(bucket.high, width)}"


def counts(found: Sequence[Bucket]) -> dict[str, int]:
    """How the list came out, for a build report."""
    sizes = [len(x.entries) for x in found]

    return {
        "buckets": len(found),
        "entries": sum(sizes),
        "largest": max(sizes, default=0),
        "smallest": min(sizes, default=0),
    }
