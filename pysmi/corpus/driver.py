#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Building a corpus from many source namespaces, deterministically.

The build this replaces -- ``scripts/vendor.sh`` in pysnmp/mibs -- runs
``mibdump`` once per vendor directory under GNU ``parallel``, each invocation
reading ``output/asn1`` as a dependency source while every other invocation
copies its own sources into that same directory on the way out. Which copy of
a shared dependency a module compiled against therefore depended on
scheduling, and so did the output. Three further defects came with it: the
build resolved missing dependencies from its own last publish over the
network, ``--ignore-errors`` was set on one of the three passes, and the OID
index was built by a separate implementation.

This driver is the same build without those properties:

* **The input set is fixed, ordered and immutable.** Every namespace is
  declared in a manifest and every one of them is a source for the whole
  build, so a module in one namespace resolves the same way whatever order
  the namespaces are processed in. Nothing is written into a directory that
  is a source -- :py:func:`check_disjoint` refuses to start otherwise.
* **Nothing is fetched.** Sources are local directories and Python packages;
  no borrowers are configured. A build with the network unplugged produces
  the same corpus as one without.
* **One compiler per output format, warmed across the whole corpus.** The
  ASN.1 is parsed once for the run rather than once per format per namespace.
* **One error policy.** Every format compiles the same module set and keeps
  going past a defective module, and the run reports what failed rather than
  letting each format subtract a different set silently.

See pysnmp/pysmi#182.
"""

import logging
import os
import tempfile
import time
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pysmi import __version__ as packageVersion
from pysmi import error, jsonio
from pysmi.cache.memory import InMemoryParseCache
from pysmi.codegen.base import AbstractCodeGen
from pysmi.codegen.jsondoc import JsonCodeGen
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.compiler import MibCompiler, MibResolution, bundled_mib_names
from pysmi.corpus import closure as corpus_closure
from pysmi.corpus import db as corpus_db
from pysmi.corpus import index as corpus_index
from pysmi.corpus.namespace import DEFAULT_TIER, TIERS, Namespace
from pysmi.parser import SmiV1CompatParser
from pysmi.reader.base import AbstractReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.package import PackageReader
from pysmi.searcher.anyfile import AnyFileSearcher
from pysmi.searcher.base import AbstractSearcher
from pysmi.searcher.stub import StubSearcher
from pysmi.writer.base import AbstractWriter
from pysmi.writer.callback import CallbackWriter
from pysmi.writer.localfile import FileWriter
from pysmi.writer.pyfile import PyFileWriter

logger = logging.getLogger(__name__)

_JSON_EXT: Final[str] = ".json"

#: Modules left out of ``standard.txt``. The list is a published artifact and
#: this is the shape it has: the build that produced it filtered ``RFC*`` and
#: ``SNMPv2*`` out, so every SNMPv2 module -- ``SNMPv2-MIB`` among them, which
#: holds ``sysDescr`` -- has always been absent. Reproduced rather than
#: corrected: a consumer preloading the list gets what it has always got, and
#: pysnmp/mibs#366 decides the file's fate. See ``tests/artifact-contract.sh``
#: in pysnmp/mibs.
STANDARD_TXT_EXCLUDED_PREFIXES: Final[tuple[str, ...]] = ("RFC", "SNMPv2")


@dataclass(frozen=True)
class Destination:
    """One output format the corpus is emitted in.

    Attributes:
        name: what the report calls this destination.
        format: ``pysnmp`` or ``json``.
        directory: where it is written.
        genTexts: whether DESCRIPTION and the other texts are carried over.
        keepTextsLayout: whether those texts keep their original layout.
    """

    name: str
    format: str
    directory: str
    genTexts: bool = False
    keepTextsLayout: bool = False


@dataclass
class CorpusOutputs:
    """Where a corpus build puts what it produces.

    Every field is optional: a build that wants only an index does not have
    to write Python modules to get one. The defaults are the artifact names
    pysnmp/mibs publishes, so that a build directory laid out that way keeps
    serving the consumers that bind to them.
    """

    #: The published ASN.1 tree: one file per module name, flat, named for
    #: the module. Staged from what the compile resolved, so the ASN.1 beside
    #: a compiled module is the text it was compiled from.
    asn1: str | None = None
    #: pysnmp modules without texts.
    notexts: str | None = None
    #: pysnmp modules with texts, original layout kept.
    texts: str | None = None
    #: jsondoc documents.
    json: str | None = None
    #: jsondoc documents carrying DESCRIPTION and the other texts.
    #:
    #: A tree of its own, so a build may have both: the lean one it publishes,
    #: and a complete one for something that needs the prose. Pointed at the
    #: same directory as :py:attr:`json` it is that tree with the texts in it,
    #: which is the other thing a build may want.
    #:
    #: What ``genTexts`` gates is more than descriptions.
    #: ``JsonCodeGen.gen_module_identity`` puts ``organization`` and
    #: ``contactinfo`` behind the same switch, so a published MODULE-IDENTITY
    #: is ``name``, ``oid``, ``class`` and ``lastupdated`` and nothing else --
    #: ``CISCO-ENTITY-ALARM-MIB`` carries a full CONTACT-INFO block in its
    #: ASN.1 and no trace of it reaches the JSON. Over a 500-module sample,
    #: 90% of modules carry ORGANIZATION and CONTACT-INFO.
    #:
    #: It costs roughly 70% more on disk, which is why it is asked for rather
    #: than assumed. ``keepTextsLayout`` stays off: a JSON consumer generally
    #: wants the text normalised rather than the publisher's line breaks
    #: preserved. See pysnmp/pysmi#277.
    json_texts: str | None = None
    #: The legacy OID index, which replays :py:attr:`frozen_index`.
    index: str | None = None
    #: The ranked OID index, where collisions are resolved by rule.
    ranked_index: str | None = None
    #: The frozen snapshot :py:attr:`index` replays, read as input.
    frozen_index: str | None = None
    #: The standard module list.
    standard: str | None = None
    #: The corpus database: the SMI model laid out for lookup. See
    #: :py:mod:`pysmi.corpus.db`.
    core_db: str | None = None
    #: The transitive import closure per module: the files a consumer needs
    #: in order to load one. See :py:mod:`pysmi.corpus.closure`.
    closure: str | None = None
    #: The build report, as JSON.
    report: str | None = None

    def directories(self) -> list[str]:
        """Every directory this build writes into."""
        dirs = [self.asn1, self.notexts, self.texts, self.json, self.json_texts]
        files = [
            self.index,
            self.ranked_index,
            self.standard,
            self.core_db,
            self.closure,
            self.report,
        ]

        return [x for x in dirs if x] + [
            os.path.dirname(os.path.abspath(x)) for x in files if x
        ]


@dataclass
class CorpusReport:
    """What one corpus build did.

    Written out as JSON, and returned to a caller driving the build in
    process. The failure inventory is the point of it: a corpus built from
    MIBs nobody controls will always carry defective modules, and a build
    that subtracts them silently is how 41% of a corpus came to have JSON
    output and no Python (pysnmp/pysmi#182).
    """

    #: pysmi version that produced this.
    version: str = packageVersion
    #: Which JSON implementation wrote the corpus artifacts. What it wrote
    #: does not depend on this -- ``tests/test_jsonio.py`` holds the
    #: implementations to identical bytes -- but a build being compared
    #: against another is easier to reason about when each says what it
    #: resolved. See :py:mod:`pysmi.jsonio`.
    json: str = jsonio.IMPLEMENTATION
    #: Namespaces built, in declaration order, with their tier and how many
    #: modules each supplied.
    namespaces: list[dict[str, Any]] = field(default_factory=list)
    #: Per destination, how many modules reached each status.
    statuses: dict[str, dict[str, int]] = field(default_factory=dict)
    #: Modules that failed, mapped to the error, per destination. The
    #: inventory of what in the corpus does not compile.
    failed: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Modules dropped because something they import failed, per destination.
    unprocessed: dict[str, list[str]] = field(default_factory=dict)
    #: Modules more than one namespace holds a differing copy of: which file
    #: was used, which were passed over, and which rule decided.
    shadowed: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: Where each published module came from: the namespace that supplied it,
    #: the file read, and that file's digest. :py:attr:`shadowed` is the
    #: origin story for exactly the modules more than one namespace held a
    #: differing copy of, which is a small minority; this is the answer for
    #: the rest. See pysnmp/pysmi#278.
    provenance: dict[str, dict[str, str]] = field(default_factory=dict)
    #: Modules the corpus publishes, counted once however many namespaces
    #: hold one: what compiled, which is what every artifact carries. A
    #: module that failed, and anything that imports it, is not in this
    #: number. Independent of the emit set, which is what lets a manifest
    #: bound it whatever artifacts the build was asked for -- unlike
    #: :py:attr:`staged`, which is zero for a build not writing ASN.1.
    modules: int = 0
    #: Modules staged into the published ASN.1 tree.
    staged: int = 0
    #: Nodes the corpus defines, before and after resolving the OIDs more
    #: than one module defines. pysnmp/pysnmp#196 and pysnmp/pysmi#183 both
    #: want the second number.
    nodes: dict[str, int] = field(default_factory=dict)
    #: Index rows written, and how the legacy index was reconciled with its
    #: frozen snapshot.
    index: dict[str, int] = field(default_factory=dict)
    #: Rows written to the corpus database, by table.
    db: dict[str, int] = field(default_factory=dict)
    #: Import closures written, and how many name a module the corpus does
    #: not hold. The second number is the one to look at: it counts modules
    #: this corpus publishes that nothing here can load.
    closure: dict[str, int] = field(default_factory=dict)
    #: Seconds the build took, by phase.
    seconds: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """This report as plain data, for JSON."""
        return {
            "version": self.version,
            "json": self.json,
            "namespaces": self.namespaces,
            "statuses": self.statuses,
            "failed": self.failed,
            "unprocessed": self.unprocessed,
            "shadowed": self.shadowed,
            "provenance": self.provenance,
            "modules": self.modules,
            "staged": self.staged,
            "nodes": self.nodes,
            "index": self.index,
            "db": self.db,
            "closure": self.closure,
            "seconds": {k: round(v, 3) for k, v in self.seconds.items()},
        }


def check_disjoint(namespaces: list[Namespace], outputs: CorpusOutputs) -> None:
    """Refuse a build that would write into a directory it also reads.

    This is the shared-directory race, stated as a precondition rather than
    left to be noticed: a build whose output is one of its own inputs cannot
    be reproducible, because what it reads then depends on how far it has
    got. It is not a race only under ``parallel`` -- serially it is an
    ordering dependency, which is the same defect with a stable outcome.

    Args:
        namespaces: the input set
        outputs: where the build writes

    Raises:
        PySmiError: an output directory is, contains, or is contained by a
            source directory.
    """
    sources = {
        os.path.abspath(x.source): x.name for x in namespaces if not x.is_package
    }

    for directory in outputs.directories():
        target = os.path.abspath(directory)

        for source, name in sources.items():
            if (
                target == source
                or _contains(source, target)
                or _contains(target, source)
            ):
                raise error.PySmiError(
                    f"output directory {target} overlaps source namespace "
                    f"{name} at {source}; a corpus cannot be built from its "
                    f"own output"
                )


def _contains(parent: str, child: str) -> bool:
    """Whether *child* is inside *parent*."""
    return child.startswith(parent.rstrip(os.sep) + os.sep)


class CorpusDriver:
    """Builds a corpus from a declared set of source namespaces.

    Args:
        namespaces: the input set, in the order that breaks precedence ties
        outputs: where the artifacts go

    Keyword Args:
        useBundledMibs: register pysmi's bundled base MIBs as a source, so
            that a corpus of vendor modules resolves ``SNMPv2-SMI`` and its
            neighbours without the caller having to supply them. A namespace
            may name the bundle itself -- ``package:pysmi.mibs.asn1`` -- when
            the corpus should also *publish* those modules, which is a
            different question from resolving against them.
        rebuild: compile every module even where output for it already
            exists. On by default: a corpus is published as a whole, and a
            build that leaves some modules as an earlier run wrote them is
            not the corpus it reports. A module is still compiled only once
            per run however many namespaces ask for it.
        stubs: modules excluded from code generation, per destination format
            -- ``{"pysnmp": [...]}``. The format's own default otherwise,
            which is ``mibdump``'s: the base MIBs, on the grounds that a
            corpus published beside pysnmp does not restate what pysnmp
            already implements. A caller producing the base layer *itself*
            wants a narrower list, since most of those modules generate
            perfectly well and only a few genuinely cannot; see
            ``hatch_build.py``, which is that caller.
    """

    def __init__(
        self,
        namespaces: list[Namespace],
        outputs: CorpusOutputs,
        *,
        useBundledMibs: bool = True,
        rebuild: bool = True,
        stubs: "Mapping[str, Iterable[str]] | None" = None,
        corpusVersion: str | None = None,
        corpusId: str | None = None,
    ) -> None:
        """Create a driver over the given input set."""
        if not namespaces:
            raise error.PySmiError("a corpus needs at least one source namespace")

        if not any(x.publish for x in namespaces):
            raise error.PySmiError(
                "every namespace is declared unpublished; a corpus built from "
                "resolution sources alone would carry nothing"
            )

        check_disjoint(namespaces, outputs)

        self._namespaces = list(namespaces)
        self._outputs = outputs
        self._useBundledMibs = useBundledMibs
        self._rebuild = rebuild
        self._stubs = {k: list(v) for k, v in (stubs or {}).items()}
        #: What to stamp core.db as. Carried rather than derived: a value this
        #: process observed -- a clock, a checkout's describe -- would make two
        #: builds of one source tree differ, which is the property the database
        #: is written to preserve.
        self._corpusVersion = corpusVersion
        self._corpusId = corpusId
        self._parseCache = InMemoryParseCache()
        self._readers: dict[str, AbstractReader] = {
            x.name: self._reader_for(x) for x in self._namespaces
        }
        #: Which namespace each module name came from, for the index tiers.
        self._tierOfModule: dict[str, int] = {}
        self._corpus: dict[
            tuple[str, ...] | None,
            tuple[list[tuple[str, dict[str, Any], int, int]], dict[str, str]],
        ] = {}
        self._modulesOfNamespace: dict[str, list[str]] = {}
        #: Where each module came from, per module selection. Filled by
        #: staging, which resolves every module anyway, and computed on its
        #: own only for a build that asked for provenance without asking for
        #: the ASN.1 tree.
        self._provenance: dict[tuple[str, ...] | None, dict[str, dict[str, str]]] = {}
        #: Namespace name per reader, by identity, so a resolution can say
        #: which namespace supplied it. Two namespaces may be two directories
        #: under one root, so the path alone does not answer it.
        self._namespaceOfReader = {
            id(reader): name for name, reader in self._readers.items()
        }

    @staticmethod
    def _reader_for(namespace: Namespace) -> AbstractReader:
        """The reader serving one namespace.

        Only local sources: a package this process already has installed, or
        a directory on disk. There is deliberately no URL case. A corpus that
        resolved a dependency over the network would be reproducible only for
        as long as the far end kept answering the same way, and where that
        far end is the corpus's own last publish -- which is what the build
        this replaces did -- a bad publish reproduces itself indefinitely.
        """
        if namespace.is_package:
            return PackageReader(namespace.package)

        if "://" in namespace.source:
            raise error.PySmiError(
                f"namespace {namespace.name} names a URL; a corpus is built "
                f"from local sources only"
            )

        if not os.path.isdir(namespace.source):
            raise error.PySmiError(
                f"namespace {namespace.name} names {namespace.source}, "
                f"which is not a directory"
            )

        return FileReader(namespace.source)

    @property
    def _published(self) -> list[Namespace]:
        """The namespaces this corpus carries, in declaration order.

        The rest are resolution sources: they supply what the published
        modules import and contribute nothing to the output.
        """
        return [x for x in self._namespaces if x.publish]

    def _resolve_only_modules(self) -> list[str]:
        """Every module held only by a namespace the corpus does not publish.

        Stubbed in every output format, which is what keeps such a module out
        of the corpus when something published imports it -- the compiler
        compiles and writes a dependency like anything else, so declining to
        ask for it is not enough.

        A module a published namespace also holds is not stubbed: the corpus
        carries it, and where it came from is the precedence rule's business
        rather than this one's.
        """
        published: set[str] = set()
        resolveOnly: set[str] = set()

        for namespace in self._namespaces:
            names = self._module_sets()[namespace.name]

            (published if namespace.publish else resolveOnly).update(names)

        return sorted(resolveOnly - published)

    def _destinations(self) -> list[Destination]:
        """The output formats this build was asked for, in a fixed order."""
        wanted = []

        if self._outputs.notexts:
            wanted.append(Destination("notexts", "pysnmp", self._outputs.notexts))

        if self._outputs.texts:
            wanted.append(
                Destination(
                    "texts",
                    "pysnmp",
                    self._outputs.texts,
                    genTexts=True,
                    keepTextsLayout=True,
                )
            )

        if self._outputs.json:
            wanted.append(Destination("json", "json", self._outputs.json))

        # Its own destination rather than a flag on the one above, so that a
        # build may have both: the lean tree it publishes, and a complete one
        # for something that needs the prose. A build wanting only the second
        # names only the second, and pays one pass for it.
        if self._outputs.json_texts:
            wanted.append(
                Destination(
                    "json-texts", "json", self._outputs.json_texts, genTexts=True
                )
            )

        return wanted

    def _compiler_for(self, destination: Destination) -> MibCompiler:
        """A compiler writing one format, reading every namespace.

        Each destination needs its own compiler -- one carries one code
        generator and one writer -- but they share this driver's parse cache,
        so the ASN.1 is parsed once for the run rather than once per format.
        Parsing is about three quarters of a pass.

        The searchers and stubs match what ``mibdump`` configures for the
        same format, taken from the same class attributes rather than copied,
        so the two cannot drift apart. What is deliberately absent is
        borrowers: a corpus build compiles or reports a failure, it does not
        fetch somebody else's answer.
        """
        codegen: AbstractCodeGen
        writer: AbstractWriter
        searchers: list[AbstractSearcher]
        eligibleBaseMibs: list[str] = []

        configured = self._stubs.get(destination.format)

        if destination.format == "pysnmp":
            stubs = (
                list(configured)
                if configured is not None
                else [
                    x for x in PySnmpCodeGen.baseMibs if x not in PySnmpCodeGen.fakeMibs
                ]
            )

            codegen = PySnmpCodeGen()
            writer = PyFileWriter(destination.directory).set_options(pyCompile=False)
            searchers = [StubSearcher(*stubs)]

        elif destination.format == "json":
            # Nothing supplies a JSON SNMPv2-TC the way pysnmp supplies a
            # Python one, so stubbing the base MIBs would leave a tree that
            # cannot resolve the DisplayString half its modules import.
            # Compile those from the bundle instead, and stub the rest.
            bundled = bundled_mib_names(MibCompiler.bundledMibsPackage)
            stubs = (
                list(configured)
                if configured is not None
                else list(JsonCodeGen.baseMibs)
            )

            if self._useBundledMibs:
                eligibleBaseMibs = [x for x in stubs if x in bundled]
                stubs = [x for x in stubs if x not in bundled]

            codegen = JsonCodeGen()
            writer = FileWriter(destination.directory).set_options(suffix=_JSON_EXT)
            searchers = [
                AnyFileSearcher(destination.directory).set_options(exts=[_JSON_EXT]),
                StubSearcher(*stubs),
            ]

        else:
            raise error.PySmiError(
                f"unknown corpus destination format {destination.format}"
            )

        # Last, so that it wins over the JSON branch above: a base MIB the
        # bundle supplies is compiled into the JSON tree for a corpus that
        # publishes the standard modules, and stubbed for one that does not.
        resolveOnly = self._resolve_only_modules()

        if resolveOnly:
            stubs = sorted(set(stubs) | set(resolveOnly))
            searchers = [x for x in searchers if not isinstance(x, StubSearcher)] + [
                StubSearcher(*stubs)
            ]

        compiler = MibCompiler(
            SmiV1CompatParser(tempdir=""),
            codegen,
            writer,
            useBundledMibs=self._useBundledMibs,
            parseCache=self._parseCache,
        )
        compiler.add_sources(*[self._readers[x.name] for x in self._namespaces])
        compiler.add_searchers(*searchers)

        if eligibleBaseMibs:
            logger.debug(
                "base MIBs eligible to be written out from the bundle: %s",
                ", ".join(sorted(eligibleBaseMibs)),
                extra={"eligible_base_mibs": sorted(eligibleBaseMibs)},
            )

        return compiler

    def _module_sets(self) -> dict[str, list[str]]:
        """What each namespace holds, enumerated once for the run.

        The readers are asked, not the file names: a module declared in a
        file named for something else is still a module the corpus holds.
        """
        if self._modulesOfNamespace:
            return self._modulesOfNamespace

        for namespace in self._namespaces:
            modules = sorted(self._readers[namespace.name].list_mibs())
            self._modulesOfNamespace[namespace.name] = modules

            for module in modules:
                # First namespace declaring a module names its tier: the
                # input set is ordered, so this does not depend on anything
                # the build discovers as it goes.
                self._tierOfModule.setdefault(module, namespace.tier_rank)

            logger.debug(
                "namespace %s holds %d modules",
                namespace.name,
                len(modules),
                extra={"namespace": namespace.name, "modules": len(modules)},
            )

        return self._modulesOfNamespace

    def _published_modules(
        self, results: dict[str, dict[str, Any]]
    ) -> "list[str] | None":
        """What the corpus carries, read off the jsondoc compile.

        The jsondoc is the SMI model every other artifact is a projection
        of, so it is the one that decides. A module that did not compile is
        not in it, and neither is anything that imports one -- the compiler
        reports those as ``failed`` or ``unprocessed`` already, so the
        closure costs no dependency walk here.

        ``None`` where the build compiled no JSON at all, which means
        "everything the namespaces hold" to each writer.
        """
        written = results.get("json")

        if written is None:
            return None

        return sorted(
            name
            for name, status in written.items()
            if str(status) in PUBLISHED_STATUSES
        )

    def compile(self, report: CorpusReport) -> dict[str, dict[str, Any]]:
        """Compile every namespace into every destination.

        A namespace at a time, in declaration order, with every namespace
        configured as a source throughout -- so a module in ``nokia`` that
        ``alcatel`` imports resolves the same whether nokia is built first or
        last, which is the property the build this replaces did not have.

        A module is compiled once per destination however many namespaces
        hold it: the corpus is a flat tree with one file per module name, so
        there is one winner for the whole build and the compiler's precedence
        rule is what picks it.

        Args:
            report: filled in with what each destination did

        Returns:
            Per destination name, the statuses of every module processed.
        """
        moduleSets = self._module_sets()
        results: dict[str, dict[str, Any]] = {}

        for destination in self._destinations():
            started = time.time()
            compiler = self._compiler_for(destination)
            processed: dict[str, Any] = {}

            for namespace in self._published:
                wanted = [x for x in moduleSets[namespace.name] if x not in processed]

                if not wanted:
                    continue

                outcome = compiler.compile(
                    *wanted,
                    rebuild=self._rebuild,
                    genTexts=destination.genTexts,
                    textFilter=(
                        (lambda symbol, text: text)
                        if destination.keepTextsLayout
                        else None
                    ),
                    # Every destination keeps going past a defective module
                    # and the run reports it. The alternative is what the
                    # shell build did: set this on one pass of three, and
                    # let a single defective module remove its whole
                    # namespace from the other two without saying so.
                    ignoreErrors=True,
                )

                processed.update(outcome)

            results[destination.name] = processed

            report.statuses[destination.name] = _tally(processed)
            report.failed[destination.name] = {
                name: str(getattr(status, "error", ""))
                for name, status in sorted(processed.items())
                if status == "failed"
            }
            report.unprocessed[destination.name] = sorted(
                name for name, status in processed.items() if status == "unprocessed"
            )
            report.seconds[destination.name] = time.time() - started

            logger.info(
                "destination %s: %s",
                destination.name,
                ", ".join(
                    f"{k} {v}"
                    for k, v in sorted(report.statuses[destination.name].items())
                ),
                extra={
                    "destination": destination.name,
                    "statuses": report.statuses[destination.name],
                },
            )

        return results

    @staticmethod
    def _selector(compiled: "Iterable[str] | None") -> tuple[str, ...] | None:
        """A hashable key for one module selection, for the per-build caches."""
        return None if compiled is None else tuple(sorted(set(compiled)))

    def _resolutions(
        self, compiled: "Iterable[str] | None"
    ) -> "Iterator[MibResolution]":
        """Which copy of each published module the sources supply.

        One pass, streamed rather than collected, because a resolution carries
        the module's whole text and a corpus holds thousands of them.

        Which copy wins is
        :py:meth:`~pysmi.compiler.MibCompiler.resolve`'s answer, which is the
        same rule -- applied by the same code -- that decides which copy the
        compile uses. That is what makes the published ASN.1 the text the
        published ``.py`` and ``.json`` beside it were generated from, and
        what makes the provenance recorded beside them true of that text.

        Args:
            compiled: the modules this build compiled, or ``None`` for every
                module the namespaces hold.

        Yields:
            One resolution per published module, in namespace order, each
            module once.
        """
        # A resolver over the same source set, with no code generator or
        # writer doing anything: this asks where a module comes from, which
        # costs a read of the sources and not a compile.
        resolver = MibCompiler(
            SmiV1CompatParser(tempdir=""),
            JsonCodeGen(),
            CallbackWriter(lambda *_: None),
            useBundledMibs=self._useBundledMibs,
            parseCache=self._parseCache,
        )
        resolver.add_sources(*[self._readers[x.name] for x in self._namespaces])

        seen: set[str] = set()
        publishable = None if compiled is None else set(compiled)

        for namespace in self._published:
            for module in self._module_sets()[namespace.name]:
                if module in seen:
                    continue

                if publishable is not None and module not in publishable:
                    continue

                resolution = resolver.resolve(module)

                if resolution is None:
                    logger.error(
                        "%s vanished from the sources between enumeration and staging",
                        module,
                        extra={"mib": module},
                    )
                    continue

                seen.add(module)

                yield resolution

    def _origin(self, resolution: "MibResolution") -> dict[str, str]:
        """Where one module came from, as the report and the database carry it.

        The file is recorded relative to the namespace that supplied it, never
        as the absolute path the build happened to read. ``core.db`` is
        byte-reproducible, and a path carrying a checkout directory or a
        runner's scratch space would end that -- as well as saying where this
        build ran, which is nobody's business downstream.
        """
        namespace = self._namespaceOfReader.get(id(resolution.source), "")

        return {
            "namespace": namespace,
            "file": self._relative_source(namespace, resolution),
            "digest": resolution.digest,
        }

    def _relative_source(self, namespace: str, resolution: "MibResolution") -> str:
        """The path *resolution* was read from, relative to its namespace root.

        Falls back to the file name, which is what a package namespace has and
        all a caller can use of it.
        """
        source = next(
            (
                x.source
                for x in self._namespaces
                if x.name == namespace and not x.is_package
            ),
            None,
        )

        if source and resolution.path:
            try:
                relative = os.path.relpath(
                    os.path.abspath(resolution.path), os.path.abspath(source)
                )

            except ValueError:
                # Different drives on Windows. The file name is still true.
                return resolution.file

            if not relative.startswith(os.pardir):
                return relative.replace(os.sep, "/")

        return resolution.file

    def provenance(
        self, compiled: "Iterable[str] | None" = None
    ) -> dict[str, dict[str, str]]:
        """Where every published module came from.

        Free after :py:meth:`stage`, which resolves every module in order to
        write it and records this on the way past. A build that asked for the
        database but not for the ASN.1 tree pays one resolution pass here,
        which is the cost of the answer rather than an accident of ordering.

        Args:
            compiled: the modules this build compiled, as :py:meth:`stage`
                takes it.

        Returns:
            Per module, the namespace that supplied it, the file read
            relative to that namespace, and that file's digest.
        """
        selector = self._selector(compiled)

        if selector not in self._provenance:
            self._provenance[selector] = {
                x.name: self._origin(x) for x in self._resolutions(compiled)
            }

        return self._provenance[selector]

    def stage(
        self, report: CorpusReport, compiled: "Iterable[str] | None" = None
    ) -> dict[str, str]:
        """Write the published ASN.1 tree, one file per module name.

        Flat and named for the module, because that is what the tree's
        consumers substitute into: sc4snmp configures
        ``asn1/@mib@`` and pysmi replaces ``@mib@`` with a bare module name.

        Which copy of a module reaches the tree is
        :py:meth:`~pysmi.compiler.MibCompiler.resolve`'s answer, which is the
        same rule -- applied by the same code -- that decides which copy the
        compile uses. That is what makes the published ASN.1 the text the
        published ``.py`` and ``.json`` beside it were generated from,
        rather than whichever copy a parallel job happened to copy last.

        Args:
            report: filled in with what was staged, what was shadowed, and
                where each module came from
            compiled: the modules this build compiled, which is what the
                corpus publishes. A module that does not compile -- and, by
                the same result, everything that imports it -- is left out,
                so the tree, the indexes and the database carry one module
                set rather than three. Every module the namespaces hold when
                not given, which is what a caller staging sources without
                compiling them wants. See pysnmp/pysmi#269.

        Returns:
            Module name to the source path it was staged from.
        """
        directory = self._outputs.asn1

        if not directory:
            return {}

        started = time.time()
        os.makedirs(directory, exist_ok=True)

        staged: dict[str, str] = {}
        provenance: dict[str, dict[str, str]] = {}

        for resolution in self._resolutions(compiled):
            with open(
                os.path.join(directory, resolution.name),
                "w",
                encoding="utf-8",
                newline="",
            ) as fileObj:
                fileObj.write(resolution.data)

            staged[resolution.name] = resolution.path
            provenance[resolution.name] = self._origin(resolution)

            if resolution.shadowed:
                report.shadowed[resolution.name] = {
                    "used": resolution.path,
                    "shadowed": list(resolution.shadowed),
                    "precedence": resolution.precedence,
                }

        # Staging resolved every module, so provenance is already answered
        # and the pass that would answer it again is not run.
        self._provenance[self._selector(compiled)] = provenance
        report.provenance = provenance

        report.staged = len(staged)
        report.seconds["stage"] = time.time() - started

        logger.info(
            "staged %d modules into %s, %d of them held by more than one namespace",
            len(staged),
            directory,
            len(report.shadowed),
            extra={"staged": len(staged), "shadowed": len(report.shadowed)},
        )

        return staged

    def write_standard(self, compiled: "Iterable[str] | None" = None) -> None:
        """Write the standard module list.

        Every module from a namespace declared ``standard`` that the corpus
        publishes, less the prefixes the published file has never carried.
        See :py:data:`STANDARD_TXT_EXCLUDED_PREFIXES` for why that exclusion
        is reproduced rather than corrected.

        Args:
            compiled: the modules this build compiled, as :py:meth:`stage`
                takes it. The list is what a consumer preloads, so a module
                that does not compile has no business on it -- naming one is
                the same lie as serving it. Every module the standard
                namespaces hold when not given.
        """
        path = self._outputs.standard

        if not path:
            return

        standard: set[str] = set()

        for namespace in self._published:
            if namespace.tier != "standard":
                continue

            standard.update(self._module_sets()[namespace.name])

        if compiled is not None:
            standard &= set(compiled)

        names = sorted(
            x for x in standard if not x.startswith(STANDARD_TXT_EXCLUDED_PREFIXES)
        )

        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

        with open(path, "w", encoding="utf-8", newline="") as fileObj:
            fileObj.write("".join(f"{x}\n" for x in names))

        logger.info(
            "wrote %d standard module names to %s",
            len(names),
            path,
            extra={"modules": len(names), "path": path},
        )

    def _read_corpus(
        self, compiled: "Iterable[str] | None"
    ) -> tuple[list[tuple[str, dict[str, Any], int, int]], dict[str, str]]:
        """The corpus this build produced, read once and ranked once.

        Both the index and the database are projections of the same jsondoc
        tree, and reading a 5,000-module tree twice to make two projections of
        it is the kind of cost that only shows up at corpus scale. Cached on
        the instance because a driver builds one corpus.

        Args:
            compiled: the modules this build wrote JSON for, or ``None`` for
                everything in the directory

        Returns:
            ``(documents, ranked)`` as
            :py:func:`~pysmi.corpus.index.read_documents` and
            :py:func:`~pysmi.corpus.index.rank_index` produce them.
        """
        # Keyed by the selector, not merely memoized: write_index and write_db
        # are public and a caller may ask for a named subset and then for all
        # of it. Caching the first answer under both would silently write the
        # subset twice.
        selector = None if compiled is None else tuple(sorted(set(compiled)))

        if selector in self._corpus:
            return self._corpus[selector]

        tree = self._jsondoc_tree

        if not tree:
            raise error.PySmiError(
                "the OID indexes and the corpus database are projections of "
                "the jsondoc tree; emit json to build either"
            )

        try:
            from pysmi.mibs import manifest

            rfcs = {
                name: entry["rfc"]
                for name, entry in manifest().items()
                if isinstance(entry.get("rfc"), int)
            }

        except (ImportError, OSError, ValueError):  # pragma: no cover
            rfcs = {}

        documents = list(
            corpus_index.read_documents(tree, self._tierOfModule, rfcs, selector)
        )

        self._corpus[selector] = (documents, corpus_index.rank_index(documents))

        return self._corpus[selector]

    def write_db(
        self, report: CorpusReport, compiled: "Iterable[str] | None" = None
    ) -> None:
        """Write the corpus database.

        Args:
            report: filled in with the row counts and how long it took
            compiled: the modules this build wrote JSON for, as
                :py:meth:`write_index` takes it.
        """
        if not self._outputs.core_db:
            return

        # Free after staging, which resolved every module anyway. A build
        # asking for the database without the ASN.1 tree pays one resolution
        # pass for it, which is what the answer costs.

        started = time.time()

        documents, ranked = self._read_corpus(compiled)
        tiers = {
            name: TIERS[tier] if 0 <= tier < len(TIERS) else DEFAULT_TIER
            for name, tier in self._tierOfModule.items()
        }

        report.db = corpus_db.write_db(
            self._outputs.core_db,
            documents,
            tiers,
            ranked,
            corpusVersion=self._corpusVersion,
            corpusId=self._corpusId,
            provenance=self.provenance(compiled),
        )

        logger.info(
            "corpus database: %d modules, %d nodes",
            report.db.get("module", 0),
            report.db.get("node", 0),
            extra={
                "modules": report.db.get("module", 0),
                "nodes": report.db.get("node", 0),
            },
        )

        report.seconds["db"] = time.time() - started

    def write_closure(
        self, report: CorpusReport, compiled: "Iterable[str] | None" = None
    ) -> None:
        """Write the transitive import closure per module.

        A projection of the same jsondoc tree the indexes and the database are
        read from, so it costs the read the build has already paid for.

        Args:
            report: filled in with the counts and how long it took
            compiled: the modules this build wrote JSON for, as
                :py:meth:`write_index` takes it.
        """
        if not self._outputs.closure:
            return

        started = time.time()

        documents, _ranked = self._read_corpus(compiled)
        found = corpus_closure.closures(documents)

        _write_text(self._outputs.closure, corpus_closure.render_closure(found))

        report.closure = corpus_closure.counts(found)
        report.seconds["closure"] = time.time() - started

    def write_index(
        self, report: CorpusReport, compiled: "Iterable[str] | None" = None
    ) -> None:
        """Write the OID indexes, ranked and legacy.

        Both are computed from the jsondoc documents this build produced, so
        neither can name a module the corpus does not carry -- not even one
        left in the output directory by an earlier build over a different
        input set, which is how an index comes to name a module the site
        answers 404 for.

        Args:
            report: filled in with the node counts and index sizes
            compiled: the modules this build wrote JSON for. Every document
                in the directory when not given, which is what a caller
                indexing a tree it did not just build wants.
        """
        if not (self._outputs.ranked_index or self._outputs.index):
            return

        started = time.time()

        documents, ranked = self._read_corpus(compiled)

        report.nodes = {
            "defined": sum(len(corpus_index.oids_of(x[1])) for x in documents),
            "distinct": len(ranked),
            "modules": len(documents),
        }
        report.index["ranked"] = len(ranked)

        if self._outputs.ranked_index:
            _write_text(self._outputs.ranked_index, corpus_index.render_index(ranked))

        if self._outputs.index:
            frozen: list[tuple[str, str]] = []

            if self._outputs.frozen_index and os.path.exists(
                self._outputs.frozen_index
            ):
                with open(self._outputs.frozen_index, encoding="utf-8") as fileObj:
                    frozen = list(corpus_index.read_index(fileObj.read()))

            merged, dropped, added = corpus_index.merge_frozen(
                frozen, ranked, (x[0] for x in documents)
            )

            report.index.update(
                {"legacy": len(merged), "dropped": dropped, "added": added}
            )

            _write_text(self._outputs.index, corpus_index.render_index(merged))

            logger.info(
                "legacy index: %d OIDs, %d rows dropped as absent, %d added from the ranked index",
                len(merged),
                dropped,
                added,
                extra={"oids": len(merged), "dropped": dropped, "added": added},
            )

        report.seconds["index"] = time.time() - started

    @property
    def _jsondoc_tree(self) -> str | None:
        """The jsondoc tree the projections read.

        The lean one where a build has it, since that is what the indexes and
        the database have always been built from and the texts change nothing
        they carry. A build that asked only for the tree with texts in it gets
        its projections from that one rather than from a second pass.
        """
        return self._outputs.json or self._outputs.json_texts

    def _needs_jsondoc(self) -> bool:
        """Whether an artifact asked for is a projection of the jsondoc tree.

        The ASN.1 tree and the standard list are projections too: both carry
        what the corpus publishes, and what it publishes is what compiled.
        """
        return bool(
            self._outputs.core_db
            or self._outputs.index
            or self._outputs.ranked_index
            or self._outputs.closure
            or self._outputs.asn1
            or self._outputs.standard
        )

    def run(self) -> CorpusReport:
        """Build the corpus and report what it did.

        A build asking for the database or an index but not for the jsondoc
        tree gets one staged for the duration and removed afterwards,
        including where the build raises. The dependency is pysmi's own: a
        publisher asking for ``core.db`` did not ask for a tree of JSON and
        should not have to know one exists, nor pick a scratch path for it
        and clean up after itself. See pysnmp/pysmi#262.

        Returns:
            The report, also written to the ``report`` path when one was
            asked for.
        """
        if self._jsondoc_tree or not self._needs_jsondoc():
            return self._build()

        with tempfile.TemporaryDirectory(prefix="pysmi-corpus-") as scratch:
            self._outputs.json = os.path.join(scratch, "json")

            try:
                return self._build()

            finally:
                # The caller handed us these outputs; they leave as they came.
                self._outputs.json = None

    def _build(self) -> CorpusReport:
        """One build, with every output path already decided."""
        started = time.time()
        report = CorpusReport()

        moduleSets = self._module_sets()
        report.namespaces = [
            {
                "name": x.name,
                "tier": x.tier,
                "source": x.source,
                "modules": len(moduleSets[x.name]),
                "publish": x.publish,
            }
            for x in self._namespaces
        ]

        # The compile decides what the corpus publishes, so it runs first
        # and every artifact is derived from the one answer it gives. A
        # module that does not compile reaches no output tree, and neither
        # does anything that imports it -- the compiler already reports
        # those as failed or unprocessed, so no dependency walk is needed
        # here. See pysnmp/pysmi#269.
        results = self.compile(report)
        published = self._published_modules(results)

        # What the corpus holds, that compiled. A resolve-only module is
        # stubbed and comes back "untouched", so the compile result alone
        # would count modules the corpus does not carry.
        held = {x for ns in self._published for x in moduleSets[ns.name]}
        report.modules = len(held if published is None else held & set(published))

        self.stage(report, published)
        self.write_standard(published)
        self.write_index(report, published)
        self.write_db(report, published)
        self.write_closure(report, published)

        # Whatever answered provenance -- staging, or the database asking for
        # it -- the report carries it. A build that asked for neither says
        # nothing rather than paying a pass to fill in a field.
        report.provenance = self._provenance.get(
            self._selector(published), report.provenance
        )

        report.seconds["total"] = time.time() - started

        if self._outputs.report:
            import json as _json

            _write_text(
                self._outputs.report,
                _json.dumps(report.as_dict(), indent=2, sort_keys=True) + "\n",
            )

        return report


def check_expectations(expect: "Mapping[str, Any]", report: CorpusReport) -> list[str]:
    """What a build failed to be, against what its manifest said it would be.

    ``report.json`` has always carried the counts and nothing checked them,
    so a publisher's real assertions -- this corpus has N modules, these
    namespaces are in it, no more than this many modules fail to compile --
    lived in a downstream test script that every publisher wrote once and
    differently. Declaring them makes them data pysmi enforces. See
    pysnmp/pysmi#263.

    Args:
        expect: the manifest's ``expect``, as
            :py:func:`~pysmi.corpus.namespace.read_manifest` validated it
        report: what the build did

    Returns:
        One line per expectation missed, naming the field, the bound and
        what the build actually was. Empty when the build is what the
        manifest said it would be.
    """
    #: Modules that failed in any destination, counted once. A module
    #: failing in all three is one module the corpus does not carry.
    failures = len({x for failed in report.failed.values() for x in failed})

    actual = {"modules": report.modules, "failures": failures}
    missed: list[str] = []

    for key, bounds in expect.items():
        if key == "namespaces-present":
            present = {x["name"] for x in report.namespaces if x["publish"]}

            missed.extend(
                f"namespaces-present: {x} is not a namespace this corpus publishes"
                for x in bounds
                if x not in present
            )

            continue

        value = actual[key]

        if "min" in bounds and value < bounds["min"]:
            missed.append(f"{key}: expected at least {bounds['min']}, got {value}")

        if "max" in bounds and value > bounds["max"]:
            missed.append(f"{key}: expected at most {bounds['max']}, got {value}")

    return missed


#: Compile outcomes that mean the corpus has the module. Anything else --
#: ``failed`` for a module that does not compile, ``unprocessed`` for one
#: dropped because something it imports did not -- is not published.
PUBLISHED_STATUSES: Final[tuple[str, ...]] = ("compiled", "untouched", "borrowed")


def _tally(processed: dict[str, Any]) -> dict[str, int]:
    """How many modules reached each status."""
    counts: dict[str, int] = {}

    for status in processed.values():
        counts[str(status)] = counts.get(str(status), 0) + 1

    return dict(sorted(counts.items()))


def _write_text(path: str, text: str) -> None:
    """Write a file, creating the directory it lives in."""
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="") as fileObj:
        fileObj.write(text)
