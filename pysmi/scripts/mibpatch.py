#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
# SNMP SMI/MIB repair tool
#
"""The *mibpatch* tool: write down the repairs a tree of MIBs needs.

pysmi repairs a module that uses an SMIv2 base symbol without naming it in
IMPORTS, and does it in memory, every run, leaving no trace in the source. That
suits a consumer compiling somebody else's MIBs. It suits nobody who *owns* a
tree of them: the defect is rediscovered on every run, the correction is never
reviewed, and the only record it happened is a line in a report.

This tool makes the repair a file. It scans a source tree, works out the same
corrections the compiler would have made, and writes each one as a unified diff
under an output directory. Those diffs are reviewable, they go into version
control, and ``--apply`` writes them into the tree -- after which the modules
compile under ``mibdump --strict-imports`` and no repair happens at runtime at
all.

``--check`` writes nothing and fails when the patches on disk are not the ones
the tree needs, which is the same job in a CI gate: a MIB that grew a new defect,
or a patch left behind by one that was fixed upstream.

What cannot be derived is reported rather than guessed at. A module that does
not parse has no symbol table to reason from, so its patch has to be written by
hand -- the twelve in ``scripts/mib-patches`` mostly are.

Every patch written here opens with the defect it repairs, since a derived
repair knows exactly what that is: an identifier from :py:mod:`pysmi.defects`
and the URL documenting it, one line. A header somebody has since edited is
kept -- regenerating the diff does not spend what a person wrote about the
defect -- and ``--check`` compares diffs rather than headers for the same
reason.
"""

import getopt
import logging
import os
import sys
from pathlib import Path
from typing import Final

from pysmi import debug, error
from pysmi.patches import (
    APPLIED,
    NOT_APPLICABLE,
    apply_patch,
    format_header,
    split_patch,
)
from pysmi.patchgen import CLEAN, REPAIRABLE, UNPARSEABLE, Defect, inspect

logger = logging.getLogger(__name__)

# sysexits.h
EX_OK: Final = 0
EX_USAGE: Final = 64
EX_SOFTWARE: Final = 70

#: ``--check`` found the patches on disk are not the ones the tree needs.
EX_STALE: Final = 79

#: Names that are never a MIB, so that pointing the tool at a checkout does not
#: try to parse its version control.
_SKIP: Final = frozenset({"__pycache__", ".git", ".hg", ".svn"})


def start() -> None:
    """Scan the trees named by the command line and write out their repairs."""
    sourceDirectories: list[str] = []
    outputDirectory = "mib-patches"
    verboseFlag = True
    checkFlag = False
    applyFlag = False

    helpMessage = """\
    Usage: {} [--help]
        [--version]
        [--quiet]
        [--debug=<{}>]
        [--source=<DIRECTORY>]
        [--output-directory=<DIRECTORY>]
        [--check]
        [--apply]
    Where:
        --source - a directory of ASN.1 MIB modules to scan, repeatable.
                Every file in it is read as a module, and the name a
                module gives itself is what its patch is named after,
                not the name of the file it was found in.
        --output-directory - where the patches go, one <MODULE>.patch per
                repaired module, each opening with the defect it repairs
                and a link to where that defect is documented. Read back
                by --check and --apply, and by
                pysmi.patches.PatchSet.from_directory. A header edited by
                hand is kept when the patch is regenerated. Defaults to
                "mib-patches" under the working directory.
        --check  - write nothing and exit {} if the patches on disk are
                not the ones the sources need: a module needing a patch
                that is not there, a patch that no longer matches what
                the module needs, or a patch left behind by a module that
                no longer needs one. For a CI gate over a MIB tree.
        --apply  - write each repaired module back over its source file,
                as well as writing the diff. The tree then compiles under
                "mibdump --strict-imports", which is the point: the
                repair has moved out of the compiler and into the MIBs.
    """.format(
        os.path.basename(sys.argv[0]),
        "|".join(sorted(debug.flagMap)),
        EX_STALE,
    )

    try:
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "hv",
            [
                "help",
                "version",
                "quiet",
                "debug=",
                "source=",
                "output-directory=",
                "check",
                "apply",
            ],
        )

    except getopt.GetoptError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    for opt in opts:
        if opt[0] in ("-h", "--help"):
            sys.stderr.write(f"""\
    Synopsis:
    Write the repairs a tree of MIBs needs out as reviewable patches
    Documentation:
    https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] in ("-v", "--version"):
            from pysmi import __version__

            sys.stderr.write(f"""\
    SNMP SMI/MIB library version {__version__}
    Python interpreter: {sys.version}
    Software documentation and support at https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] == "--quiet":
            verboseFlag = False

        if opt[0] == "--debug":
            debug.enableDebugLogging(*opt[1].split(","))

        if opt[0] == "--source":
            sourceDirectories.append(opt[1])

        if opt[0] == "--output-directory":
            outputDirectory = opt[1]

        if opt[0] == "--check":
            checkFlag = True

        if opt[0] == "--apply":
            applyFlag = True

    if verboseFlag:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    if not sourceDirectories:
        sys.stderr.write(f"ERROR: no sources; pass --source\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    if checkFlag and applyFlag:
        sys.stderr.write(
            f"ERROR: --check writes nothing, so it cannot --apply\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    try:
        found = _scan(sourceDirectories)

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    out = Path(outputDirectory)

    if checkFlag:
        stale = _check(found, out)

        if verboseFlag:
            _summarize(found, stale=stale)

        sys.exit(EX_STALE if stale else EX_OK)

    try:
        _write(found, out, applyFlag=applyFlag)

    except OSError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    if verboseFlag:
        _summarize(found)

    sys.exit(EX_OK)


def _scan(directories: list[str]) -> dict[Path, Defect]:
    """Read every module under *directories* and work out what each needs.

    A file that cannot be decoded as text is not a MIB and is passed over in
    silence; a file that decodes but does not parse is a MIB that needs a
    hand-written patch, and is reported as one.

    Returns:
        The path each module was read from, mapped to its
        :py:class:`~pysmi.patchgen.Defect`, ordered by path.

    Raises:
        PySmiFileNotFoundError: a named directory is not there.
    """
    found: dict[Path, Defect] = {}

    for name in directories:
        directory = Path(name)

        if not directory.is_dir():
            raise error.PySmiFileNotFoundError(f"no such source directory: {name}")

        for path in sorted(directory.rglob("*")):
            if not path.is_file() or set(path.parts) & _SKIP:
                continue

            if path.name.startswith(".") or path.suffix in (".py", ".patch"):
                continue

            try:
                # newline="" so a CRLF module is seen as it is on disk: the
                # patch is cut against that text, and has to apply to it.
                with path.open(encoding="utf-8", newline="") as source:
                    text = source.read()

            except (UnicodeDecodeError, OSError):
                logger.debug("not readable as text, skipping: %s", path)
                continue

            found[path] = inspect(text, mibname=path.stem)

    return found


def _check(found: dict[Path, Defect], out: Path) -> list[str]:
    """Compare the patches a tree needs against the ones on disk.

    The comparison is of the diffs. A patch's header is the thing a person
    wrote about the repair, and a person who improved the wording of a reason
    has not made the patch stale.

    Returns:
        One line per disagreement, ready to print. Empty when the directory
        holds exactly the patches the sources need.
    """
    on_disk = {
        path.stem: path.read_text(encoding="utf-8")
        for path in sorted(out.glob("*.patch"))
    }

    stale: list[str] = []

    for path, defect in sorted(found.items()):
        patch = on_disk.get(defect.mibname)

        if defect.status == REPAIRABLE:
            if patch is None:
                stale.append(f"{defect.mibname}: needs a patch, and none is written")

            elif split_patch(patch)[1] != split_patch(defect.patch)[1]:
                stale.append(f"{defect.mibname}: its patch is not the repair it needs")

            continue

        if patch is None:
            continue

        # The module needs no repair derived, but a patch for it exists. That
        # is the ordinary state of a tree --apply has been run over, and of one
        # whose patches are hand-written: the text already carries them. So the
        # question is not whether the patch is surplus but whether it still
        # belongs to this text, and the patch answers that itself -- offered to
        # text it produced, it reports ALREADY_APPLIED.
        with path.open(encoding="utf-8", newline="") as source:
            _, status = apply_patch(source.read(), patch, defect.mibname)

        if status == NOT_APPLICABLE:
            stale.append(
                f"{defect.mibname}: its patch was cut against different text"
                if defect.status == UNPARSEABLE
                else f"{defect.mibname}: needs no patch, but one is written"
            )

    seen = {defect.mibname for defect in found.values()}

    # A patch for a module no source held is not judged here: the tree being
    # scanned is not necessarily the only one the set covers.
    for mibname in sorted(set(on_disk) - seen):
        logger.info(
            "patch for %s kept: no source scanned holds that module",
            mibname,
            extra={"mib": mibname},
        )

    return stale


def _keeping_header(patchFile: Path, patch: str) -> str:
    """Put a freshly derived diff under the header the file on disk already had.

    The derived header names what the compiler could work out. Somebody who has
    added the defects it could not classify, or a note on what was reported
    upstream, has written the better one; regenerating the repair must not
    spend it.

    Args:
        patchFile: the ``<MODULE>.patch`` about to be written, which may not
            exist.
        patch: the patch just derived, header and all.

    Returns:
        *patch*, or *patch*'s diff under the header already on disk.
    """
    if not patchFile.exists():
        return patch

    try:
        header = split_patch(patchFile.read_text(encoding="utf-8"))[0]

    except OSError:
        return patch

    if not header.defects and not header.body:
        return patch

    return format_header(header.defects, header.body) + split_patch(patch)[1]


def _write(found: dict[Path, Defect], out: Path, *, applyFlag: bool) -> None:
    """Write each derived diff, and optionally the repaired module with it."""

    repairable = {
        path: defect for path, defect in found.items() if defect.status == REPAIRABLE
    }

    if repairable:
        out.mkdir(parents=True, exist_ok=True)

    for path, defect in repairable.items():
        patchFile = out / f"{defect.mibname}.patch"

        patchFile.write_text(_keeping_header(patchFile, defect.patch), encoding="utf-8")

        if not applyFlag:
            continue

        with path.open(encoding="utf-8", newline="") as source:
            text = source.read()

        patched, status = apply_patch(text, defect.patch, defect.mibname)

        if status != APPLIED:
            logger.error(
                "MIB %s: its own patch did not apply to it (%s), leaving it alone",
                defect.mibname,
                status,
                extra={"mib": defect.mibname, "status": status},
            )
            continue

        # newline="" so that a module written back keeps the line endings it
        # arrived with rather than gaining the platform's.
        with path.open("w", encoding="utf-8", newline="") as target:
            target.write(patched)


def _summarize(found: dict[Path, Defect], stale: list[str] | None = None) -> None:
    """Report what the scan found, and what --check disagreed with."""
    repaired = sorted(
        (defect.mibname, split_patch(defect.patch)[0].defects, defect.imports)
        for defect in found.values()
        if defect.status == REPAIRABLE
    )

    byhand = sorted(
        (defect.mibname, defect.reason)
        for defect in found.values()
        if defect.status == UNPARSEABLE
    )

    clean = sum(1 for defect in found.values() if defect.status == CLEAN)

    sys.stderr.write(f"Read {len(found)} modules, {clean} needing nothing\n")

    if repaired:
        sys.stderr.write(f"Repairs derived for {len(repaired)} modules:\n")

        # The identifiers the patch carries, then what this module in
        # particular was missing. The identifier says which kind of defect it
        # is and is documented once; the symbols are what nothing else knows.
        for mibname, references, imports in repaired:
            named = ", ".join(reference.id for reference in references)
            supplied = ", ".join(
                f"{symbol} from {module}" for symbol, module in sorted(imports.items())
            )
            sys.stderr.write(f" {mibname} ({named}: {supplied})\n")

    if byhand:
        sys.stderr.write(
            f"No repair could be derived for {len(byhand)} modules, "
            f"so a patch for each has to be written by hand:\n"
        )

        for mibname, reason in byhand:
            sys.stderr.write(f" {mibname} ({reason})\n")

    if stale:
        sys.stderr.write(
            f"Patches on disk disagree with the sources in {len(stale)} ways:\n"
        )

        for line in stale:
            sys.stderr.write(f" {line}\n")


if __name__ == "__main__":
    start()
