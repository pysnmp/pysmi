#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""MIB patches, carried with the MIB rather than applied once at bundle time.

Some published MIBs do not compile. ``SMUX-MIB`` imports ``OBJECT-TYPE`` from a
module called ``RFC1212``, and no such module exists -- it is ``RFC-1212``.
``HPR-MIB`` is published with ``LAST-UPDATED "970514000000Z"``, which is
thirteen characters and so reads as the wide form, year 9705 of month 14. These
are defects in the published text, and the fix for each is a small diff against
it.

Those diffs used to be applied by the bundle-refresh script, which meant the fix
reached exactly one set of files: pysmi's own copies under ``pysmi/mibs/asn1``.
A caller pointing ``--mib-source`` at their own ``SMUX-MIB``, or at a checkout of
``pysnmp/mibs``, got the published text and the failure the patch exists to
prevent. Worse, source precedence resolves duplicate modules by newest
MODULE-IDENTITY revision, so a caller's *unpatched* copy could outrank pysmi's
patched one and silently reintroduce a break pysmi already knows how to fix.

So a patch travels with the MIB instead. Every reader applies the bundled set on
the way out, whatever source the text came from, and records on the module's
:py:class:`~pysmi.mibinfo.MibInfo` that it did. Reading a MIB means reading the
MIB and its patch.

Three things follow from applying at read time rather than at refresh time:

* A patch is offered to text it was not cut against -- a caller's copy from
  another publisher, a different revision, a copy someone has already hand-fixed.
  Context that does not match is therefore the ordinary case and not an error.
  It is reported as :py:data:`NOT_APPLICABLE` and the text passes through
  unchanged. Only a patch that is not a well-formed diff raises.
* pysmi's own bundled copies are already patched, so the same patch is offered to
  text that already carries it. That is detected by trying the patch backwards --
  the dry run ``patch -R`` does -- and reported as :py:data:`ALREADY_APPLIED`,
  which is a patched module just as much as :py:data:`APPLIED` is.
* Matching is exact. A patch that no longer applies to the text it was cut
  against means the source moved, which is a thing to look at rather than to
  fuzz past, and the bundle refresh still fails loudly on it.
"""

import logging
import re
from importlib import resources
from typing import TYPE_CHECKING, NamedTuple

from pysmi import error

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

#: The text carried the patch already -- pysmi's own bundled copies do.
ALREADY_APPLIED = "already-applied"

#: The patch was applied to this text just now.
APPLIED = "applied"

#: There is a patch for this module, but it was cut against different text.
NOT_APPLICABLE = "not-applicable"

#: No patch is known for this module.
UNPATCHED = ""

HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


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


def parse_patch(patch: str, mibname: str) -> tuple[Hunk, ...]:
    """Read a unified diff into hunks.

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
                raise error.PySmiPatchError(
                    f"{mibname}: overlapping hunks in its patch", mibname=mibname
                )

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
            raise error.PySmiPatchError(
                f"{mibname}: unreadable line in its patch: {line!r}", mibname=mibname
            )

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


class PatchSet:
    """The patches available to a reader, keyed by module name.

    A reader holds one of these and offers the matching patch to every module it
    produces. :py:meth:`bundled` is the set pysmi ships and the default for every
    reader; a caller with their own patches points :py:meth:`from_directory` at
    them, and one who wants none sets the reader's ``patchSet`` to ``None``.
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
        """The diff for *mibname*, or ``None`` when there is not one."""
        return self._patches.get(mibname)

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

        except error.PySmiPatchError as exc:
            logger.error(  # noqa: TRY400 -- the traceback adds nothing here
                "MIB %s has a malformed patch, leaving its text alone: %s",
                mibname,
                exc,
                extra={"mib": mibname, "error": str(exc)},
            )

            return text, UNPATCHED

    @classmethod
    def from_directory(cls, path: "str | pathlib.Path") -> "PatchSet":
        """Read every ``<MODULE>.patch`` in a directory.

        The file name before ``.patch`` is the module name, so the set can be
        looked up without opening anything.

        Args:
            path: the directory to read.

        Returns:
            The patches it holds. Empty when the directory does not exist.
        """
        from pathlib import Path

        directory = Path(path)

        if not directory.is_dir():
            return cls()

        return cls(
            {
                entry.stem: entry.read_text(encoding="utf-8")
                for entry in sorted(directory.glob("*.patch"))
            }
        )

    @classmethod
    def bundled(cls) -> "PatchSet":
        """The patches pysmi ships, in ``pysmi/mibs/patches``.

        Read once and shared, since the set does not change while the process
        runs and every reader wants the same one.
        """
        global _BUNDLED

        if _BUNDLED is None:
            root = resources.files("pysmi") / "mibs" / "patches"

            _BUNDLED = cls(
                {
                    entry.name[: -len(".patch")]: entry.read_text(encoding="utf-8")
                    for entry in sorted(root.iterdir(), key=lambda e: e.name)
                    if entry.name.endswith(".patch")
                }
            )

        return _BUNDLED


_BUNDLED: PatchSet | None = None
