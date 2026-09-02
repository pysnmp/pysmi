#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# SNMP SMI/MIB copying tool
#
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


def start():
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
    """.format(sys.argv[0], "|".join(sorted(debug.DEBUG_CATEGORIES)))

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
    http://snmplabs.com/pysmi
    {helpMessage}
    """)
            sys.exit(EX_OK)

        if opt[0] == "-v" or opt[0] == "--version":
            from pysmi import __version__

            sys.stderr.write(f"""\
    SNMP SMI/MIB library version {__version__}, written by Ilya Etingof <etingof@gmail.com>
    Python interpreter: {sys.version}
    Software documentation and support at http://snmplabs.com/pysmi
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

    def getMibRevision(mibDir, mibFile):
        mibCompiler = MibCompiler(mibParser, codeGenerator, fileWriter)

        mibCompiler.addSources(
            FileReader(mibDir, recursive=False, ignoreErrors=ignoreErrorsFlag), *getReadersFromUrls(*mibSources)
        )

        try:
            processed = mibCompiler.compile(
                mibFile, **dict(noDeps=True, rebuild=True, fuzzyMatching=False, ignoreErrors=ignoreErrorsFlag)
            )

        except error.PySmiError as exc:
            sys.stderr.write(f"ERROR: {exc}\r\n")
            sys.exit(EX_SOFTWARE)

        for canonicalMibName in processed:
            if processed[canonicalMibName] == "compiled" and processed[
                canonicalMibName
            ].path == "file://" + os.path.join(mibDir, mibFile):
                try:
                    revision = datetime.strptime(processed[canonicalMibName].revision, "%Y-%m-%d %H:%M")

                except (TypeError, ValueError):
                    # Missing or unparsable revision date.
                    revision = datetime.fromtimestamp(0)

                return canonicalMibName, revision

        raise error.PySmiError(f'Can\'t read or parse MIB "{os.path.join(mibDir, mibFile)}"')

    def shortenPath(path, maxLength=45):
        if len(path) > maxLength:
            return "..." + path[-maxLength:]
        else:
            return path

    mibsSeen = mibsCopied = mibsFailed = 0

    mibsRevisions = {}

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
                mibName, srcMibRevision = getMibRevision(mibDir, mibFile)

            except error.PySmiError as ex:
                if verboseFlag:
                    sys.stderr.write(f'Failed to read source MIB "{os.path.join(mibDir, mibFile)}": {ex}\r\n')

                if not quietFlag:
                    sys.stderr.write(f"FAILED {shortenPath(os.path.join(mibDir, mibFile))}\r\n")

                mibsFailed += 1

                continue

            if mibName in mibsRevisions:
                dstMibRevision = mibsRevisions[mibName]

            else:
                try:
                    _, dstMibRevision = getMibRevision(dstDirectory, mibName)

                except error.PySmiError as ex:
                    if verboseFlag:
                        sys.stderr.write(
                            f'MIB "{os.path.join(mibDir, mibFile)}" is not available at the '
                            f'destination directory "{dstDirectory}": {ex}\r\n'
                        )

                    dstMibRevision = datetime.fromtimestamp(0)

                mibsRevisions[mibName] = dstMibRevision

            if dstMibRevision >= srcMibRevision:
                if verboseFlag:
                    sys.stderr.write(
                        f'Destination MIB "{os.path.join(dstDirectory, mibName)}" has the same or newer revision as the '
                        f'source MIB "{os.path.join(mibDir, mibFile)}"\r\n'
                    )
                if not quietFlag:
                    sys.stderr.write(f"NOT COPIED {shortenPath(os.path.join(mibDir, mibFile))} ({mibName})\r\n")

                continue

            mibsRevisions[mibName] = srcMibRevision

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
                if not quietFlag:
                    sys.stderr.write(f"COPIED {shortenPath(os.path.join(mibDir, mibFile))} ({mibName})\r\n")

                mibsCopied += 1

    if not quietFlag:
        sys.stderr.write(f"MIBs seen: {mibsSeen}, copied: {mibsCopied}, failed: {mibsFailed}\r\n")

    sys.exit(EX_OK)
