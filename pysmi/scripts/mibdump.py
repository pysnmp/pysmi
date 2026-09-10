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
from dataclasses import dataclass
from typing import Any, Final

from pysmi import debug, error
from pysmi.borrower import AnyFileBorrower, PyFileBorrower
from pysmi.borrower.base import AbstractBorrower
from pysmi.cache.base import AbstractParseCache
from pysmi.cache.memory import InMemoryParseCache
from pysmi.codegen import JsonCodeGen, NullCodeGen, PySnmpCodeGen
from pysmi.codegen.base import AbstractCodeGen
from pysmi.compiler import (
    PRECEDENCE_NO_REVISION,
    MibCompiler,
    bundled_mib_names,
)
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import getReadersFromUrls
from pysmi.reader.base import AbstractReader
from pysmi.searcher import (
    AnyFileSearcher,
    PyFileSearcher,
    PyPackageSearcher,
    StubSearcher,
)
from pysmi.searcher.base import AbstractSearcher
from pysmi.writer import CallbackWriter, FileWriter, PyFileWriter

_JSON_EXT: Final = ".json"

# sysexits.h
EX_OK: Final = 0
EX_USAGE: Final = 64
EX_SOFTWARE: Final = 70
EX_MIB_MISSING: Final = 79
EX_MIB_FAILED: Final = 79


@dataclass(frozen=True)
class _Destination:
    """One output format written to one directory, as ``--emit`` names it."""

    #: ``pysnmp``, ``json`` or ``null``.
    format: str
    #: Where that format is written. ``None`` means the format's own default.
    directory: str | None
    #: Whether DESCRIPTION and the other texts are carried into the output.
    genTexts: bool

    def __str__(self) -> str:
        """The spelling ``--emit`` takes, which labels this run's reports."""
        return f"{self.format}{'+texts' if self.genTexts else ''}:{self.directory}"


def _parse_emit(spec: str) -> "_Destination":
    """One ``--emit`` argument, as ``FORMAT[+texts][:DIRECTORY]``.

    The directory is optional so that ``--emit=json`` still means the format's
    own default location, the same as ``--destination-format=json`` alone.
    """
    token, _, directory = spec.partition(":")
    fmt, plus, suffix = token.partition("+")

    if plus and suffix != "texts":
        raise error.PySmiError(f"unknown --emit modifier: +{suffix}")

    return _Destination(fmt, directory or None, bool(plus))


def _enumerate_sources(sourceReaders: list["AbstractReader"]) -> list[str]:
    """Every module name the given sources can be listed for, sorted.

    Only the sources themselves are asked, not the bundled base MIBs: the
    bundle is what resolves the imports of whatever is built, never the
    thing to build. A source that cannot be enumerated -- a web server
    given a ``@mib@`` URL template -- contributes nothing.

    The readers passed in are the ones the compile then runs against, so a
    module found in a file named for something else stays fetchable: the
    scan records where it is on the reader that will be asked for it.
    """
    seen: set[str] = set()

    for reader in sourceReaders:
        seen.update(reader.list_mibs())

    return sorted(seen)


def _compile_to(
    destination: "_Destination",
    options: dict[str, Any],
    parseCache: AbstractParseCache,
    labelled: bool,
) -> "tuple[dict[str, Any], dict[str, Any]]":
    """Compile one destination; return what was processed and what was pruned.

    Each destination gets its own :py:class:`~pysmi.compiler.MibCompiler`,
    because a compiler carries one code generator and one writer. What they
    share is *parseCache*, so the ASN.1 is parsed once for the whole run
    rather than once per destination -- three quarters of the work when a
    build asks for pysnmp with texts, pysnmp without, and JSON, as
    ``pysnmp/mibs`` does.

    The per-format defaults below fill in whatever list the caller left empty.
    They are taken from a copy each time, so a second destination starts from
    what the caller passed rather than from what the first destination
    defaulted to -- otherwise JSON would inherit pysnmp's stub list.
    """
    dstFormat = destination.format
    dstDirectory = destination.directory
    genMibTextsFlag = destination.genTexts

    mibSources: list[str] = list(options["mibSources"])
    # Built once for the run rather than per destination, so every
    # destination sees the same directory listings and the same index --
    # including what --build-all learned while enumerating them.
    sourceReaders: list[AbstractReader] = options["sourceReaders"]
    mibSearchers: list[str] = list(options["mibSearchers"])
    mibStubs: list[str] = list(options["mibStubs"])
    mibBorrowers: list[tuple[str, bool]] = list(options["mibBorrowers"])
    inputMibs: list[str] = list(options["inputMibs"])

    helpMessage = options["helpMessage"]
    cacheDirectory = options["cacheDirectory"]
    keepTextsLayout = options["keepTextsLayout"]
    doFuzzyMatchingFlag = options["doFuzzyMatchingFlag"]
    nodepsFlag = options["nodepsFlag"]
    rebuildFlag = options["rebuildFlag"]
    pruneFlag = options["pruneFlag"]
    bundledMibsFlag = options["bundledMibsFlag"]
    preferMibSourceFlag = options["preferMibSourceFlag"]
    baseMibsFlag = options["baseMibsFlag"]
    dryrunFlag = options["dryrunFlag"]
    pyCompileFlag = options["pyCompileFlag"]
    pyOptimizationLevel = options["pyOptimizationLevel"]
    ignoreErrorsFlag = options["ignoreErrorsFlag"]
    buildIndexFlag = options["buildIndexFlag"]
    writeMibsFlag = options["writeMibsFlag"]
    repairImportsFlag = options["repairImportsFlag"]
    strictSourcesFlag = options["strictSourcesFlag"]
    verboseFlag = options["verboseFlag"]

    if verboseFlag and labelled:
        sys.stderr.write(f"=== {destination} ===\r\n")

    if not dstFormat:
        dstFormat = "pysnmp"

    # Base MIBs taken off the stub list, so one is compiled and written out
    # like any other module wherever something imports it. The whole eligible
    # set, not the subset a given run reaches -- which of them were written is
    # what the created/updated line reports. Only the JSON format fills this
    # in; see the branch below.
    eligibleBaseMibs: list[str] = []

    if dstFormat == "pysnmp":
        if not mibSearchers:
            mibSearchers = list(PySnmpCodeGen.defaultMibPackages)

        if not mibStubs:
            mibStubs = [
                x for x in PySnmpCodeGen.baseMibs if x not in PySnmpCodeGen.fakeMibs
            ]

        if not mibBorrowers:
            mibBorrowers = [
                ("https://pysnmp.github.com:443/mibs/notexts/@mib@", False),
                ("https://pysnmp.github.com:443/mibs/fulltexts/@mib@", True),
            ]

        if not dstDirectory:
            dstDirectory = os.path.expanduser("~")
            if sys.platform[:3] == "win":
                dstDirectory = os.path.join(
                    dstDirectory, "PySNMP Configuration", "mibs"
                )
            else:
                dstDirectory = os.path.join(dstDirectory, ".pysnmp", "mibs")

        # Compiler infrastructure

        borrowers: list[AbstractBorrower] = [
            PyFileBorrower(x[1], genTexts=mibBorrowers[x[0]][1])
            for x in enumerate(
                getReadersFromUrls(*[m[0] for m in mibBorrowers], lowcaseMatching=False)
            )
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

            if baseMibsFlag and bundledMibsFlag:
                # Nothing supplies a JSON SNMPv2-TC the way pysnmp supplies a
                # Python one, so stubbing the base MIBs leaves a destination
                # directory that cannot resolve the DisplayString half the
                # modules in it import. Compile them instead, from the copies
                # pysmi bundles -- and only those, since the rest of the stub
                # list would then have to be found somewhere.
                bundled = bundled_mib_names(MibCompiler.bundledMibsPackage)

                eligibleBaseMibs = [x for x in mibStubs if x in bundled]
                mibStubs = [x for x in mibStubs if x not in bundled]

        if not mibBorrowers:
            mibBorrowers = [
                ("https://pysnmp.github.io:443/mibs/json/notexts/@mib@", False),
                ("https://pysnmp.github.io:443/mibs/fulltexts/@mib@", True),
            ]

        if not dstDirectory:
            dstDirectory = os.path.join(".")

        # Compiler infrastructure

        borrowers = [
            AnyFileBorrower(x[1], genTexts=mibBorrowers[x[0]][1]).set_options(
                exts=[_JSON_EXT]
            )
            for x in enumerate(
                getReadersFromUrls(*[m[0] for m in mibBorrowers], lowcaseMatching=False)
            )
        ]

        searchers = [
            AnyFileSearcher(dstDirectory).set_options(exts=[_JSON_EXT]),
            StubSearcher(*mibStubs),
        ]

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
            for x in enumerate(
                getReadersFromUrls(*[m[0] for m in mibBorrowers], lowcaseMatching=False)
            )
        ]

        fileWriter = CallbackWriter(lambda *x: None)

    else:
        sys.stderr.write(
            f"ERROR: unknown destination format: {dstFormat}\r\n{helpMessage}\r\n"
        )
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
    Search pysmi's bundled base MIBs, newest revision winning: {}
    Prefer --mib-source where no revision decides: {}
    Base MIBs eligible to be written out from the bundle: {}
    Rebuild MIBs regardless of age: {}
    Prune stored MIBs with no remaining source: {}
    Dry run mode: {}
    Create/update MIBs: {}
    Byte-compile Python modules: {} (optimization level {})
    Report a failed MIB as an error: {}
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
                (preferMibSourceFlag and "yes") or "no",
                ", ".join(sorted(eligibleBaseMibs)) or "none",
                (rebuildFlag and "yes") or "no",
                (pruneFlag and "yes") or "no",
                (dryrunFlag and "yes") or "no",
                (writeMibsFlag and "yes") or "no",
                (dstFormat == "pysnmp" and pyCompileFlag and "yes") or "no",
                (dstFormat == "pysnmp" and pyOptimizationLevel and "yes") or "no",
                (ignoreErrorsFlag and "no") or "yes",
                (buildIndexFlag and "yes") or "no",
                (genMibTextsFlag and "yes") or "no",
                (keepTextsLayout and "yes") or "no",
                (doFuzzyMatchingFlag and "yes") or "no",
            )
        )

    # Initialize compiler infrastructure

    mibCompiler = MibCompiler(
        SmiV1CompatParser(tempdir=cacheDirectory),
        codeGenerator,
        fileWriter,
        useBundledMibs=bundledMibsFlag,
        preferConfiguredSources=preferMibSourceFlag,
        parseCache=parseCache,
    )

    pruned = {}

    try:
        mibCompiler.add_sources(*sourceReaders)

        mibCompiler.add_searchers(*searchers)

        mibCompiler.add_borrowers(*borrowers)

        processed = mibCompiler.compile(
            *inputMibs,
            noDeps=nodepsFlag,
            rebuild=rebuildFlag,
            dryRun=dryrunFlag,
            genTexts=genMibTextsFlag,
            textFilter=(lambda symbol, text: text) if keepTextsLayout else None,
            writeMibs=writeMibsFlag,
            ignoreErrors=ignoreErrorsFlag,
            repairImports=repairImportsFlag,
            strictSources=strictSourcesFlag,
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
                [
                    f"{x} ({processed[x].path})"
                    for x in sorted(processed)
                    if processed[x] == "borrowed"
                ]
            )
            sys.stdout.write(
                f"Pre-compiled MIBs {borrowedVerb}borrowed: {borrowedMibs}\r\n"
            )

            sys.stdout.write(
                "Up to date MIBs: "
                + ", ".join(sorted(x for x in processed if processed[x] == "untouched"))
                + "\r\n"
            )
            sys.stderr.write(
                "Missing source MIBs: "
                + "\n ".join(sorted(x for x in processed if processed[x] == "missing"))
                + "\n"
            )

            sys.stderr.write(
                "Omitted MIBs (they import a failed MIB): "
                + ", ".join(
                    sorted(x for x in processed if processed[x] == "unprocessed")
                )
                + "\r\n"
            )

            repairedMibs = "\n ".join(
                f"{x} ({', '.join(f'{s} from {m}' for s, m in sorted(getattr(processed[x], 'repaired', {}).items()))})"
                for x in sorted(processed)
                if getattr(processed[x], "repaired", None)
            )
            sys.stderr.write(f"Repaired MIBs: {repairedMibs}\n")

            # A module resolved to a copy other than the one the caller
            # thought they configured is worth more than a line in the
            # summary: it is why an upgrade of pysmi can change compiled
            # output that no --mib-source change explains. Say which copy
            # won, which rule made it win, and how to have it the other way.
            bundledPrefix = f"package://{mibCompiler.bundledMibsPackage}/"

            for mibname in sorted(processed):
                shadowed = getattr(processed[mibname], "shadowed", None)

                if not shadowed:
                    continue

                fromBundle = processed[mibname].path.startswith(bundledPrefix)
                precedence = getattr(processed[mibname], "precedence", "")

                if fromBundle:
                    headline = (
                        f"WARNING: {mibname} resolved to pysmi's bundled copy, "
                        f"not to --mib-source"
                    )
                    # Telling someone to ship a newer revision is no help for
                    # a module that has none to carry, which is the case for
                    # 32 of the 210 bundled ones.
                    remedy = (
                        "pass --prefer-mib-source, or --no-bundled-mibs"
                        if precedence == PRECEDENCE_NO_REVISION
                        else (
                            "give your copy a newer MODULE-IDENTITY revision, or pass "
                            "--prefer-mib-source, or --no-bundled-mibs"
                        )
                    )

                else:
                    headline = f"NOTE: {mibname} was found in more than one source"
                    remedy = (
                        "give the --mib-source you want first, or pass "
                        "--strict-sources to fail instead of choosing"
                    )

                sys.stderr.write(
                    f"{headline}\n"
                    f"    used        {processed[mibname].path}\n"
                    f"    passed over {', '.join(shadowed)}\n"
                    f"    decided by  {precedence}\n"
                    f"    to change   {remedy}\n"
                )

            shadowedMibs = ", ".join(
                f"{x} (used {processed[x].path}, passed over {', '.join(processed[x].shadowed)},"
                f" by {getattr(processed[x], 'precedence', '')})"
                for x in sorted(processed)
                if getattr(processed[x], "shadowed", None)
            )
            sys.stderr.write(f"MIBs found in more than one source: {shadowedMibs}\n")

            sys.stderr.write(
                "Failed MIBs: "
                + "\n ".join(
                    [
                        f"{x} ({processed[x].error})"
                        for x in sorted(processed)
                        if processed[x] == "failed"
                    ]
                )
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
                    + "\n ".join(
                        [
                            f"{x} ({pruned[x].error})"
                            for x in sorted(pruned)
                            if pruned[x] == "failed"
                        ]
                    )
                    + "\n"
                )

    return processed, pruned


def start() -> None:
    """Entry point of the ``mibdump`` command.

    Parses the command line, compiles the requested MIBs and reports what
    happened. Exits with a ``sysexits.h`` status.
    """
    # Defaults
    verboseFlag = True
    mibSources: list[str] = []
    doFuzzyMatchingFlag = True
    mibSearchers: list[str] = []
    mibStubs: list[str] = []
    mibBorrowers: list[tuple[str, bool]] = []
    dstFormat = None
    dstDirectory: str | None = None
    emitSpecs: list[str] = []
    cacheDirectory = ""
    nodepsFlag = False
    rebuildFlag = False
    buildAllFlag = False
    pruneFlag = False
    bundledMibsFlag = True
    preferMibSourceFlag = False
    baseMibsFlag = True
    dryrunFlag = False
    genMibTextsFlag = False
    keepTextsLayout = False
    pyCompileFlag = True
    pyOptimizationLevel = 0
    ignoreErrorsFlag = False
    buildIndexFlag = False
    writeMibsFlag = True
    repairImportsFlag = True
    strictSourcesFlag = False

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
        [--emit=<FORMAT>[+texts][:<DIRECTORY>]]
        [--cache-directory=<DIRECTORY>]
        [--disable-fuzzy-source]
        [--no-dependencies]
        [--no-bundled-mibs]
        [--prefer-mib-source]
        [--no-base-mibs]
        [--no-python-compile]
        [--python-optimization-level]
        [--ignore-errors]
        [--build-index]
        [--build-all]
        [--rebuild]
        [--prune]
        [--dry-run]
        [--no-mib-writes]
        [--generate-mib-texts]
        [--keep-texts-layout]
        [--strict-imports]
        [--strict-sources]
        <MIB-NAME> [MIB-NAME [...]]]
    Where:
        URI      - file, zip, http, https schemes are supported.
                Use @mib@ placeholder token in URI to refer directly to
                the required MIB module when source does not support
                directory listing (e.g. HTTP).
        FORMAT   - pysnmp, json, null
        --emit   - write one format to one directory, repeatable, so that
                every format asked for is produced from a single read of
                the sources rather than one run each. Suffix the format
                with +texts for that destination to carry DESCRIPTION and
                the other texts; --generate-mib-texts is the whole-run
                spelling. Cannot be combined with --destination-format
                or --destination-directory.
        --build-all - compile every MIB module the local --mib-source
                trees hold, instead of the modules named on the command
                line. The module names come from the headers in the text
                rather than from the file names, so a module in a file
                named for something else is still built, under the name
                it declares. A source that cannot be listed -- a web
                server answering a @mib@ URL template -- contributes
                nothing, and neither do the bundled base MIBs: they are
                there to resolve what the built modules import. Naming
                modules as well is an error, since the two say different
                things about what to build.
        --prune  - remove previously stored output whose source MIB no
                longer exists in any configured source. Runs without
                MIB-NAME arguments; deletes unless combined with
                --dry-run.
        --no-bundled-mibs - do not use pysmi's own bundled copies of the
                bundled base MIBs (SNMPv2-SMI and similar) at all. The
                bundle is not a last-resort fallback: it is consulted
                ahead of --mib-source, and where both have one of the
                210 bundled modules the newer MODULE-IDENTITY
                LAST-UPDATED supplies it -- so a --mib-source carrying a
                newer revision still wins, and one carrying an older or
                undated copy does not. Revisions are only compared across
                sources read locally (file, zip); a remote --mib-source is
                not fetched once a local source has the module, leaving
                the bundled copy in place. Pass this to compile strictly
                from --mib-source, so a base MIB that is missing there
                fails loudly rather than resolving to the bundled copy.
        --prefer-mib-source - keep the bundled base MIBs, but let
                --mib-source supply one wherever the revisions do not
                decide: a module with no MODULE-IDENTITY to compare, or two
                copies carrying the same one. The newest revision still
                wins when every copy found has one. 32 of the 210 bundled
                modules -- SNMPv2-SMI, SNMPv2-TC, SNMPv2-CONF and the other
                SMI and RFC-numbered ones -- have no MODULE-IDENTITY at
                all, so this is what decides them.
        --no-base-mibs - do not write out the base MIBs (SNMPv2-SMI,
                SNMPv2-TC and the rest) that the compiled modules import.
                Only --destination-format=json writes them, and only from
                the bundled copies, so --no-bundled-mibs turns this off
                too; the pysnmp format leaves them stubbed, because pysnmp
                implements those modules itself and a generated copy would
                shadow the implementation. Without this, a JSON
                destination directory resolves every import on its own
                rather than needing the base MIBs from somewhere else.
                Giving --mib-stub explicitly replaces the stub list, for
                either format, and this option is then not consulted at
                all. --no-bundled-mibs is: it drops the bundle as a
                source, so a base MIB the replacement list leaves
                unstubbed has to come from --mib-source or it is missing.
        --strict-imports - fail a MIB that uses an SNMPv2-SMI, SNMPv2-TC or
                SNMPv2-CONF symbol without naming it in IMPORTS, which RFC
                2578 Section 3.2 does not allow. Without this the import is
                supplied, which is the default because the repair is forced:
                the symbol is undefined, unimported, and exactly one base
                module exports it, so there is nothing to guess. Every
                repair is listed on the "Repaired MIBs" line of the report,
                so a supplied import is never silent. Use this when
                validating a MIB rather than consuming one.
        --strict-sources - fail a MIB that more than one source has a
                different copy of. Without this, the precedence above picks
                one and the copies passed over are named on the "MIBs found
                in more than one source" line of the report.""".format(
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
                "emit=",
                "cache-directory=",
                "no-dependencies",
                "no-bundled-mibs",
                "prefer-mib-source",
                "no-base-mibs",
                "no-python-compile",
                "python-optimization-level=",
                "ignore-errors",
                "build-index",
                "rebuild",
                "build-all",
                "prune",
                "dry-run",
                "no-mib-writes",
                "generate-mib-texts",
                "disable-fuzzy-source",
                "keep-texts-layout",
                "strict-imports",
                "strict-sources",
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

        if opt[0] == "--emit":
            emitSpecs.append(opt[1])

        if opt[0] == "--cache-directory":
            cacheDirectory = opt[1]

        if opt[0] == "--no-dependencies":
            nodepsFlag = True

        if opt[0] == "--no-bundled-mibs":
            bundledMibsFlag = False

        if opt[0] == "--prefer-mib-source":
            preferMibSourceFlag = True

        if opt[0] == "--no-base-mibs":
            baseMibsFlag = False

        if opt[0] == "--no-python-compile":
            pyCompileFlag = False

        if opt[0] == "--python-optimization-level":
            try:
                pyOptimizationLevel = int(opt[1])

            except ValueError:
                sys.stderr.write(
                    f"ERROR: known Python optimization levels: -1, 0, 1, 2\r\n{helpMessage}\r\n"
                )
                sys.exit(EX_USAGE)

        if opt[0] == "--ignore-errors":
            ignoreErrorsFlag = True

        if opt[0] == "--build-index":
            buildIndexFlag = True

        if opt[0] == "--rebuild":
            rebuildFlag = True

        if opt[0] == "--build-all":
            buildAllFlag = True

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

        if opt[0] == "--strict-imports":
            repairImportsFlag = False

        if opt[0] == "--strict-sources":
            strictSourcesFlag = True

    if not mibSources:
        mibSources = ["https://pysnmp.github.io:443/mibs/asn1/@mib@"]

    if inputMibs:
        mibSources = (
            sorted(
                {
                    os.path.abspath(os.path.dirname(x))
                    for x in inputMibs
                    if os.path.sep in x
                }
            )
            + mibSources
        )

        inputMibs = [os.path.basename(os.path.splitext(x)[0]) for x in inputMibs]

    # Built here rather than per destination so that every destination reads
    # the sources through the same readers -- sharing their directory
    # listings, and the module index --build-all fills in while enumerating.
    try:
        sourceReaders = list(
            getReadersFromUrls(*mibSources, fuzzyMatching=doFuzzyMatchingFlag)
        )

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    if buildAllFlag and inputMibs:
        sys.stderr.write(
            "ERROR: --build-all compiles what the sources hold; it cannot be "
            f"combined with MIB module names\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    if buildAllFlag:
        inputMibs = _enumerate_sources(sourceReaders)

        if not inputMibs:
            sys.stderr.write(
                "ERROR: --build-all found no MIB modules in "
                f"{', '.join(mibSources)}\r\n"
            )
            sys.exit(EX_MIB_MISSING)

        if verboseFlag:
            sys.stderr.write(
                f"Building {len(inputMibs)} MIB modules found in sources\r\n"
            )

    if not inputMibs and not pruneFlag:
        sys.stderr.write(f"ERROR: MIB modules names not specified\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    if emitSpecs and (dstFormat or dstDirectory):
        sys.stderr.write(
            "ERROR: --emit names a format and a directory itself; it cannot be "
            f"combined with --destination-format or --destination-directory\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    try:
        destinations = [_parse_emit(spec) for spec in emitSpecs] or [
            _Destination(dstFormat or "pysnmp", dstDirectory, genMibTextsFlag)
        ]

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    seen = {destination.directory for destination in destinations}
    if len(seen) != len(destinations):
        sys.stderr.write(
            "ERROR: two --emit destinations write to the same directory, so one "
            f"would overwrite the other\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    options: dict[str, Any] = {
        "mibSources": mibSources,
        "sourceReaders": sourceReaders,
        "mibSearchers": mibSearchers,
        "mibStubs": mibStubs,
        "mibBorrowers": mibBorrowers,
        "inputMibs": inputMibs,
        "helpMessage": helpMessage,
        "cacheDirectory": cacheDirectory,
        "keepTextsLayout": keepTextsLayout,
        "doFuzzyMatchingFlag": doFuzzyMatchingFlag,
        "nodepsFlag": nodepsFlag,
        "rebuildFlag": rebuildFlag,
        "pruneFlag": pruneFlag,
        "bundledMibsFlag": bundledMibsFlag,
        "preferMibSourceFlag": preferMibSourceFlag,
        "baseMibsFlag": baseMibsFlag,
        "dryrunFlag": dryrunFlag,
        "pyCompileFlag": pyCompileFlag,
        "pyOptimizationLevel": pyOptimizationLevel,
        "ignoreErrorsFlag": ignoreErrorsFlag,
        "buildIndexFlag": buildIndexFlag,
        "writeMibsFlag": writeMibsFlag,
        "repairImportsFlag": repairImportsFlag,
        "strictSourcesFlag": strictSourcesFlag,
        "verboseFlag": verboseFlag,
    }

    # One cache for the run, so the sources are parsed once however many
    # formats are asked for. Parsing is about three quarters of a pass, so
    # this is what makes several destinations cost meaningfully less than
    # several invocations.
    parseCache = InMemoryParseCache()

    results = [
        _compile_to(destination, options, parseCache, labelled=len(destinations) > 1)
        for destination in destinations
    ]

    # A defective MIB is an error by default. What it costs is bounded --
    # the module itself and whatever imports it are omitted, and every
    # other module in the run is written either way -- but a build that
    # produced less than it was asked for should say so rather than exit
    # zero. --ignore-errors reports success on the same output, which is
    # what a caller compiling MIBs it does not control wants: the report
    # still names what was dropped, and the caller decides.
    #
    # Every destination compiles the same modules, so one failing anywhere
    # fails the run: a build that wrote JSON but no Python is not a success.
    exitCode = EX_OK

    if not ignoreErrorsFlag:
        for processed, pruned in results:
            if any(x for x in processed.values() if x == "missing"):
                exitCode = EX_MIB_MISSING

            if any(x for x in processed.values() if x == "failed") or any(
                x for x in pruned.values() if x == "failed"
            ):
                exitCode = EX_MIB_FAILED

    sys.exit(exitCode)
