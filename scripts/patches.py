#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The repairs pysmi makes to its own bundle, applied while a distribution builds.

The engine moved into the package as :py:mod:`pysmi.patches`, because
:py:mod:`pysmi.scripts.mibpatch` gives the same reading and applying to anyone
with MIBs of their own. What stays here is the one thing that is pysmi's own
business: :py:func:`bundled_patches`, the set of diffs in ``scripts/mib-patches`` that
repair the modules in ``pysmi/mibs/asn1``.

Those diffs do not ship. The repository holds each module as its publisher
printed it, so that ``git diff`` on a bundle refresh is a diff against the
publisher and the repairs pysmi makes are a diff of their own, reviewable on
their own terms. The *distribution* holds the repaired text: ``hatch_build.py``
applies these diffs as the wheel is built, and both the ASN.1 the wheel carries
and the pysnmp modules rendered from it are the repaired form. So a consumer
gets working MIBs without carrying a patch set, and a fork wanting different
repairs edits this directory and rebuilds. The distribution is the opinion.
"""

from pathlib import Path

from pysmi.error import PySmiPatchError
from pysmi.patches import (
    ALREADY_APPLIED,
    APPLIED,
    CONTEXT_LINES,
    NOT_APPLICABLE,
    UNPATCHED,
    Hunk,
    PatchSet,
    apply_patch,
    make_patch,
    parse_patch,
)

__all__ = [
    "ALREADY_APPLIED",
    "APPLIED",
    "CONTEXT_LINES",
    "NOT_APPLICABLE",
    "PATCHES",
    "UNPATCHED",
    "Hunk",
    "PatchSet",
    "PySmiPatchError",
    "apply_patch",
    "bundled_patches",
    "make_patch",
    "parse_patch",
]

#: Where the diffs live, beside this module.
PATCHES = Path(__file__).resolve().parent / "mib-patches"

_BUNDLED: PatchSet | None = None


def bundled_patches() -> PatchSet:
    """The repairs pysmi makes to its own bundle, from ``scripts/mib-patches``.

    Read once and shared, since the set does not change while the build runs
    and everything that wants it wants the same one.
    """
    global _BUNDLED

    if _BUNDLED is None:
        _BUNDLED = PatchSet.from_directory(PATCHES)

    return _BUNDLED
