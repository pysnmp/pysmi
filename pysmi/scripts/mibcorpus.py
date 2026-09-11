#!/usr/bin/env python3
#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
# SNMP SMI/MIB corpus build tool
#
"""The *mibcorpus* tool: build a whole MIB corpus, reproducibly.

``mibdump`` compiles the modules it is given. A corpus build is a different
shape of job: it takes a *set of source namespaces* and produces every
artifact the corpus publishes, with the property that two runs over the same
inputs produce the same bytes. That is what this tool is, and
:py:mod:`pysmi.corpus.driver` is what it drives.
"""

import getopt
import logging
import os
import sys
from typing import Final

from pysmi import debug, error
from pysmi.corpus.driver import (
    CorpusDriver,
    CorpusOutputs,
    CorpusReport,
    check_expectations,
)
from pysmi.corpus.namespace import Manifest, Namespace, read_manifest

# sysexits.h
EX_OK: Final = 0
EX_USAGE: Final = 64
EX_DATAERR: Final = 65
EX_SOFTWARE: Final = 70
EX_MIB_FAILED: Final = 79


def start() -> None:
    """Run the corpus build named by the command line."""
    manifestPath = ""
    outputDirectory = "output"
    frozenIndex = ""
    verboseFlag = True
    failOnErrorsFlag = False
    namespaceArgs: list[tuple[str, bool]] = []
    outputs = CorpusOutputs()
    explicitOutputs = False
    corpusVersion = ""
    corpusId = ""

    helpMessage = """\
    Usage: {} [--help]
        [--version]
        [--quiet]
        [--debug=<{}>]
        [--manifest=<FILE>]
        [--namespace=<TIER>:<NAME>:<SOURCE>]
        [--resolve-namespace=<TIER>:<NAME>:<SOURCE>]
        [--output-directory=<DIRECTORY>]
        [--frozen-index=<FILE>]
        [--emit=<ARTIFACT>[:<PATH>]]
        [--no-bundled-mibs]
        [--fail-on-errors]
    Where:
        --manifest - the JSON file declaring what this corpus is: the
                source namespaces it is built from, in the order that
                breaks ties between two namespaces holding a module of one
                name; optionally an "emit" list naming the artifacts it
                carries; optionally an "expect" object of what must be
                true of the result -- modules, failures and
                namespaces-present -- which is checked after the build and
                exits non-zero naming whatever missed. Paths in it are
                relative to the manifest's directory.
        --namespace - declare one namespace on the command line instead
                of, or in addition to, a manifest. SOURCE is a directory,
                or "package:" and a dotted package name for the modules
                a Python package ships. TIER is one of standard, draft,
                vendor, and is what tells the OID index that a standard
                module owns an arc a vendor module also defines.
        --resolve-namespace - declare a namespace the corpus resolves
                against but does not carry. Its modules supply what the
                published ones import and reach no output tree, so a
                corpus can be built for a runtime that already has the
                standard modules -- pysmi bundles 210 of them -- without
                every vendor module that imports SNMPv2-SMI failing.
                Same in a manifest as "publish": false.
        --output-directory - where the artifacts go, laid out as the
                published corpus is: asn1/, notexts/, texts/, json/,
                index.csv, index-v2.csv, standard.txt and report.json.
                core.db is not in the default layout -- ask for it by
                name, because building it costs a pass nothing else needs.
        --frozen-index - the snapshot index.csv replays, so that consumers
                keying on the module an OID resolves to keep the answers
                they already have. Absent, index.csv is the ranked index.
        --emit   - produce one named artifact, repeatable. Naming any
                turns off the full layout, so a build can ask for just
                the index or just the JSON. ARTIFACT is one of asn1,
                notexts, texts, json, index, index-v2, standard, core-db,
                report. core-db and the two indexes are projections of the
                jsondoc tree; a build asking for one without asking for
                json gets a tree staged in a temporary directory and
                removed afterwards, so the corpus carries only what was
                named. Emit json to keep it, with a path of its own to say
                where. Overrides the manifest's own emit set, as a flag
                overrides a file.
        --corpus-version - what to stamp core.db as, recorded verbatim in
                its metadata. Nothing is invented when this is absent: a
                version taken from a clock or from a checkout would make
                two builds of one source tree differ, and the database is
                written to be reproducible. A publisher passes its release.
        --corpus-id - a stable name for the corpus core.db is a build of,
                so a consumer holding two can tell whose each one is.
        --fail-on-errors - exit non-zero when any module failed to
                compile. Off by default: a corpus of MIBs nobody controls
                always carries some that do not compile, and the report
                names them.
    """.format(os.path.basename(sys.argv[0]), "|".join(sorted(debug.flagMap)))

    try:
        opts, _ = getopt.getopt(
            sys.argv[1:],
            "hv",
            [
                "help",
                "version",
                "quiet",
                "debug=",
                "manifest=",
                "namespace=",
                "resolve-namespace=",
                "output-directory=",
                "frozen-index=",
                "emit=",
                "corpus-version=",
                "corpus-id=",
                "no-bundled-mibs",
                "fail-on-errors",
            ],
        )

    except getopt.GetoptError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    bundledMibsFlag = True
    emitted: list[str] = []

    for opt in opts:
        if opt[0] in ("-h", "--help"):
            sys.stderr.write(f"""\
    Synopsis:
    Build a MIB corpus from a declared set of source namespaces
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

        if opt[0] == "--manifest":
            manifestPath = opt[1]

        if opt[0] == "--namespace":
            namespaceArgs.append((opt[1], True))

        if opt[0] == "--resolve-namespace":
            namespaceArgs.append((opt[1], False))

        if opt[0] == "--output-directory":
            outputDirectory = opt[1]

        if opt[0] == "--frozen-index":
            frozenIndex = opt[1]

        if opt[0] == "--emit":
            emitted.append(opt[1])
            explicitOutputs = True

        if opt[0] == "--corpus-version":
            corpusVersion = opt[1]

        if opt[0] == "--corpus-id":
            corpusId = opt[1]

        if opt[0] == "--no-bundled-mibs":
            bundledMibsFlag = False

        if opt[0] == "--fail-on-errors":
            failOnErrorsFlag = True

    if verboseFlag:
        logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)

    namespaces: list[Namespace] = []
    manifest = Manifest(namespaces=[])

    try:
        if manifestPath:
            manifest = read_manifest(manifestPath)
            namespaces.extend(manifest.namespaces)

        for spec, publish in namespaceArgs:
            namespaces.append(_parse_namespace(spec, publish=publish))

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    if not namespaces:
        sys.stderr.write(
            f"ERROR: no source namespaces; pass --manifest or --namespace\r\n{helpMessage}\r\n"
        )
        sys.exit(EX_USAGE)

    # A flag overrides a file. Absent both, the full published layout.
    selected = emitted if explicitOutputs else manifest.emit

    try:
        outputs = _outputs_for(outputDirectory, selected)

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    outputs.frozen_index = frozenIndex or None

    try:
        report = CorpusDriver(
            namespaces,
            outputs,
            useBundledMibs=bundledMibsFlag,
            corpusVersion=corpusVersion or None,
            corpusId=corpusId or None,
        ).run()

    except error.PySmiError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_SOFTWARE)

    if verboseFlag:
        _summarize(report)

    missed = check_expectations(manifest.expect, report)

    if missed:
        sys.stderr.write(
            "ERROR: the build is not what the manifest says this corpus is:\r\n"
        )
        sys.stderr.writelines(f"    {x}\r\n" for x in missed)
        sys.exit(EX_DATAERR)

    failures = sum(len(x) for x in report.failed.values())

    if failures and failOnErrorsFlag:
        sys.exit(EX_MIB_FAILED)

    sys.exit(EX_OK)


def _parse_namespace(spec: str, *, publish: bool = True) -> Namespace:
    """One ``--namespace`` argument, as ``TIER:NAME:SOURCE``.

    A source carrying a ``package:`` prefix keeps it, so
    ``standard:base:package:pysmi.mibs.asn1`` reads the way it looks.

    Keyword Args:
        publish: whether the corpus carries this namespace's modules.
            ``--resolve-namespace`` is the same argument with this off.
    """
    parts = spec.split(":", 2)

    if len(parts) != 3:
        raise error.PySmiError(f"--namespace takes TIER:NAME:SOURCE, not {spec!r}")

    tier, name, source = parts

    return Namespace(name=name, source=source, tier=tier, publish=publish)


#: Artifact names ``--emit`` takes, mapped to the field each one sets and the
#: path it defaults to under ``--output-directory``.
_ARTIFACTS: Final = {
    "asn1": ("asn1", "asn1"),
    "notexts": ("notexts", "notexts"),
    "texts": ("texts", "texts"),
    "json": ("json", "json"),
    "index": ("index", "index.csv"),
    "index-v2": ("ranked_index", "index-v2.csv"),
    "standard": ("standard", "standard.txt"),
    "core-db": ("core_db", "core.db"),
    "report": ("report", "report.json"),
}

#: Artifacts a build produces only when asked for by name.
#:
#: The default layout is what pysnmp/mibs publishes, and the corpus database is
#: not part of it: building one costs a pass over the whole jsondoc tree that
#: nothing else needs, so a plain ``mibcorpus`` run must not pay for it.
_OPT_IN: Final = frozenset({"core-db"})


def _outputs_for(directory: str, emitted: list[str] | None) -> CorpusOutputs:
    """Where each artifact goes: the full published layout, or a subset.

    Args:
        directory: the build directory
        emitted: the artifacts asked for by name, or ``None`` for all of them

    Returns:
        The outputs, with every artifact not asked for left unset.
    """
    outputs = CorpusOutputs()

    if emitted is None:
        for artifact, (attribute, default) in _ARTIFACTS.items():
            if artifact in _OPT_IN:
                continue

            setattr(outputs, attribute, os.path.join(directory, default))

        return outputs

    for spec in emitted:
        artifact, _, path = spec.partition(":")

        try:
            attribute, default = _ARTIFACTS[artifact]

        except KeyError:
            raise error.PySmiError(
                f"unknown --emit artifact {artifact!r}; expected one of "
                f"{', '.join(sorted(_ARTIFACTS))}"
            ) from None

        setattr(outputs, attribute, path or os.path.join(directory, default))

    return outputs


def _summarize(report: "CorpusReport") -> None:
    """Print what the build did, in the shape a build log wants."""
    sys.stdout.write(
        f"{len(report.namespaces)} namespaces, {report.staged} modules staged\r\n"
    )

    for destination, statuses in sorted(report.statuses.items()):
        counts = ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))
        sys.stdout.write(f"{destination}: {counts}\r\n")

    for destination, failed in sorted(report.failed.items()):
        if failed:
            sys.stdout.write(
                f"{destination}: {len(failed)} modules failed to compile\r\n"
            )

    if report.shadowed:
        sys.stdout.write(
            f"{len(report.shadowed)} modules held by more than one namespace\r\n"
        )

    if report.nodes:
        sys.stdout.write(
            f"nodes: {report.nodes['defined']} defined, "
            f"{report.nodes['distinct']} after dedup, "
            f"across {report.nodes['modules']} modules\r\n"
        )

    if report.index:
        sys.stdout.write(
            ", ".join(f"index {k} {v}" for k, v in sorted(report.index.items()))
            + "\r\n"
        )

    sys.stdout.write(f"total {report.seconds.get('total', 0):.1f}s\r\n")


if __name__ == "__main__":
    start()
