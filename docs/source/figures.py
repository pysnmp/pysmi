#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Figures the documentation states, supplied rather than typed.

A count written into prose is wrong the next time the thing it counts changes,
and keeping it right is a diff to review on every change after that. The pages
here name a figure instead -- ``{{ bundled }}`` in Markdown, ``|bundled|`` in
reStructuredText -- and this supplies it.

Two kinds of figure, and they come from different places:

**What pysmi itself holds** is in this checkout, so it is always exact: the
modules the wheel bundles, the ones held back, the manifest's own count.

**What a corpus holds** is a property of whatever corpus somebody built, which
pysmi has no copy of. ``mibcorpus --emit=report`` writes those counts, and a
documentation build given one through :py:data:`REPORT_ENV` states them.
Without one -- which is what pysmi's own CI does, since a build here fetches
nothing and compiles no vendor's MIBs -- the figure renders as a phrase naming
the scale. The prose is written so either reads as a sentence.

See ``docs/source/conf.py``, which is what loads this.
"""

import argparse
import json
import os
import pathlib
import re
from typing import Any, Final

#: The repository root, from this file's own location.
ROOT: Final = pathlib.Path(__file__).resolve().parent.parent.parent

#: A ``report.json`` to read the corpus figures from, named by a build that
#: has one. ``mibcorpus --emit=report`` writes it.
REPORT_ENV: Final = "PYSMI_CORPUS_REPORT"

#: Where the bundled ASN.1 lives, and where the held tier lived. The second is
#: empty in a current wheel -- pysnmp/pysmi#323 promoted all of it -- and the
#: figure is read rather than asserted, so the page is right either way.
BUNDLE: Final = "pysmi/mibs/asn1"
HELD: Final = "pysmi/mibs/future"


def read_report() -> "dict[str, Any]":
    """The corpus report a build was given, or ``{}``.

    A report that will not parse counts as none: the figures then fall back
    like any other build without one, rather than failing a documentation
    build over a truncated artifact.
    """
    named = os.environ.get(REPORT_ENV)

    if not named:
        return {}

    try:
        with open(named, encoding="utf-8") as fileObj:
            found = json.load(fileObj)

    except (OSError, ValueError):
        return {}

    return found if isinstance(found, dict) else {}


#: What is in a MIB directory and is not a module. The bundle is a Python
#: package as well as a tree of ASN.1, so it carries an ``__init__.py``; the
#: held tier carries a README saying what it is for.
NOT_A_MODULE: Final = frozenset({".py", ".pyc", ".md", ".rst", ".txt", ".json"})


def _modules(where: pathlib.Path) -> int:
    """Modules in a MIB directory, which holds one file per module.

    The bundle's own packaging files do not count: ``pysmi/mibs/asn1`` is an
    importable package, so the module count is the files that are MIBs.
    """
    try:
        return sum(
            1 for x in where.iterdir() if x.is_file() and x.suffix not in NOT_A_MODULE
        )

    except OSError:
        return 0


def _grouped(count: int) -> str:
    """A count as prose states it, grouped so the magnitude is readable."""
    return f"{count:,}"


def _count(block: "dict[str, Any]", key: str) -> "int | None":
    """One count out of a report block, or ``None`` where it has none.

    ``None`` rather than zero, because a build that counted none of something
    and a build that did not count it are different answers: a corpus with no
    registrant pages reports ``0`` and a publication that emitted no entity
    index reports nothing at all. Only the second wants a fallback.

    A field that is present and is not a number is absent for this purpose.
    ``report.json`` is an artifact read off disk, and a documentation build
    that raised ``ValueError`` partway through substituting its figures would
    fail over a field it could have ignored.
    """
    if not isinstance(block, dict) or key not in block:
        return None

    found = block[key]

    if isinstance(found, bool) or not isinstance(found, (int, float, str)):
        return None

    try:
        return int(found)

    except (TypeError, ValueError):
        return None


def _figure(count: "int | None", scale: str) -> str:
    """*count* where a report supplied one, and *scale* where none did.

    A phrase where the figure is missing, because "a corpus of 0 modules" is
    false and "a corpus of thousands of modules" is true of every corpus the
    sentence is about. A supplied zero is a measurement and is rendered as
    ``0``: a build that resolved no arcs at all should say so.
    """
    return scale if count is None else _grouped(count)


def figures() -> "dict[str, str]":
    """Every figure the documentation names, ready to substitute.

    Returns:
        Figure name to the text to render. A name is always present, so a page
        naming one cannot fail to build.
    """
    report = read_report()
    site = report.get("site") or {}
    nodes = report.get("nodes") or {}
    arcs = report.get("arcs") or {}
    entity = report.get("entity") or {}
    db = report.get("db") or {}

    return {
        # pysmi's own bundle, which is in this checkout.
        "bundled": _grouped(_modules(ROOT / BUNDLE)),
        "held": _grouped(_modules(ROOT / HELD)),
        # A corpus somebody built, which is not.
        "corpus_modules": _figure(_count(report, "modules"), "thousands of"),
        "corpus_nodes": _figure(_count(nodes, "defined"), "hundreds of thousands of"),
        "corpus_oids": _figure(_count(nodes, "distinct"), "tens of thousands of"),
        "corpus_arcs": _figure(_count(arcs, "arcs"), "tens of thousands of"),
        "corpus_registrants": _figure(_count(entity, "arcs"), "a few hundred"),
        "corpus_pages": _figure(_count(site, "pages"), "thousands of"),
        "corpus_rows": _figure(_count(db, "node"), "hundreds of thousands of"),
    }


#: Numbers a page may state outright, because they are not this project's to
#: change: a platform's limits, a protocol's, a wire format's.
ALLOWED: Final = frozenset(
    {
        # A GitHub issue body's character limit, which is what makes a MIB
        # too big to paste. See mibcontribute.rst.
        "65,536",
        # The sitemap protocol's own ceilings, per file. See mibcorpus.rst.
        "50,000",
        "50",
        # GitHub Pages' own limits: a site, and a file in one.
        "1",
        "100",
        # Not counts of anything this project measures: the markup a table
        # cell used to carry, the width of the longest bucket label, and a
        # year -- "the 2017 files" are the ones dated 2017.
        "61",
        "27",
        "2017",
    }
)

#: Units that make a number a count of something this project measures. A
#: figure followed by one of these is a corpus measurement whatever its
#: magnitude, which is the half :py:data:`GROUPED` cannot see: "210 modules"
#: has no comma in it and went stale for two releases.
UNITS: Final = (
    r"modules?|nodes?|arcs?|pages?|files?|rows?|definitions?|registrants?"
    r"|objects?|notifications?|symbols?|descriptions?|dependents?|entries"
    r"|URLs?|MB|MiB|GB|KB"
)

#: A comma-grouped number, which is a count whatever follows it. Nothing this
#: project states in the thousands is a constant.
GROUPED: Final = r"\d{1,3}(?:,\d{3})+"

#: How many words may sit between a number and its unit. "210 bundled ASN.1
#: modules" is the shape that went stale through two releases, so nothing
#: short of two catches the cases worth catching; past two the matches stop
#: being counts of anything.
GAP: Final = 2

#: What :py:func:`stated` looks for. The lookbehind keeps ``ASN.1 modules``
#: from reading as "1 modules", which is the false positive that matters here:
#: the pages say it constantly.
COUNTS: Final = re.compile(
    rf"(?<![\w.])({GROUPED}|\d[\d,]*(?:\s+[\w.`-]+){{0,{GAP}}}\s+(?:{UNITS}))\b"
)

#: A reStructuredText directive, which opens an indented block the way a
#: literal one does. ``.. code-block:: text`` does not end in ``::``, so the
#: end-of-line test alone leaves every sample transcript in the check.
DIRECTIVE: Final = re.compile(r"^\s*\.\.\s+[\w-]+::")

#: Pages a generator writes, where a count is the generator's output rather
#: than somebody's prose. ``bundled-mibs.rst`` comes from
#: ``scripts/update_bundled_mibs.py`` and the changelogs from
#: semantic-release.
GENERATED: Final = frozenset(
    {"bundled-mibs.rst", "changelog.md", "changelog-history.rst"}
)


def _number(match: str) -> str:
    """The digits out of a match, for comparing against :py:data:`ALLOWED`."""
    return match.split(maxsplit=1)[0] if " " in match else match


def stated() -> "list[tuple[str, int, str]]":
    """Counts written into a page by hand.

    A count typed into prose is wrong the next time the thing it counts
    changes, and keeping it right is a diff to review on every change after
    that -- which is what :py:func:`figures` exists to prevent, and this is
    the check that it stays prevented.

    Two shapes count, per :py:data:`COUNTS`: anything comma-grouped, and any
    number followed by a unit this project measures. The second is what a
    grouped-only check misses, and it misses the ones that matter -- the
    pages claimed "210 bundled ASN.1 modules" through two releases that
    changed the number.

    Generated pages are skipped, and so are literal blocks: a sample report or
    a command's transcript states what it stated when it ran.

    Returns:
        ``(path, line number, the line)`` per finding, in file order.
    """
    where = pathlib.Path(__file__).resolve().parent
    found = []

    for page in sorted(where.glob("*.rst")) + sorted(where.glob("*.md")):
        if page.name in GENERATED:
            continue

        literal = False

        with open(page, encoding="utf-8") as fileObj:
            for number, line in enumerate(fileObj, start=1):
                indented = line.startswith((" ", "\t"))

                # A blank line neither opens nor closes a block, and an
                # indented line inside one is the transcript. Anything flush
                # left ends it.
                if not line.strip():
                    continue

                if literal and indented:
                    continue

                literal = bool(DIRECTIVE.match(line)) or line.rstrip().endswith("::")

                if [x for x in COUNTS.findall(line) if _number(x) not in ALLOWED]:
                    found.append((page.name, number, line.rstrip()))

    return found


def main(argv: "list[str] | None" = None) -> int:
    """Print the figures, or check that no page states a count outright."""
    parsed = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parsed.add_argument(
        "--check",
        action="store_true",
        help="fail on a count written into a page by hand",
    )
    options = parsed.parse_args(argv)

    if options.check:
        written = stated()

        for name, number, line in written:
            print(f"docs/source/{name}:{number}: {line.strip()}")

        if written:
            print(
                f"\n{len(written)} line(s) state a count outright. Name a figure "
                f"from {pathlib.Path(__file__).name} instead -- |bundled| in "
                f"reStructuredText, {{{{ bundled }}}} in Markdown -- so the page "
                f"is right after the next change. A limit that is not this "
                f"project's to change goes on ALLOWED."
            )

        return 1 if written else 0

    found = figures()
    width = max(len(x) for x in found)

    for name in sorted(found):
        print(f"{name:<{width}}  {found[name]}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
