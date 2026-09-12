#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Writing HTML without a template engine.

PySMI's runtime dependencies are ``ply`` and ``requests``. A site generator is
not a reason to add a third: everything here is a handful of stdlib string
operations, and a corpus of 5,500 modules renders in seconds without one.

What matters at corpus scale is that **nothing reaches a page unescaped**.
Every MIB in the corpus is third-party text -- a DESCRIPTION is whatever a
vendor typed, and ``CISCO-LWAPP-TC-MIB`` has one containing ``<``. The one
rule here is that :py:func:`text` is the only way a value becomes markup, and
the element builders call it for you.

See pysnmp/pysmi#276.
"""

import html
from collections.abc import Iterable, Mapping
from typing import Final

#: Written ahead of every page, so a browser reads it as HTML5.
DOCTYPE: Final = "<!doctype html>"

#: Elements that take no closing tag.
VOID: Final = frozenset({"br", "hr", "img", "link", "meta"})


def text(value: object) -> str:
    """One value, escaped for a text node or an attribute.

    Quotes included, so the same function serves both and a caller cannot pick
    the wrong one. ``None`` renders as the empty string rather than as
    ``"None"``: a fact the corpus does not hold is absent, not the word.
    """
    if value is None:
        return ""

    return html.escape(str(value), quote=True)


def attributes(pairs: "Mapping[str, object]") -> str:
    """Attributes as they are written inside a start tag.

    An attribute whose value is ``None`` or ``False`` is left out entirely,
    which is what lets a caller pass an optional one without a conditional.
    ``True`` renders as a bare attribute.

    A trailing underscore is dropped, so ``class_`` and ``for_`` reach the
    page as ``class`` and ``for`` -- both are Python keywords and neither can
    be written as a keyword argument. Underscores *inside* a name become
    hyphens, so ``data_oid`` is ``data-oid``.
    """
    written = []

    for name, value in pairs.items():
        if value is None or value is False:
            continue

        spelled = name.rstrip("_").replace("_", "-")

        if value is True:
            written.append(f" {spelled}")

        else:
            written.append(f' {spelled}="{text(value)}"')

    return "".join(written)


def tag(name: str, content: str = "", /, **pairs: object) -> str:
    """One element, its attributes escaped and its content taken as markup.

    *content* is markup rather than text, since an element holds other
    elements. Anything that is not already markup goes through :py:func:`text`
    first -- :py:func:`element` is the shorthand for that.
    """
    start = f"<{name}{attributes(pairs)}>"

    if name in VOID:
        return start

    return f"{start}{content}</{name}>"


def element(name: str, content: object = "", /, **pairs: object) -> str:
    """One element holding *content* as text rather than as markup."""
    return tag(name, text(content), **pairs)


def link(href: str, label: object, /, **pairs: object) -> str:
    """An anchor, with *label* as text."""
    return element("a", label, href=href, **pairs)


def join(parts: Iterable[str]) -> str:
    """Markup fragments, one per line, so the source is readable."""
    return "\n".join(x for x in parts if x)


def paragraphs(prose: str) -> str:
    """A MIB's prose as paragraphs, blank lines separating them.

    A DESCRIPTION arrives normalised -- ``JsonCodeGen`` collapses the
    publisher's line breaks unless ``keepTextsLayout`` is set -- but the blank
    lines between paragraphs survive, and they are the only structure the text
    has. Everything is escaped: this is vendor text, not markup.
    """
    if not prose:
        return ""

    return join(
        element("p", block.strip()) for block in prose.split("\n\n") if block.strip()
    )


def table(
    headings: "Iterable[object]",
    rows: "Iterable[Iterable[str]]",
    /,
    *,
    anchors: "Iterable[object]" = (),
    **pairs: object,
) -> str:
    """A table whose cells are already markup.

    Headings are text; cells are not, because a cell routinely holds a link or
    a code span. The caller escapes what it puts in one, which the builders
    above do.

    *anchors* gives each row an ``id``, in row order, so a row is something a
    URL can point at. Shorter than anchoring an element inside the row, and
    one anchor per row is what a deep link wants: a definition, not a cell.
    Rows past the end of it get none.

    Cells are joined with nothing between them. Every other builder here
    writes one fragment per line, because a person reads the source; a
    definition table is 764,000 rows over a corpus and a newline per cell is
    4 MB of them. The rows stay one per line, which is the granularity anyone
    reading the source is looking at anyway.
    """
    head = tag("tr", "".join(element("th", x, scope="col") for x in headings))
    keys = list(anchors)
    body = join(
        tag(
            "tr",
            "".join(tag("td", cell) for cell in row),
            id=keys[index] if index < len(keys) else None,
        )
        for index, row in enumerate(rows)
    )

    if not body:
        return ""

    return tag(
        "table",
        join((tag("thead", head), tag("tbody", body))),
        **pairs,
    )


def definitions(pairs: "Iterable[tuple[object, str]]", /, **attrs: object) -> str:
    """A description list. Terms are text, values are markup.

    A pair whose value is empty is left out: the corpus not holding a fact is
    different from it holding an empty one, and a blank row says the second.
    """
    written = join(
        join((element("dt", term), tag("dd", value))) for term, value in pairs if value
    )

    return tag("dl", written, **attrs) if written else ""
