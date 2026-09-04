#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# SNMP SMI/MIB data management tool
#
"""The *mibdump* tool: compile ASN.1 MIBs into PySNMP modules or JSON."""

import getopt
import os
import sys
from typing import Final

from pysmi import debug, error
from pysmi.borrower import AnyFileBorrower, PyFileBorrower
from pysmi.borrower.base import AbstractBorrower
from pysmi.codegen import JsonCodeGen, NullCodeGen, PySnmpCodeGen
from pysmi.codegen.base import AbstractCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import getReadersFromUrls
from pysmi.searcher import AnyFileSearcher, PyFileSearcher, PyPackageSearcher, StubSearcher
from pysmi.searcher.base import AbstractSearcher
from pysmi.writer import CallbackWriter, FileWriter, PyFileWriter

_JSON_EXT: Final = ".json"


def start() -> None:
    """Entry point of the ``mibdump`` command.

    Parses the command line, compiles the requested MIBs and reports what
    happened. Exits with a ``sysexits.h`` status.
    """
    # sysexits.h
    EX_OK = 0
    EX_USAGE = 64
    EX_SOFTWARE = 70
    EX_MIB_MISSING = 79
    EX_MIB_FAILED = 79

    # Defaults
    verboseFlag = True
    mibSources: list[str] = []
    doFuzzyMatchingFlag = True
    mibSearchers: list[str] = []
    mibStubs: list[str] = []
    mibBorrowers: list[tuple[str, bool]] = []
    dstFormat = None
    dstDirectory: str | None = None
    cacheDirectory = ""
    nodepsFlag = False
    rebuildFlag = False
    pruneFlag = False
    bundledMibsFlag = True
    dryrunFlag = False
    genMibTextsFlag = False
    keepTextsLayout = False
    pyCompileFlag = True
    pyOptimizationLevel = 0
    ignoreErrorsFlag = False
    buildIndexFlag = False
    writeMibsFlag = True
    repairImportsFlag = False

    helpMessage = """\
    Usage: {} [--help]
        [--version]
        [--quiet]
        [--debug=<{}>]
        [--mib-source=<URI>]
        [--mib-searcher=<PATH|PACKAGE>]
        [--mib-stub=<MIB-NAME>]
        [--mib-borrower=<PATH>]
        [--destination-format=<FORMAT>]
        [--destination-directory=<DIRECTORY>]
        [--cache-directory=<DIRECTORY>]
        [--disable-fuzzy-source]
        [--no-dependencies]
        [--no-bundled-mibs]
        [--no-python-compile]
        [--python-optimization-level]
        [--ignore-errors]
        [--build-index]
        [--rebuild]
        [--prune]
        [--dry-run]
        [--no-mib-writes]
        [--generate-mib-texts]
        [--keep-texts-layout]
        [--repair-imports]
        <MIB-NAME> [MIB-NAME [...]]]
    Where:
        URI      - file, zip, http, https, ftp, sftp schemes are supported.
                Use @mib@ placeholder token in URI to refer directly to
                the required MIB module when source does not support
                directory listing (e.g. HTTP).
        FORMAT   - pysnmp, json, null
        --prune  - remove previously stored output whose source MIB no
                longer exists in any configured source. Runs without
                MIB-NAME arguments; deletes unless combined with
                --dry-run.
        --no-bundled-mibs - do not fall back to pysmi's own bundled copy
                of the RFC-frozen base MIBs (SNMPv2-SMI and similar) when
                none of --mib-source has them. Without this, a compile
                that would once have failed on a missing base MIB now
                silently succeeds from the bundled copy; pass this to make
                a misconfigured --mib-source fail loudly instead.
        --repair-imports - supply the import a MIB should have carried for
                any SNMPv2-SMI, SNMPv2-TC or SNMPv2-CONF symbol it uses
                without naming it in IMPORTS, which RFC 2578 Section 3.2
                does not allow. Off by default, so a MIB broken this way
                fails rather than being silently patched; what was
                repaired is listed in the report.""".format(
        os.path.basename(sys.argv[0]), "|".join(sorted(debug.DEBUG_CATEGORIES))
    )

    try:
        opts, inputMibs = getopt.getopt(
            sys.argv[1:],
            "hv",
            [
                "help",
                "version",
                "quiet",
                "debug=",
                "mib-source=",
                "mib-searcher=",
                "mib-stub=",
                "mib-borrower=",
                "destination-format=",
                "destination-directory=",
                "cache-directory=",
                "no-dependencies",
                "no-bundled-mibs",
                "no-python-compile",
                "python-optimization-level=",
                "ignore-errors",
                "build-index",
                "rebuild",
                "prune",
                "dry-run",
                "no-mib-writes",
                "generate-mib-texts",
                "disable-fuzzy-source",
                "keep-texts-layout",
                "repair-imports",
            ],
        )

    except getopt.GetoptError as exc:
        if verboseFlag:
            sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")

        sys.exit(EX_USAGE)

    for opt in opts:
        if opt[0] == "-h" or opt[0] == "--help":
            sys.stderr.write(f"""\
    Synopsis:
    SNMP SMI/MIB files conversion tool
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
            verboseFlag = False

        if opt[0] == "--debug":
            debug.enableDebugLogging(*opt[1].split(","))

        if opt[0] == "--mib-source":
            mibSources.append(opt[1])

        if opt[0] == "--mib-searcher":
            mibSearchers.append(opt[1])

        if opt[0] == "--mib-stub":
            mibStubs.append(opt[1])

        if opt[0] == "--mib-borrower":
            mibBorrowers.append((opt[1], genMibTextsFlag))

        if opt[0] == "--destination-format":
            dstFormat = opt[1]

        if opt[0] == "--destination-directory":
            dstDirectory = opt[1]

        if opt[0] == "--cache-directory":
            cacheDirectory = opt[1]

        if opt[0] == "--no-dependencies":
            nodepsFlag = True

        if opt[0] == "--no-bundled-mibs":
            bundledMibsFlag = False

        if opt[0] == "--no-python-compile":
            pyCompileFlag = False

        if opt[0] == "--python-optimization-level":
            try:
                pyOptimizationLevel = int(opt[1])

            except ValueError:
                sys.stderr.write(f"ERROR: known Python optimization levels: -1, 0, 1, 2\r\n{helpMessage}\r\n")
                sys.exit(EX_USAGE)

        if opt[0] == "--ignore-errors":
            ignoreErrorsFlag = True

        if opt[0] == "--build-index":
            buildIndexFlag = True

        if opt[0] == "--rebuild":
            rebuildFlag = True

        if opt[0] == "--prune":
            pruneFlag = True

        if opt[0] == "--dry-run":
            dryrunFlag = True

        if opt[0] == "--no-mib-writes":
            writeMibsFlag = False

        if opt[0] == "--generate-mib-texts":
            genMibTextsFlag = True

        if opt[0] == "--disable-fuzzy-source":
            doFuzzyMatchingFlag = False

        if opt[0] == "--keep-texts-layout":
            keepTextsLayout = True

        if opt[0] == "--repair-imports":
            repairImportsFlag = True

    if not mibSources:
        mibSources = ["https://pysnmp.github.io:443/mibs/asn1/@mib@"]

    if inputMibs:
        mibSources = sorted({os.path.abspath(os.path.dirname(x)) for x in inputMibs if os.path.sep in x}) + mibSources

        inputMibs = [os.path.basename(os.path.splitext(x)[0]) for x in inputMibs]

    if not inputMibs and not pruneFlag:
        sys.stderr.write(f"ERROR: MIB modules names not specified\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    if not dstFormat:
        dstFormat = "pysnmp"

    if dstFormat == "pysnmp":
        if not mibSearchers:
            mibSearchers = list(PySnmpCodeGen.defaultMibPackages)

        if not mibStubs:
            mibStubs = [x for x in PySnmpCodeGen.baseMibs if x not in PySnmpCodeGen.fakeMibs]

        if not mibBorrowers:
            mibBorrowers = [
                ("https://pysnmp.github.com:443/mibs/notexts/@mib@", False),
                ("https://pysnmp.github.com:443/mibs/fulltexts/@mib@", True),
            ]

        if not dstDirectory:
            dstDirectory = os.path.expanduser("~")
            if sys.platform[:3] == "win":
                dstDirectory = os.path.join(dstDirectory, "PySNMP Configuration", "mibs")
            else:
                dstDirectory = os.path.join(dstDirectory, ".pysnmp", "mibs")

        # Compiler infrastructure

        borrowers: list[AbstractBorrower] = [
            PyFileBorrower(x[1], genTexts=mibBorrowers[x[0]][1])
            for x in enumerate(getReadersFromUrls(*[m[0] for m in mibBorrowers], **dict(lowcaseMatching=False)))
        ]

        searchers: list[AbstractSearcher] = [PyFileSearcher(dstDirectory)]

        for mibSearcher in mibSearchers:
            searchers.append(PyPackageSearcher(mibSearcher))

        searchers.append(StubSearcher(*mibStubs))

        codeGenerator: AbstractCodeGen = PySnmpCodeGen()

        fileWriter = PyFileWriter(dstDirectory).set_options(
            pyCompile=pyCompileFlag, pyOptimizationLevel=pyOptimizationLevel
        )

    elif dstFormat == "json":
        if not mibStubs:
            mibStubs = list(JsonCodeGen.baseMibs)

        if not mibBorrowers:
            mibBorrowers = [
                ("https://pysnmp.github.io:443/mibs/json/notexts/@mib@", False),
                ("https://pysnmp.github.io:443/mibs/fulltexts/@mib@", True),
            ]

        if not dstDirectory:
            dstDirectory = os.path.join(".")

        # Compiler infrastructure

        borrowers = [
            AnyFileBorrower(x[1], genTexts=mibBorrowers[x[0]][1]).set_options(exts=[_JSON_EXT])
            for x in enumerate(getReadersFromUrls(*[m[0] for m in mibBorrowers], **dict(lowcaseMatching=False)))
        ]

        searchers = [AnyFileSearcher(dstDirectory).set_options(exts=[_JSON_EXT]), StubSearcher(*mibStubs)]

        codeGenerator = JsonCodeGen()

        fileWriter = FileWriter(dstDirectory).set_options(suffix=_JSON_EXT)

    elif dstFormat == "null":
        if not mibStubs:
            mibStubs = list(NullCodeGen.baseMibs)

        if not mibBorrowers:
            mibBorrowers = [
                ("https://pysnmp.github.io:443/mibs/null/notexts/@mib@", False),
                ("https://pysnmp.github.io:443/mibs/null/fulltexts/@mib@", True),
            ]

        if not dstDirectory:
            dstDirectory = ""

        # Compiler infrastructure

        codeGenerator = NullCodeGen()

        searchers = [StubSearcher(*mibStubs)]

        borrowers = [
            AnyFileBorrower(x[1], genTexts=mibBorrowers[x[0]][1])
            for x in enumerate(getReadersFromUrls(*[m[0] for m in mibBorrowers], **dict(lowcaseMatching=False)))
        ]

        fileWriter = CallbackWriter(lambda *x: None)

    else:
        sys.stderr.write(f"ERROR: unknown destination format: {dstFormat}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    if verboseFlag:
        sys.stderr.write(
            """Source MIB repositories: {}
    Borrow missing/failed MIBs from: {}
    Existing/compiled MIB locations: {}
    Compiled MIBs destination directory: {}
    MIBs excluded from code generation: {}
    MIBs to compile: {}
    Destination format: {}
    Parser grammar cache directory: {}
    Also compile all relevant MIBs: {}
    Use pysmi's bundled base MIBs as a fallback source: {}
    Rebuild MIBs regardless of age: {}
    Prune stored MIBs with no remaining source: {}
    Dry run mode: {}
    Create/update MIBs: {}
    Byte-compile Python modules: {} (optimization level {})
    Ignore compilation errors: {}
    Generate OID->MIB index: {}
    Generate texts in MIBs: {}
    Keep original texts layout: {}
    Try various file names while searching for MIB module: {}
    """.format(
                ", ".join(mibSources),
                ", ".join([x[0] for x in mibBorrowers if x[1] == genMibTextsFlag]),
                ", ".join(mibSearchers),
                dstDirectory,
                ", ".join(sorted(mibStubs)),
                ", ".join(inputMibs),
                dstFormat,
                cacheDirectory or "not used",
                (nodepsFlag and "no") or "yes",
                (bundledMibsFlag and "yes") or "no",
                (rebuildFlag and "yes") or "no",
                (pruneFlag and "yes") or "no",
                (dryrunFlag and "yes") or "no",
                (writeMibsFlag and "yes") or "no",
                (dstFormat == "pysnmp" and pyCompileFlag and "yes") or "no",
                (dstFormat == "pysnmp" and pyOptimizationLevel and "yes") or "no",
                (ignoreErrorsFlag and "yes") or "no",
                (buildIndexFlag and "yes") or "no",
                (genMibTextsFlag and "yes") or "no",
                (keepTextsLayout and "yes") or "no",
                (doFuzzyMatchingFlag and "yes") or "no",
            )
        )

    # Initialize compiler infrastructure

    mibCompiler = MibCompiler(
        SmiV1CompatParser(tempdir=cacheDirectory), codeGenerator, fileWriter, useBundledMibs=bundledMibsFlag
    )

    pruned = {}

    try:
        mibCompiler.add_sources(*getReadersFromUrls(*mibSources, **dict(fuzzyMatching=doFuzzyMatchingFlag)))

        mibCompiler.add_searchers(*searchers)

        mibCompiler.add_borrowers(*borrowers)

        processed = mibCompiler.compile(
            *inputMibs,
            **dict(
                noDeps=nodepsFlag,
                rebuild=rebuildFlag,
                dryRun=dryrunFlag,
                genTexts=genMibTextsFlag,
                textFilter=(lambda symbol, text: text) if keepTextsLayout else None,
                writeMibs=writeMibsFlag,
                ignoreErrors=ignoreErrorsFlag,
                repairImports=repairImportsFlag,
            ),
        )

        safe = {}
        for x in sorted(processed):
            if processed[x] != "failed":
                safe[x] = processed[x]

        if buildIndexFlag:
            mibCompiler.build_index(safe, dryRun=dryrunFlag, ignoreErrors=True)

        if pruneFlag:
            pruned = mibCompiler.prune(dryRun=dryrunFlag, ignoreErrors=ignoreErrorsFlag)

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    else:
        if verboseFlag:
            createdVerb = "Would be c" if dryrunFlag else "C"
            createdMibs = ", ".join(
                [
                    f"{x}{f' ({processed[x].alias})' if x != processed[x].alias else ''}"
                    for x in sorted(processed)
                    if processed[x] == "compiled"
                ]
            )
            sys.stdout.write(f"{createdVerb}reated/updated MIBs: {createdMibs}\r\n")

            borrowedVerb = "Would be " if dryrunFlag else ""
            borrowedMibs = ", ".join(
                [f"{x} ({processed[x].path})" for x in sorted(processed) if processed[x] == "borrowed"]
            )
            sys.stdout.write(f"Pre-compiled MIBs {borrowedVerb}borrowed: {borrowedMibs}\r\n")

            sys.stdout.write(
                "Up to date MIBs: " + ", ".join(sorted(x for x in processed if processed[x] == "untouched")) + "\r\n"
            )
            sys.stderr.write(
                "Missing source MIBs: " + "\n ".join(sorted(x for x in processed if processed[x] == "missing")) + "\n"
            )

            sys.stderr.write(
                "Ignored MIBs: " + ", ".join(sorted(x for x in processed if processed[x] == "unprocessed")) + "\r\n"
            )

            repairedMibs = "\n ".join(
                f"{x} ({', '.join(f'{s} from {m}' for s, m in sorted(getattr(processed[x], 'repaired', {}).items()))})"
                for x in sorted(processed)
                if getattr(processed[x], "repaired", None)
            )
            sys.stderr.write(f"Repaired MIBs: {repairedMibs}\n")

            sys.stderr.write(
                "Failed MIBs: "
                + "\n ".join([f"{x} ({processed[x].error})" for x in sorted(processed) if processed[x] == "failed"])
                + "\n"
            )

            if pruneFlag:
                prunedVerb = "Would be " if dryrunFlag else ""
                sys.stdout.write(
                    f"MIBs {prunedVerb}pruned: "
                    + ", ".join(sorted(x for x in pruned if pruned[x] == "pruned"))
                    + "\r\n"
                )
                sys.stderr.write(
                    "Failed to prune: "
                    + "\n ".join([f"{x} ({pruned[x].error})" for x in sorted(pruned) if pruned[x] == "failed"])
                    + "\n"
                )

        exitCode = EX_OK

        if any(x for x in processed.values() if x == "missing"):
            exitCode = EX_MIB_MISSING

        if any(x for x in processed.values() if x == "failed") or any(x for x in pruned.values() if x == "failed"):
            exitCode = EX_MIB_FAILED

        sys.exit(exitCode)
