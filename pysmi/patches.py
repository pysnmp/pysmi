#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Reading, applying and writing the diffs that repair a broken MIB.

Some published MIBs do not compile. ``SMUX-MIB`` imports ``OBJECT-TYPE`` from a
module called ``RFC1212``, and no such module exists -- it is ``RFC-1212``.
``HPR-MIB`` is published with ``LAST-UPDATED "970514000000Z"``, which is
thirteen characters and so reads as the wide form, year 9705 of month 14. These
are defects in the published text, and the fix for each is a small diff against
it.

A diff is the durable, reviewable form of a repair. It names the defect, it
carries the correction, and it lives in version control where it can be read
before anything runs -- unlike a repair made in memory as a module is compiled,
which exists only for the length of the run that made it. :py:mod:`pysmi.scripts.mibpatch`
writes them, this module reads and applies them, and ``hatch_build.py`` uses it
to repair pysmi's own bundle as a distribution is built.

Nothing here runs while a MIB is compiled. pysmi reads what a source actually
holds and does not patch anything on the way past; patching a tree is a thing
done to it beforehand, deliberately, with the diffs to show for it.

Two things follow from applying a diff rather than fuzzing text:

* The copy a patch is cut against is the text as published, so a patch that no
  longer applies means the publisher moved. That is a thing to look at rather
  than to paper over: matching is exact, and callers fail loudly on it.
* The same diff is nevertheless offered to text that already carries it. That
  is detected by trying the patch backwards, the dry run ``patch -R`` does, and
  reported as :py:data:`ALREADY_APPLIED`.

A diff carries the correction. It does not name the defect, and the defect is
what decides whether the repair should still exist -- a repair to text the
publisher has since fixed should go, and a local preference dressed as a repair
should never have been there. So a patch file opens with a header naming the
defect it repairs, one ``Defect:`` line per defect: an identifier, and where
that identifier is documented.

.. code-block:: diff

    Defect: SMI-UNPUBLISHED-MODULE https://pysnmp.github.io/pysmi/stable/mib-defects.html#smi-unpublished-module

    --- a/SMUX-MIB
    +++ b/SMUX-MIB
    @@ -4,7 +4,7 @@

The explanation lives once, in :py:mod:`pysmi.defects` and on the page it is
rendered to, rather than being written out again in every patch that repairs
the same kind of thing. An identifier pysmi does not know is read the same way:
a downstream corpus names its own defects and points at its own page.

This is a convention over the format rather than a change to it.
:py:func:`parse_patch` ignores everything before the first ``@@``, and so does
GNU ``patch``, so a header is readable by every tool that reads a diff and
every patch written without one stays valid. :py:func:`split_patch` reads it,
:py:meth:`PatchSet.defects_for` looks it up, and :py:func:`make_patch` writes
it.
"""

import difflib
import logging
import re
from collections.abc import Iterable
from pathlib import Path
from typing import NamedTuple

from pysmi.defects import DefectRef
from pysmi.error import PySmiPatchError

logger = logging.getLogger(__name__)

#: How many lines of context :py:func:`make_patch` puts around a change. Three
#: is what ``diff -u`` defaults to and what the patches in ``scripts/mib-patches``
#: were cut with, so a generated patch and a hand-written one read alike.
CONTEXT_LINES = 3


#: The text carried the patch already -- pysmi's own bundled copies do.
ALREADY_APPLIED = "already-applied"

#: The patch was applied to this text just now.
APPLIED = "applied"

#: There is a patch for this module, but it was cut against different text.
NOT_APPLICABLE = "not-applicable"

#: No patch is known for this module.
UNPATCHED = ""

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")

#: The one field a patch header defines, repeatable: an identifier and,
#: optionally, the URL that documents it. Everything else in the block is prose.
DEFECT = re.compile(r"^Defect:[ \t]*(\S+)(?:[ \t]+(\S+))?[ \t]*$")

#: The first line of the diff proper, so the header block is everything above
#: it. ``diff`` and ``Index:`` are not written here, but a patch cut by another
#: tool carries them and they are not part of anybody's reason.
DIFF_START = re.compile(r"^(?:--- |\+\+\+ |@@ |diff |Index: )")


class Hunk(NamedTuple):
    """One ``@@`` block of a unified diff.

    *before* and *after* are the hunk's two sides with their marks dropped, so
    applying it forwards means finding *before* at *old_start* and putting
    *after* in its place, and applying it backwards means the reverse. Holding
    both sides is what lets the same hunk be tried either way.
    """

    #: Line the hunk starts at in the pre-image, counting from zero.
    old_start: int

    #: Line the hunk starts at in the post-image, counting from zero.
    new_start: int

    #: The pre-image lines this hunk covers -- its context and removals.
    before: tuple[str, ...]

    #: The post-image lines this hunk produces -- its context and additions.
    after: tuple[str, ...]


class PatchHeader(NamedTuple):
    """What a patch file says about the repair, above the diff.

    Empty in both fields for a patch written without a header, which every
    patch was before the convention existed.
    """

    #: The defects the patch repairs, in the order the file names them. A
    #: patch may repair more than one -- ``DNS-SERVER-MIB`` repairs three.
    defects: tuple[DefectRef, ...]

    #: Everything else in the header block, with blank lines at either end
    #: dropped. Free text, and normally empty: what a defect is belongs in the
    #: catalogue the identifier points at, not repeated in every patch that
    #: repairs one. It is here for what is particular to this patch and
    #: nowhere else -- an unclassified defect, a note on why the repair was
    #: made the way it was.
    body: str


def split_patch(patch: str) -> tuple[PatchHeader, str]:
    """Separate a patch file's header block from its diff.

    Args:
        patch: the contents of a ``.patch`` file.

    Returns:
        The header, and the diff as it stands from its first ``---``, ``@@`` or
        ``diff`` line. A patch with no header gives back an empty
        :py:class:`PatchHeader` and itself unchanged, so this round-trips
        through :py:func:`format_header` either way.
    """
    lines = patch.split("\n")

    for index, line in enumerate(lines):
        if DIFF_START.match(line):
            return _read_header(lines[:index]), "\n".join(lines[index:])

    # No diff in it at all. Malformed, but that is parse_patch's judgement to
    # make against a module name, not this function's.
    return _read_header(lines), ""


def _read_header(lines: list[str]) -> PatchHeader:
    """Read a header block's lines into its defect references and its prose."""
    defects: list[DefectRef] = []
    body: list[str] = []

    for line in lines:
        found = DEFECT.match(line)

        if found:
            defects.append(DefectRef(found[1], found[2] or ""))
            continue

        body.append(line)

    while body and not body[0].strip():
        body.pop(0)

    while body and not body[-1].strip():
        body.pop()

    return PatchHeader(tuple(defects), "\n".join(body))


def format_header(defects: "Iterable[DefectRef] | None" = None, body: str = "") -> str:
    """Write a header block, ending in the blank line that separates it from the diff.

    Args:
        defects: the defects the patch repairs, one ``Defect:`` line each.
            :py:func:`pysmi.defects.ref` builds one of pysmi's.
        body: free text under them, for what the catalogue cannot say.

    Returns:
        The block, or ``""`` when there is nothing to say -- a patch naming no
        defect is written exactly as it was before the convention existed.
    """
    lines = [f"Defect: {defect.id} {defect.url}".rstrip() for defect in defects or ()]

    if not lines and not body:
        return ""

    if body:
        if lines:
            lines.append("")

        lines.extend(body.rstrip("\n").split("\n"))

    lines.append("")

    return "\n".join(lines) + "\n"


def parse_patch(patch: str, mibname: str) -> tuple[Hunk, ...]:
    """Read a unified diff into hunks.

    Everything above the first ``@@`` is skipped, which is what makes a header
    block a convention over the format rather than a change to it: GNU ``patch``
    skips it too. :py:func:`split_patch` is what reads it.

    Args:
        patch: the diff, as written in a ``.patch`` file.
        mibname (str): the module it belongs to, named in errors.

    Returns:
        The hunks, in the order they appear.

    Raises:
        PySmiPatchError: the diff is malformed -- an unreadable line, or hunks
            that do not run forwards.
    """
    lines = patch.split("\n")

    # split() on a trailing newline leaves one empty element that is an artifact
    # of the split rather than a line of the diff. Every other empty element is
    # an empty context line whose trailing space an editor ate, and dropping
    # those would silently misalign everything after them.
    if lines and not lines[-1]:
        lines.pop()

    hunks: list[Hunk] = []
    old_start = new_start = -1
    before: list[str] = []
    after: list[str] = []

    def flush() -> None:
        if old_start >= 0:
            hunks.append(Hunk(old_start, new_start, tuple(before), tuple(after)))

    for line in lines:
        if line.startswith(("--- ", "+++ ")):
            continue

        header = HUNK.match(line)

        if header:
            flush()

            start = int(header[1]) - 1

            if hunks and start < hunks[-1].old_start + len(hunks[-1].before):
                raise PySmiPatchError(f"{mibname}: overlapping hunks in its patch")

            old_start, new_start = start, int(header[3]) - 1
            before, after = [], []
            continue

        if old_start < 0:
            continue

        mark, body = (line[0], line[1:]) if line else (" ", "")

        if mark == "+":
            after.append(body)
        elif mark == "-":
            before.append(body)
        elif mark == " ":
            before.append(body)
            after.append(body)
        elif mark == "\\":
            continue
        else:
            raise PySmiPatchError(f"{mibname}: unreadable line in its patch: {line!r}")

    flush()

    return tuple(hunks)


def _splice(
    lines: list[str], hunks: tuple[Hunk, ...], reverse: bool
) -> list[str] | None:
    """Apply hunks in one direction, or report that the context does not match.

    Returns:
        The patched lines, or ``None`` when any hunk's context is not where the
        diff says it is -- which is a text this patch was not cut against, not
        an error.
    """
    out: list[str] = []
    cursor = 0

    for hunk in hunks:
        start = hunk.new_start if reverse else hunk.old_start
        want = hunk.after if reverse else hunk.before
        give = hunk.before if reverse else hunk.after

        if start < cursor or lines[start : start + len(want)] != list(want):
            return None

        out.extend(lines[cursor:start])
        out.extend(give)
        cursor = start + len(want)

    out.extend(lines[cursor:])

    return out


def apply_patch(text: str, patch: str, mibname: str) -> tuple[str, str]:
    """Offer a patch to a MIB's text.

    Args:
        text: the module's ASN.1 source.
        patch: the diff to offer it.
        mibname (str): the module's name, named in errors.

    Returns:
        The text and what happened to it -- :py:data:`APPLIED` with the patched
        text, or :py:data:`ALREADY_APPLIED` or :py:data:`NOT_APPLICABLE` with the
        text unchanged.

    Raises:
        PySmiPatchError: the diff is malformed. Context that does not match is
            not malformed; it is :py:data:`NOT_APPLICABLE`.
    """
    hunks = parse_patch(patch, mibname)

    if not hunks:
        return text, NOT_APPLICABLE

    # A MIB is text, and whether it arrived with CRLF line endings says nothing
    # about whether the patch applies. Normalise for matching, then put the
    # module's own ending back so patching does not silently rewrite the file's
    # shape -- the source digest is taken over normalised newlines, but the text
    # handed to the lexer is not.
    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").split("\n")

    patched = _splice(lines, hunks, reverse=False)

    if patched is None:
        # Backwards is the dry run `patch -R` does: text that the patch produces
        # is text that already carries it.
        return text, (
            ALREADY_APPLIED
            if _splice(lines, hunks, reverse=True) is not None
            else NOT_APPLICABLE
        )

    out = "\n".join(patched)

    return (out.replace("\n", "\r\n") if crlf else out), APPLIED


def make_patch(
    mibname: str,
    before: str,
    after: str,
    defects: "Iterable[DefectRef] | None" = None,
    body: str = "",
) -> str:
    """Cut a unified diff from a module's text to its repaired text.

    The inverse of :py:func:`apply_patch`, and written in the same shape as the
    patches under ``scripts/mib-patches``: ``a/<MODULE>`` to ``b/<MODULE>``,
    three lines of context, no timestamps. A diff with no timestamps in it is
    one that only changes when the repair does, so a regenerated patch is
    byte-identical to the one already in the tree unless something real moved.

    *defects* and *body* are written above it as a header block, so a repair
    regenerated from a patch that carried one keeps it: read the old file with
    :py:func:`split_patch` and hand its header back here.

    Args:
        mibname (str): the module the diff is for, used in its ``---``/``+++``
            headers.
        before: the module's text as its publisher printed it.
        after: the same text, repaired.
        defects: the defects it repairs, one ``Defect:`` line each.
        body: free text under them, for what the catalogue cannot say.

    Returns:
        The patch, ending in a newline, or ``""`` when the two texts are equal
        -- there being no patch to write for a module that needs no repair,
        and so no defect for it to name.
    """
    # Matching is done over normalised newlines, so cut the diff over them too.
    # A patch carrying CRLF in its context lines would not apply to the same
    # module read from a source that hands back LF, and apply_patch puts the
    # module's own ending back on its own.
    old = before.replace("\r\n", "\n")
    new = after.replace("\r\n", "\n")

    if old == new:
        return ""

    diff = difflib.unified_diff(
        old.split("\n"),
        new.split("\n"),
        fromfile=f"a/{mibname}",
        tofile=f"b/{mibname}",
        n=CONTEXT_LINES,
        lineterm="",
    )

    return format_header(defects, body) + "\n".join(diff) + "\n"


class PatchSet:
    """A set of repairs, keyed by module name.

    A patch is held as the file holds it, header and all, since everything that
    reads one skips what it does not want: :py:meth:`apply` goes to the hunks,
    :py:meth:`defects_for` goes to the header.

    :py:meth:`from_directory` reads a directory of ``<MODULE>.patch`` files,
    which is what :py:mod:`pysmi.scripts.mibpatch` writes and what
    ``hatch_build.py`` applies to pysmi's own bundle as a distribution is
    built. Constructing one directly from a mapping is for a caller holding
    diffs that never went to disk.
    """

    def __init__(self, patches: dict[str, str] | None = None) -> None:
        """Hold a mapping of module name to diff.

        Args:
            patches: module name to unified diff. Empty when omitted.
        """
        self._patches: dict[str, str] = dict(patches or {})

    def __repr__(self) -> str:
        """Show how many modules this set can patch."""
        return f"{self.__class__.__name__}({len(self._patches)} modules)"

    def __contains__(self, mibname: object) -> bool:
        """Whether this set has a patch for *mibname*."""
        return mibname in self._patches

    def __len__(self) -> int:
        """How many modules this set can patch."""
        return len(self._patches)

    def modules(self) -> tuple[str, ...]:
        """Names of the modules this set has a patch for, sorted."""
        return tuple(sorted(self._patches))

    def patch_for(self, mibname: str) -> str | None:
        """The patch file for *mibname*, header and all, or ``None``."""
        return self._patches.get(mibname)

    def header_for(self, mibname: str) -> PatchHeader | None:
        """What the patch for *mibname* says about the repair, or ``None``.

        A patch written without a header gives back an empty
        :py:class:`PatchHeader` rather than ``None``: the patch exists and
        names no defect, which is a different thing from there being no patch.
        """
        patch = self._patches.get(mibname)

        return None if patch is None else split_patch(patch)[0]

    def defects_for(self, mibname: str) -> tuple[DefectRef, ...]:
        """The defects the patch for *mibname* says it repairs.

        Empty when there is no patch, and when the patch predates the
        convention and names none. A caller telling those apart wants
        :py:meth:`header_for`.
        """
        header = self.header_for(mibname)

        return header.defects if header else ()

    def apply(self, mibname: str, text: str) -> tuple[str, str]:
        """Offer this set's patch for *mibname*, if it has one.

        A malformed patch is logged and the text passes through, because a
        reader's job is to produce the module: refusing to read a MIB at all
        because a patch for it is broken would be a worse failure than handing
        back the text the source actually holds.

        Args:
            mibname (str): the module the text belongs to.
            text: the module's ASN.1 source.

        Returns:
            The text and one of :py:data:`APPLIED`, :py:data:`ALREADY_APPLIED`,
            :py:data:`NOT_APPLICABLE` or :py:data:`UNPATCHED`.
        """
        patch = self._patches.get(mibname)

        if patch is None:
            return text, UNPATCHED

        try:
            return apply_patch(text, patch, mibname)

        except PySmiPatchError as exc:
            logger.error(  # noqa: TRY400 -- the traceback adds nothing here
                "MIB %s has a malformed patch, leaving its text alone: %s",
                mibname,
                exc,
                extra={"mib": mibname, "error": str(exc)},
            )

            return text, UNPATCHED

    @classmethod
    def from_directory(cls, path: "str | Path") -> "PatchSet":
        """Read every ``<MODULE>.patch`` in a directory.

        The file name before ``.patch`` is the module name, so the set can be
        looked up without opening anything.

        Args:
            path: the directory to read.

        Returns:
            The patches it holds. Empty when the directory does not exist.
        """
        directory = Path(path)

        if not directory.is_dir():
            return cls()

        return cls(
            {
                entry.stem: entry.read_text(encoding="utf-8")
                for entry in sorted(directory.glob("*.patch"))
            }
        )
