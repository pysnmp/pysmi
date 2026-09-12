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
from pysmi.corpus.site.crawl import Crawl
from pysmi.corpus.site.theme import load_theme
from pysmi.registry.pen import Registrant, is_pen_registry, load_registry
from pysmi.registry.smi import ArcName, parse_smi_numbers

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
    oidRegistryPaths: list[str] = []

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
        [--oid-registry=<FILE>]
        [--site-template=<FILE>]
        [--site-stylesheet=<FILE>]
        [--site-name=<NAME>]
        [--base-url=<URL>]
        [--site-description=<TEXT>]
        [--page-size=<COUNT>]
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
                index.csv, index-v2.csv, standard.txt, closure.json and
                report.json. core.db and entity.json are not in the
                default layout -- ask for either by name. core.db costs
                a pass nothing else needs; entity.json is only worth
                having with --oid-registry to name its arcs.
        --frozen-index - the snapshot index.csv replays, so that consumers
                keying on the module an OID resolves to keep the answers
                they already have. Absent, index.csv is the ranked index.
        --emit   - produce one named artifact, repeatable. Naming any
                turns off the full layout, so a build can ask for just
                the index or just the JSON. ARTIFACT is one of asn1,
                notexts, texts, json, json-texts, index, index-v2,
                standard, closure, core-db, entity, arcs, site,
                report.
                json-texts is a jsondoc tree with DESCRIPTION and the
                other texts in it, which costs roughly 70% more on disk
                and is what makes the tree the complete machine-readable
                rendering of a module; give it a path of its own to keep
                a lean published tree beside it. json-texts, core-db,
                entity and arcs are not in the default layout -- ask for
                those by name. core-db, entity, arcs, closure and the
                two indexes are projections of the
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
        --oid-registry - a published registry naming OID arcs, as a file,
                repeatable. Which registry it is is read from the file
                rather than from its name. Two are understood: the IANA
                Private Enterprise Numbers registry, which names the arcs
                under 1.3.6.1.4.1 (see --emit=entity), and IANA's
                smi-numbers XML, which names the 1.3.6.1 subtree. Both
                feed --emit=arcs. Taken as an input and never fetched,
                because a corpus is reproducible with the network
                unplugged and a registry that changes daily would end
                that. The enterprise registry is read in its published
                four-line-record form or as the reduced CSV that
                "python -m pysmi.registry" writes. An arc no registry
                names is reported as unnamed rather than guessed at.
        --site-template - an HTML file replacing the page frame
                --emit=site renders into, so a distribution publishing
                this beside its own documentation makes it look like the
                rest of that documentation without forking the generator.
                $name substitution; pysmi.corpus.site.theme lists the
                placeholders a page may use.
        --site-stylesheet - a CSS file replacing the built-in one, for
                the same reason.
        --site-name - what the site's header calls this corpus.
        --base-url - the site's origin and path, which is what makes a
                build a distribution site rather than a subtree somebody
                else will assemble. Given, --emit=site also writes the
                crawl surface: canonical links, JSON-LD, sitemap.xml,
                robots.txt and llms.txt. Without it there is nothing to
                put in a canonical link, and guessing an origin would
                publish a site claiming to live somewhere it does not.
        --site-description - one paragraph saying what this corpus is,
                for llms.txt.
        --page-size - entries per page before a long list splits into
                buckets keyed by the range each covers rather than by
                page number. A corpus of 200 modules and one of 50,000
                want different numbers. The manifest may instead name the
                lists individually, naming browse and entity, since the
                module list is the front door and a registrant's list is
                reached already narrowed to one vendor.
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
                "oid-registry=",
                "site-template=",
                "site-stylesheet=",
                "site-name=",
                "base-url=",
                "site-description=",
                "page-size=",
                "no-bundled-mibs",
                "fail-on-errors",
            ],
        )

    except getopt.GetoptError as exc:
        sys.stderr.write(f"ERROR: {exc}\r\n{helpMessage}\r\n")
        sys.exit(EX_USAGE)

    bundledMibsFlag = True
    emitted: list[str] = []
    sitePage: str | None = None
    siteStylesheet: str | None = None
    siteName: str | None = None
    baseUrl: str | None = None
    siteDescription: str | None = None
    pageSize: int | dict[str, int] | None = None

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

        if opt[0] == "--oid-registry":
            oidRegistryPaths.append(opt[1])

        if opt[0] == "--site-template":
            sitePage = opt[1]

        if opt[0] == "--site-stylesheet":
            siteStylesheet = opt[1]

        if opt[0] == "--site-name":
            siteName = opt[1]

        if opt[0] == "--base-url":
            baseUrl = opt[1]

        if opt[0] == "--site-description":
            siteDescription = opt[1]

        if opt[0] == "--page-size":
            try:
                pageSize = int(opt[1])

            except ValueError:
                sys.stderr.write(
                    f"ERROR: --page-size takes a number, not {opt[1]!r}\r\n"
                )
                sys.exit(EX_USAGE)

            if pageSize < 1:
                sys.stderr.write("ERROR: --page-size is at least 1\r\n")
                sys.exit(EX_USAGE)

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
        oidRegistry, smiRegistry = _registries(oidRegistryPaths)

    except (OSError, error.PySmiError) as exc:
        # A build pointed at a registry that is not there, or at a file that
        # is not one, is misconfigured. Carrying on would emit an index naming
        # nobody, which reads as a corpus registering under arcs nobody
        # allocated.
        sys.stderr.write(f"ERROR: cannot read --oid-registry: {exc}\r\n")
        sys.exit(EX_USAGE)

    # Flags override the manifest, as flags do everywhere else here.
    declared = manifest.site
    sitePage = sitePage or declared.get("template")
    siteStylesheet = siteStylesheet or declared.get("stylesheet")
    siteName = siteName or declared.get("name")
    baseUrl = baseUrl or declared.get("base-url")
    siteDescription = siteDescription or declared.get("description")

    if pageSize is None:
        pageSize = declared.get("page-size")

    try:
        theme = (
            load_theme(sitePage, siteStylesheet, siteName)
            if outputs.site and (sitePage or siteStylesheet or siteName)
            else None
        )

    except error.PySmiError as exc:
        # Named and unreadable, which is a typo in a manifest rather than a
        # reason to publish a whole site in the wrong skin and say nothing.
        sys.stderr.write(f"ERROR: {exc}\r\n")
        sys.exit(EX_USAGE)

    crawl = (
        Crawl(
            base=baseUrl,
            description=siteDescription or "",
            policy=declared.get("crawl") or {},
        )
        if outputs.site and baseUrl
        else None
    )

    try:
        report = CorpusDriver(
            namespaces,
            outputs,
            useBundledMibs=bundledMibsFlag,
            corpusVersion=corpusVersion or None,
            corpusId=corpusId or None,
            oidRegistry=oidRegistry,
            smiRegistry=smiRegistry,
            theme=theme,
            pageSize=pageSize,
            crawl=crawl,
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
    "json-texts": ("json_texts", "json"),
    "index": ("index", "index.csv"),
    "index-v2": ("ranked_index", "index-v2.csv"),
    "standard": ("standard", "standard.txt"),
    "core-db": ("core_db", "core.db"),
    "entity": ("entity", "entity.json"),
    "arcs": ("arcs", "arcs.json"),
    "closure": ("closure", "closure.json"),
    # The site's trees are named so that nothing collides with a corpus path,
    # which is only worth anything if they share a directory with one: a
    # reader browsing mib/IF-MIB/ and a consumer fetching asn1/IF-MIB are
    # looking at the same publication. So the default path is the output
    # directory itself rather than a subdirectory of it. See pysnmp/pysmi#276
    # and pysnmp/mibs#409.
    "site": ("site", ""),
    "report": ("report", "report.json"),
}

#: Artifacts a build produces only when asked for by name.
#:
#: The default layout is what pysnmp/mibs publishes, and the corpus database is
#: not part of it: building one costs a pass over the whole jsondoc tree that
#: nothing else needs, so a plain ``mibcorpus`` run must not pay for it.
#:
#: ``json-texts`` is not either. The default layout is the lean ``json/`` the
#: corpus has always published, and a build that wants the texts says so --
#: they cost roughly 70% more on disk.
#:
#: The entity index is opt-in for a third reason. It is cheap, but it is only
#: worth having with ``--oid-registry`` to name the arcs, and that is an input
#: the caller supplies; emitting it by default would publish an index naming
#: nobody, which reads as a corpus registering under arcs that were never
#: allocated.
#:
#: The arc name index is opt-in for the same reason as the entity index,
#: and for one more: it is the registration tree, which a corpus that only
#: wants its modules has no use for.
_OPT_IN: Final = frozenset({"core-db", "json-texts", "entity", "arcs", "site"})


def _registries(
    paths: list[str],
) -> "tuple[dict[int, Registrant], dict[str, ArcName]]":
    """Read every ``--oid-registry`` file, each as whatever it turns out to be.

    Which registry a file is comes from its content rather than from its name:
    a snapshot a repository commits is called whatever that repository calls
    it, and asking the caller to say which is which is asking them to repeat
    something the file already states.

    Args:
        paths: the files named on the command line, in order.

    Returns:
        ``(enterprises, smi)`` -- the enterprise registrations and the arc
        names, either of which may be empty.

    Raises:
        OSError: a file cannot be read.
        PySmiError: a file is not a registry this knows.
    """
    enterprises: dict[int, Registrant] = {}
    smi: dict[str, ArcName] = {}

    for path in paths:
        with open(path, encoding="utf-8", errors="replace", newline="") as fileObj:
            text = fileObj.read()

        if is_pen_registry(text):
            enterprises.update(load_registry(path))

        elif "<registry" in text[:4096]:
            smi.update(parse_smi_numbers(text))

        else:
            raise error.PySmiError(
                f"{path} is not a registry this release reads; expected the "
                f"IANA Private Enterprise Numbers registry or smi-numbers XML"
            )

    return enterprises, smi


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

    # Both may be named -- a build publishing a lean tree and rendering from a
    # complete one wants exactly that -- but not into one directory, where the
    # second pass would overwrite the first and which of them survived would
    # depend on the order this loop happened to run in.
    if outputs.json and outputs.json == outputs.json_texts:
        raise error.PySmiError(
            "--emit names json and json-texts at the same path; give one of "
            "them a path of its own, or name only json-texts to have that "
            "tree carry the texts"
        )

    return outputs


def _summarize(report: "CorpusReport") -> None:
    """Print what the build did, in the shape a build log wants."""
    sys.stdout.write(
        f"{len(report.namespaces)} namespaces, {report.staged} modules staged\r\n"
    )

    for destination, statuses in sorted(report.statuses.items()):
        counts = ", ".join(f"{k} {v}" for k, v in sorted(statuses.items()))
        sys.stdout.write(f"{destination}: {counts}\r\n")

    if report.entity:
        sys.stdout.write(
            f"enterprise arcs: {report.entity['arcs']}, "
            f"{report.entity['named']} named, "
            f"{report.entity['unregistered']} unregistered\r\n"
        )

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
