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


def _figure(count: int, scale: str) -> str:
    """*count* where a report supplied one, and *scale* where none did.

    A phrase rather than a zero: a sentence reading "a corpus of 0 modules" is
    false, and one reading "a corpus of thousands of modules" is true of every
    corpus the sentence is about.
    """
    return _grouped(count) if count else scale


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
        "corpus_modules": _figure(int(report.get("modules") or 0), "thousands of"),
        "corpus_nodes": _figure(
            int(nodes.get("defined") or 0), "hundreds of thousands of"
        ),
        "corpus_oids": _figure(int(nodes.get("distinct") or 0), "tens of thousands of"),
        "corpus_arcs": _figure(int(arcs.get("arcs") or 0), "tens of thousands of"),
        "corpus_registrants": _figure(int(entity.get("arcs") or 0), "a few hundred"),
        "corpus_pages": _figure(int(site.get("pages") or 0), "thousands of"),
        "corpus_rows": _figure(int(db.get("node") or 0), "hundreds of thousands of"),
    }


#: Numbers a page may state outright, because they are not this project's to
#: change: a platform's limits, a protocol's, a wire format's.
ALLOWED: Final = frozenset(
    {
        # A GitHub issue body's character limit, which is what makes a MIB
        # too big to paste. See mibcontribute.rst.
        "65,536",
    }
)

#: Pages a generator writes, where a count is the generator's output rather
#: than somebody's prose. ``bundled-mibs.rst`` comes from
#: ``scripts/update_bundled_mibs.py`` and the changelogs from
#: semantic-release.
GENERATED: Final = frozenset(
    {"bundled-mibs.rst", "changelog.md", "changelog-history.rst"}
)


def stated() -> "list[tuple[str, int, str]]":
    """Comma-grouped numbers written into a page by hand.

    A count typed into prose is wrong the next time the thing it counts
    changes, and keeping it right is a diff to review on every change after
    that -- which is what :py:func:`figures` exists to prevent, and this is
    the check that it stays prevented. Generated pages are skipped: a count
    there is what the generator measured.

    Returns:
        ``(path, line number, the line)`` per finding, in file order.
    """
    where = pathlib.Path(__file__).resolve().parent
    grouped = re.compile(r"\b\d{1,3}(?:,\d{3})+\b")
    found = []

    for page in sorted(where.glob("*.rst")) + sorted(where.glob("*.md")):
        if page.name in GENERATED:
            continue

        literal = False

        with open(page, encoding="utf-8") as fileObj:
            for number, line in enumerate(fileObj, start=1):
                # A literal block is a transcript -- a sample report, a
                # command's output -- and states what it stated.
                if literal and (not line.strip() or line.startswith((" ", "\t"))):
                    continue

                literal = line.rstrip().endswith("::")

                if [x for x in grouped.findall(line) if x not in ALLOWED]:
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
