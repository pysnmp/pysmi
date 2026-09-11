#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The catalogue of defects a MIB patch repairs.

A patch carries a diff. The diff carries the correction and does not name the
defect -- and the defect is what decides whether the patch should still exist,
because a repair to text the publisher has since fixed should go, and a local
preference dressed as a repair should never have been written.

Rather than repeat the explanation in every patch file, each defect gets an
identifier and one entry here, and a patch references the identifier:

.. code-block:: diff

    Defect: SMI-UNPUBLISHED-MODULE https://pysnmp.github.io/pysmi/stable/mib-defects.html#smi-unpublished-module

    --- a/SMUX-MIB
    +++ b/SMUX-MIB

Two lines, one of them a link. :doc:`/mib-defects` is that catalogue rendered,
and ``tests/test_defects.py`` holds the page and this module to the same set of
identifiers, so a defect cannot be referenced by a patch and missing from the
page.

The identifiers here are pysmi's, and name defects against the SMI itself --
:rfc:`2578`, :rfc:`2579` and :rfc:`2580` -- rather than against any particular
collection of MIBs. A downstream corpus with repairs of its own defines its own
identifiers and its own page, and :py:func:`~pysmi.patches.split_patch` reads
those exactly the same way: an identifier pysmi does not know is still an
identifier, and the URL beside it still resolves.
"""

from typing import NamedTuple

#: The published catalogue, which is :doc:`/mib-defects` on the documentation
#: site. ``stable`` rather than a version, so a patch file written today still
#: points somewhere in five years.
DOCS = "https://pysnmp.github.io/pysmi/stable/mib-defects.html"


class DefectClass(NamedTuple):
    """One kind of defect, and what makes it one.

    Not to be confused with :py:class:`pysmi.patchgen.Defect`, which is what
    one module in a scanned tree turned out to need.
    """

    #: The identifier a patch references, and never a changing one -- renaming
    #: one breaks every patch file that names it, in trees this project does
    #: not see.
    id: str

    #: What is wrong, in one line, as a report prints it.
    summary: str

    #: The rule the defective text breaks, as an RFC and a section.
    reference: str


class DefectRef(NamedTuple):
    """A patch's reference to a defect: the identifier, and where to read it."""

    #: The identifier. In :py:data:`CATALOGUE` when the defect is one of
    #: pysmi's; anything at all when the patch came from another tree.
    id: str

    #: Where the identifier is documented, or ``""`` when the patch gave no
    #: URL. Written into the patch rather than derived, so that a patch stays
    #: readable on its own and a downstream catalogue needs no configuring.
    url: str


def _catalogue(*entries: DefectClass) -> dict[str, DefectClass]:
    """Key the entries by identifier, refusing a duplicate."""
    known: dict[str, DefectClass] = {}

    for entry in entries:
        if entry.id in known:
            raise ValueError(f"duplicate defect identifier: {entry.id}")

        known[entry.id] = entry

    return known


#: Every defect pysmi names, by identifier. Kept in the order the entries are
#: written so that a page rendered from it reads in a deliberate order rather
#: than alphabetically.
CATALOGUE: dict[str, DefectClass] = _catalogue(
    DefectClass(
        "SMI-MISSING-IMPORT",
        "uses a symbol without naming it in IMPORTS",
        "RFC 2578 section 3.2",
    ),
    DefectClass(
        "SMI-UNPUBLISHED-MODULE",
        "imports FROM a module name no publisher ships",
        "RFC 2578 section 3.2",
    ),
    DefectClass(
        "SMI-SUPERSEDED-MODULE",
        "imports FROM a module that was renamed, under a name that now belongs "
        "to a different module",
        "RFC 2578 section 3.2",
    ),
    DefectClass(
        "SMI-UNDEFINED-NAME",
        "references a descriptor the module does not define",
        "RFC 2578 section 3.1",
    ),
    DefectClass(
        "SMI-CLAUSE-OUT-OF-ORDER",
        "defines something before the module's MODULE-IDENTITY",
        "RFC 2578 section 3",
    ),
    DefectClass(
        "SMI-INVALID-DATE",
        "gives a date in neither of the two forms the SMI allows",
        "RFC 2578 section 2",
    ),
    DefectClass(
        "SMI-INVALID-ACCESS",
        "gives an access value the SMI does not define",
        "RFC 2578 section 7.3, RFC 2580 section 4.1",
    ),
    DefectClass(
        "SMI-MISDECLARED-ACCESS",
        "gives an access the object's own use contradicts",
        "RFC 2578 section 7.3",
    ),
    DefectClass(
        "SMI-RANGE-OUTSIDE-TYPE",
        "bounds a value outside the type it is declared as",
        "RFC 2578 section 7.1.1",
    ),
    DefectClass(
        "SMI-DISPLAY-HINT-MISMATCH",
        "gives a DISPLAY-HINT format the SYNTAX does not allow",
        "RFC 2579 section 3.1",
    ),
    DefectClass(
        "SMI-UNMARKED-COMMENT",
        "continues a comment onto a line that does not start one",
        "RFC 2578 section 3.1",
    ),
)


def anchor(defect_id: str) -> str:
    """The fragment :doc:`/mib-defects` gives an identifier's entry."""
    return defect_id.lower()


def url(defect_id: str) -> str:
    """Where an identifier is documented.

    Args:
        defect_id (str): the identifier, whether or not pysmi knows it. An
            unknown one gets a URL that does not resolve rather than an error,
            because this is a link and being wrong about one is not fatal.

    Returns:
        The published catalogue, at the identifier's entry.
    """
    return f"{DOCS}#{anchor(defect_id)}"


def ref(defect_id: str) -> DefectRef:
    """A patch's reference to one of pysmi's defects.

    Args:
        defect_id (str): the identifier, which must be in :py:data:`CATALOGUE`.

    Returns:
        The reference, with the URL filled in.

    Raises:
        KeyError: no such identifier. A patch naming a defect nothing
            documents is worse than one naming none, so this refuses rather
            than writing a link to an empty page.
    """
    return DefectRef(CATALOGUE[defect_id].id, url(defect_id))


def summary(defect_id: str) -> str:
    """What a defect is, in one line, or ``""`` when pysmi does not know it."""
    known = CATALOGUE.get(defect_id)

    return known.summary if known else ""
