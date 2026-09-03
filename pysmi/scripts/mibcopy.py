#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# SNMP SMI/MIB copying tool
#
"""The *mibcopy* tool: normalize MIB file names and keep the newest revision."""

import contextlib
import getopt
import os
import shutil
import sys
from datetime import datetime

from pysmi import debug, error
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader, getReadersFromUrls
from pysmi.writer import CallbackWriter


def start() -> None:
    """Entry point of the ``mibcopy`` command.

    Copies MIB files, naming each destination after the module the file
    actually defines and keeping only the newest revision of each. Exits with
    a ``sysexits.h`` status.
    """
    # sysexits.h
    EX_OK = 0
    EX_USAGE = 64
    EX_SOFTWARE = 70

    # Defaults
    quietFlag = False
    verboseFlag = False
    mibSources = []
    dstDirectory = None
    cacheDirectory = ""
    ignoreErrorsFlag = False

    helpMessage = """\
    Usage: {} [--help]
        [--version]
        [--verbose]
        [--quiet]
        [--debug=<{}>]
        [--mib-source=<URI>]
        [--cache-directory=<DIRECTORY>]
        [--ignore-errors]
        [--dry-run]
        <SOURCE [SOURCE...]> <DESTINATION>
    Where:
        URI      - file, zip, http, https, ftp, sftp schemes are supported.
                Use @mib@ placeholder token in URI to refer directly to
                the required MIB module when source does not support
                directory listing (e.g. HTTP).
    """.format(os.path.basename(sys.argv[0]), "|".join(sorted(debug.DEBUG_CATEGORIES)))

    # TODO(etingof): add the option to copy MIBs into enterprise-indexed subdirs

    try:
        opts, inputMibs = getopt.getopt(
            sys.argv[1:],
            "hv",
            [
                "help",
                "version",
                "verbose",
                "quiet",
                "debug=",
                "mib-source=",
                "mib-stub=",
                "cache-directory=",
                "ignore-errors",
                "dry-run",
            ],
        )

    except getopt.GetoptError:
        sys.exit(EX_USAGE)

    for opt in opts:
        if opt[0] == "-h" or opt[0] == "--help":
            sys.stderr.write(f"""\
    Synopsis:
    SNMP SMI/MIB files copying tool. When given MIB file(s) or directory(ies)
    on input and a destination directory, the tool parses MIBs to figure out
    their canonical MIB module name and the latest revision date, then
    copies MIB module on input into the destination directory under its
    MIB module name *if* there is no such file already or its revision date
    is older.

    Documentation:
    https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] == "-v" or opt[0] == "--version":
            from pysmi import __version__

            sys.stderr.write(f"""\
    SNMP SMI/MIB library version {__version__}, written by Ilya Etingof <etingof@gmail.com>
    Python interpreter: {sys.version}
    Software documentation and support at https://github.com/pysnmp/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] == "--quiet":
            quietFlag = True

        if opt[0] == "--verbose":
            verboseFlag = True

        if opt[0] == "--debug":
            debug.enableDebugLogging(*opt[1].split(","))

        if opt[0] == "--mib-source":
            mibSources.append(opt[1])

        if opt[0] == "--cache-directory":
            cacheDirectory = opt[1]

        if opt[0] == "--ignore-errors":
            ignoreErrorsFlag = True

    if not mibSources:
        mibSources = ["file:///usr/share/snmp/mibs", "https://pysnmp.github.io:443/mibs/asn1/@mib@"]

    if len(inputMibs) < 2:
        sys.stderr.write(f"ERROR: MIB source and/or destination arguments not given\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    dstDirectory = inputMibs.pop()

    if os.path.exists(dstDirectory) and not os.path.isdir(dstDirectory):
        sys.stderr.write(f"ERROR: given destination is not a directory\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    with contextlib.suppress(OSError):
        os.makedirs(dstDirectory, mode=0o755)

    # Compiler infrastructure

    codeGenerator = JsonCodeGen()

    mibParser = SmiV1CompatParser(tempdir=cacheDirectory)

    fileWriter = CallbackWriter(lambda *x: None)

    def getMibRevisions(mibDir: str, mibFile: str) -> dict[str, datetime]:
        """Read a MIB file just far enough to learn what it defines.

        One file may hold several modules, which is common in vendor archives.
        Every module is reported, so that each can be copied under its own name;
        a reader asked for one of them looks for a file bearing that name.

        Args:
            mibDir (str): directory holding the file
            mibFile (str): file to inspect

        Returns:
            The latest revision date of each module the file defines, keyed by
            module name, in the order the modules appear.

        Raises:
            PySmiError: the file could not be read or holds no MIB.
        """
        mibCompiler = MibCompiler(mibParser, codeGenerator, fileWriter)

        mibCompiler.add_sources(
            FileReader(mibDir, recursive=False, ignoreErrors=ignoreErrorsFlag), *getReadersFromUrls(*mibSources)
        )

        try:
            processed = mibCompiler.compile(
                mibFile, **dict(noDeps=True, rebuild=True, fuzzyMatching=False, ignoreErrors=ignoreErrorsFlag)
            )

        except error.PySmiError as exc:
            sys.stderr.write(f"ERROR: {exc}\r\n")
            sys.exit(EX_SOFTWARE)

        revisions: dict[str, datetime] = {}

        for canonicalMibName in processed:
            if processed[canonicalMibName] == "compiled" and processed[
                canonicalMibName
            ].path == "file://" + os.path.join(mibDir, mibFile):
                try:
                    revision = datetime.strptime(processed[canonicalMibName].revision, "%Y-%m-%d %H:%M")

                except (TypeError, ValueError):
                    # Missing or unparsable revision date.
                    revision = datetime.fromtimestamp(0)

                revisions[canonicalMibName] = revision

        if not revisions:
            raise error.PySmiError(f'Can\'t read or parse MIB "{os.path.join(mibDir, mibFile)}"')

        return revisions

    def shortenPath(path: str, maxLength: int = 45) -> str:
        """Trim a path from the left for display, keeping the tail readable."""
        if len(path) > maxLength:
            return "..." + path[-maxLength:]
        else:
            return path

    mibsSeen = mibsCopied = mibsFailed = 0

    # None means the destination has no such module yet, which is not the same
    # as holding one dated the epoch: an absent destination is always copied into.
    mibsRevisions: dict[str, datetime | None] = {}

    for srcDirectory in inputMibs:
        if verboseFlag:
            sys.stderr.write(f'Reading "{srcDirectory}"...\r\n')

        if os.path.isfile(srcDirectory):
            mibFiles = [(os.path.abspath(os.path.dirname(srcDirectory)), os.path.basename(srcDirectory))]

        else:
            mibFiles = [
                (os.path.abspath(dirName), mibFile)
                for dirName, _, mibFiles in os.walk(srcDirectory)
                for mibFile in mibFiles
            ]

        for mibDir, mibFile in mibFiles:
            mibsSeen += 1

            # TODO(etingof): also check module OID to make sure there is no name collision

            try:
                srcMibRevisions = getMibRevisions(mibDir, mibFile)

            except error.PySmiError as ex:
                if verboseFlag:
                    sys.stderr.write(f'Failed to read source MIB "{os.path.join(mibDir, mibFile)}": {ex}\r\n')

                if not quietFlag:
                    sys.stderr.write(f"FAILED {shortenPath(os.path.join(mibDir, mibFile))}\r\n")

                mibsFailed += 1

                continue

            # A file holding several modules is copied once under each of their
            # names: whoever looks a module up expects a file called after it.
            for mibName, srcMibRevision in srcMibRevisions.items():
                if mibName in mibsRevisions:
                    dstMibRevision = mibsRevisions[mibName]

                else:
                    try:
                        dstMibRevision = getMibRevisions(dstDirectory, mibName)[mibName]

                    except (error.PySmiError, KeyError) as ex:
                        if verboseFlag:
                            sys.stderr.write(
                                f'MIB "{os.path.join(mibDir, mibFile)}" is not available at the '
                                f'destination directory "{dstDirectory}": {ex}\r\n'
                            )

                        dstMibRevision = None

                    mibsRevisions[mibName] = dstMibRevision

                if dstMibRevision is not None and dstMibRevision >= srcMibRevision:
                    if verboseFlag:
                        sys.stderr.write(
                            f'Destination MIB "{os.path.join(dstDirectory, mibName)}" has the same or newer revision as the '
                            f'source MIB "{os.path.join(mibDir, mibFile)}"\r\n'
                        )
                    if not quietFlag:
                        sys.stderr.write(f"NOT COPIED {shortenPath(os.path.join(mibDir, mibFile))} ({mibName})\r\n")

                    continue

                if verboseFlag:
                    sys.stderr.write(
                        f'Copying "{os.path.join(mibDir, mibFile)}" (revision "{srcMibRevision}") -> "{os.path.join(dstDirectory, mibName)}" (revision "{dstMibRevision}")\r\n'
                    )

                try:
                    shutil.copy(os.path.join(mibDir, mibFile), os.path.join(dstDirectory, mibName))

                except OSError as ex:
                    if verboseFlag:
                        sys.stderr.write(
                            f'Failed to copy MIB "{os.path.join(mibDir, mibFile)}" -> "{os.path.join(dstDirectory, mibName)}" ({mibName}): "{ex}"\r\n'
                        )

                    if not quietFlag:
                        sys.stderr.write(f"FAILED {shortenPath(os.path.join(mibDir, mibFile))} ({mibName})\r\n")

                    mibsFailed += 1

                else:
                    # Only a copy that landed changes what the destination holds; a
                    # failed one must not stop a later file defining the same module.
                    mibsRevisions[mibName] = srcMibRevision

                    if not quietFlag:
                        sys.stderr.write(f"COPIED {shortenPath(os.path.join(mibDir, mibFile))} ({mibName})\r\n")

                    mibsCopied += 1

    if not quietFlag:
        sys.stderr.write(f"MIBs seen: {mibsSeen}, copied: {mibsCopied}, failed: {mibsFailed}\r\n")

    sys.exit(EX_OK)
