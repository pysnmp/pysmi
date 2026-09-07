#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""One compiler driven across many source sets parses the shared tree once.

A corpus build compiles hundreds of vendor namespaces, each with its own source
directory and each depending on the same handful of standard modules. Driven as
a shell loop -- a fresh interpreter per namespace -- that standard tree is
re-parsed once per namespace, because the parse cache lives in ``compile()`` and
dies with the call.

These tests pin the two properties that let one compiler be reused instead:
output is identical to the fresh-compiler build, and a module never resolves
from a source set that has since been swapped out. The second is the whole risk
-- a cache that survives a source swap is a cache that can answer with the
previous namespace's copy of a name.
"""

import hashlib
import json
import os
import pickle
import shutil
import tempfile
import textwrap
import unittest

from pysmi import error
from pysmi.cache import (
    AbstractParseCache,
    FileParseCache,
    InMemoryParseCache,
    NullParseCache,
)
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser, SmiV1Parser, SmiV2Parser
from pysmi.reader import CallbackReader
from pysmi.writer import CallbackWriter

#: The modules every namespace below imports from, and which a cold build
#: therefore re-parses once per namespace.
SHARED = ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF")


def module(name, oid, description):
    """A minimal but real module, importing from the shared standard tree.

    Written out rather than taken from the bundle so the two namespaces below
    can carry genuinely different modules under one name, which is what the
    leak test needs.
    """
    return textwrap.dedent(
        f"""\
        {name} DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, OBJECT-TYPE, Integer32, enterprises
                FROM SNMPv2-SMI;

        {name.lower().replace("-", "")}MI MODULE-IDENTITY
            LAST-UPDATED "202401010000Z"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "{description}"
            ::= {{ enterprises {oid} }}

        testObject OBJECT-TYPE
            SYNTAX      Integer32
            MAX-ACCESS  read-only
            STATUS      current
            DESCRIPTION "{description}"
            ::= {{ {name.lower().replace("-", "")}MI 1 }}
        END
        """
    )


def reader(modules):
    """A source serving exactly *modules*, and reporting a miss for anything else."""

    def serve(mibname, context):
        try:
            return modules[mibname]

        except KeyError:
            raise error.PySmiReaderFileNotFoundError(
                mibname=mibname, reader=None
            ) from None

    return CallbackReader(serve)


class ParseCounter:
    """Counts parser invocations, keyed by the bytes handed to them.

    Keying on content rather than module name is what makes the count
    meaningful: it separates "parsed a second module" from "parsed the same
    text a second time", and only the latter is the waste this issue is about.
    """

    def __init__(self):
        self.calls = []
        self._original = SmiV1CompatParser.parse

    def __enter__(self):
        counter = self

        def counting(inner, data, **kwargs):
            counter.calls.append(hashlib.sha256(data.encode()).hexdigest())
            return counter._original(inner, data, **kwargs)

        SmiV1CompatParser.parse = counting
        return self

    def __exit__(self, *exc):
        SmiV1CompatParser.parse = self._original

    @property
    def total(self):
        return len(self.calls)

    @property
    def distinct(self):
        return len(set(self.calls))

    @property
    def redundant(self):
        """Parses of text that had already been parsed in this build."""
        return self.total - self.distinct


def compile_cold(namespaces):
    """Compile each namespace on its own compiler, as a shell loop does."""
    output = {}

    for name, modules in namespaces.items():
        documents = {}
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(
                lambda mibname, data, cbCtx, into=documents: into.__setitem__(
                    mibname, data
                )
            ),
        )
        compiler.add_sources(reader(modules))
        compiler.compile(*modules, rebuild=True)
        output[name] = documents

    return output


class BatchOutputMatchesTheColdBuildTestCase(unittest.TestCase):
    """Reuse is only worth having if it changes nothing but the cost."""

    def setUp(self):
        self.namespaces = {
            "alpha": {"ALPHA-MIB": module("ALPHA-MIB", 1001, "alpha")},
            "beta": {"BETA-MIB": module("BETA-MIB", 1002, "beta")},
        }

    def testAReusedCompilerProducesTheColdBuildsOutput(self):
        """Byte-identical, not merely equivalent."""
        cold = compile_cold(self.namespaces)

        warm = {}
        documents = {}
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(
                lambda mibname, data, cbCtx: documents.__setitem__(mibname, data)
            ),
        )
        for name, modules in self.namespaces.items():
            documents.clear()
            compiler.set_sources(reader(modules))
            compiler.compile(*modules, rebuild=True)
            warm[name] = dict(documents)

        for name in self.namespaces:
            self.assertEqual(
                cold[name].keys(),
                warm[name].keys(),
                f"{name}: different modules reached the writer",
            )
            for mibname in cold[name]:
                self.assertEqual(
                    json.loads(cold[name][mibname]),
                    json.loads(warm[name][mibname]),
                    f"{name}::{mibname} differs between the cold and warm builds",
                )


class NoDependencyLeaksAcrossASourceSwapTestCase(unittest.TestCase):
    """The risk the cache creates, asserted directly.

    Two namespaces carry different modules under one name -- which is ordinary
    in a vendor corpus, where the same MIB name appears in several trees at
    different revisions. A cache keyed on the name alone would serve the first
    namespace's copy to the second.
    """

    def setUp(self):
        self.first = {"SHARED-NAME-MIB": module("SHARED-NAME-MIB", 2001, "first")}
        self.second = {"SHARED-NAME-MIB": module("SHARED-NAME-MIB", 2002, "second")}

    def _compile(self, compiler, modules):
        documents = {}
        compiler._writer = CallbackWriter(
            lambda mibname, data, cbCtx: documents.__setitem__(mibname, data)
        )
        compiler.set_sources(reader(modules))
        compiler.compile(*modules, rebuild=True)

        return documents

    def testTheSecondNamespaceGetsItsOwnCopy(self):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )

        first = self._compile(compiler, self.first)
        second = self._compile(compiler, self.second)

        firstOid = json.loads(first["SHARED-NAME-MIB"])["sharednamemibMI"]["oid"]
        secondOid = json.loads(second["SHARED-NAME-MIB"])["sharednamemibMI"]["oid"]

        self.assertNotEqual(
            firstOid,
            secondOid,
            "the second namespace resolved the first namespace's copy",
        )
        self.assertTrue(secondOid.endswith(".2002"), secondOid)

    def testASwappedOutSourceIsNotConsultedAgain(self):
        """A name only the first namespace had must stop resolving."""
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )

        self._compile(compiler, {"ONLY-HERE-MIB": module("ONLY-HERE-MIB", 2003, "one")})

        compiler.set_sources(reader(self.second))
        processed = compiler.compile("ONLY-HERE-MIB", rebuild=True)

        self.assertEqual(processed["ONLY-HERE-MIB"], "missing")


class PrioritySourcesSurviveASwapTestCase(unittest.TestCase):
    """The half of `set_sources` that is about what it does *not* replace.

    Priority sources are the part that does not vary between namespaces --
    pysmi's bundled base MIBs are registered that way -- so a driver registers
    them once and swaps only the rest. Nothing else in this file would notice
    if a swap dropped them, because the bundled source would still answer for
    the standard tree and the namespace reader for everything else.
    """

    def setUp(self):
        self.shared = {"SITE-BASE-MIB": module("SITE-BASE-MIB", 6001, "site base")}
        self.first = {"FIRST-MIB": module("FIRST-MIB", 6002, "first")}
        self.second = {"SECOND-MIB": module("SECOND-MIB", 6003, "second")}

    def testAPriorityOnlyModuleStillResolvesAfterASwap(self):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )
        compiler.add_priority_sources(reader(self.shared))

        compiler.set_sources(reader(self.first))
        compiler.compile("FIRST-MIB", rebuild=True)

        compiler.set_sources(reader(self.second))
        processed = compiler.compile("SITE-BASE-MIB", "SECOND-MIB", rebuild=True)

        self.assertEqual(processed["SITE-BASE-MIB"], "compiled")
        self.assertEqual(processed["SECOND-MIB"], "compiled")

    def testSwappingDoesNotAccumulateSources(self):
        """Replaces rather than appends, or a long build grows a source list."""
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )
        compiler.add_priority_sources(reader(self.shared))

        compiler.set_sources(reader(self.first))
        after_first = len(compiler._all_sources())

        compiler.set_sources(reader(self.second))

        self.assertEqual(len(compiler._all_sources()), after_first)


class TheSharedTreeIsParsedOncePerBuildTestCase(unittest.TestCase):
    """The outcome the issue asks for, measured rather than asserted."""

    def setUp(self):
        self.namespaces = {
            f"ns{n}": {f"NS{n}-MIB": module(f"NS{n}-MIB", 3000 + n, f"ns{n}")}
            for n in range(4)
        }

    def testAColdBuildReparsesTheSharedTreePerNamespace(self):
        """Pins the cost being removed, so the comparison below has a baseline."""
        with ParseCounter() as counter:
            compile_cold(self.namespaces)

        self.assertGreater(
            counter.redundant,
            0,
            "expected the cold build to re-parse the shared tree",
        )

    def testAReusedCompilerParsesEachSourceOnce(self):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )

        with ParseCounter() as counter:
            for modules in self.namespaces.values():
                compiler.set_sources(reader(modules))
                compiler.compile(*modules, rebuild=True)

        self.assertEqual(
            counter.redundant,
            0,
            f"{counter.redundant} of {counter.total} parses were repeats",
        )


if __name__ == "__main__":
    unittest.main()


class ParseCacheProvidersTestCase(unittest.TestCase):
    """The cache is a component, not a fixed behaviour of the compiler."""

    def setUp(self):
        self.modules = {"PROVIDER-MIB": module("PROVIDER-MIB", 4001, "provider")}

    def _compiler(self, **kwargs):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
            **kwargs,
        )
        compiler.add_sources(reader(self.modules))

        return compiler

    def testTheDefaultProviderIsInMemory(self):
        self.assertIsInstance(self._compiler()._parseCache, InMemoryParseCache)

    def testTheNullProviderParsesEveryTime(self):
        compiler = self._compiler(parseCache=NullParseCache())

        with ParseCounter() as counter:
            compiler.compile(*self.modules, rebuild=True)
            compiler.compile(*self.modules, rebuild=True)

        self.assertEqual(counter.redundant, counter.distinct)

    def testACustomProviderIsAskedAndFilled(self):
        """A provider written outside pysmi works with no registration step."""

        class Recording(AbstractParseCache):
            def __init__(self):
                self.gets = []
                self.sets = []
                self.entries = {}

            def get(self, key):
                self.gets.append(key)
                return self.entries.get(key)

            def set(self, key, trees):
                self.sets.append(key)
                self.entries[key] = trees

            def clear(self):
                self.entries.clear()

        recording = Recording()
        compiler = self._compiler(parseCache=recording)
        compiler.compile(*self.modules, rebuild=True)

        self.assertTrue(recording.gets)
        self.assertEqual(sorted(set(recording.sets)), sorted(recording.entries))

    def testAProviderThatAlwaysMissesStillCompiles(self):
        """A cache is an optimisation; failing to cache is not a failure."""

        class AlwaysMisses(AbstractParseCache):
            def get(self, key):
                return None

            def set(self, key, trees):
                pass

            def clear(self):
                pass

        compiler = self._compiler(parseCache=AlwaysMisses())
        processed = compiler.compile(*self.modules, rebuild=True)

        self.assertEqual(processed["PROVIDER-MIB"], "compiled")

    def testClearParseCacheReachesTheProvider(self):
        cache = InMemoryParseCache()
        compiler = self._compiler(parseCache=cache)
        compiler.compile(*self.modules, rebuild=True)

        self.assertTrue(cache._entries)

        compiler.clear_parse_cache()

        self.assertFalse(cache._entries)


class BoundedInMemoryCacheTestCase(unittest.TestCase):
    """Least-recently-used eviction, so a long build does not accumulate."""

    def testTheBoundIsHonoured(self):
        cache = InMemoryParseCache(maxEntries=2)
        cache.set("a", ["A"])
        cache.set("b", ["B"])
        cache.set("c", ["C"])

        self.assertIsNone(cache.get("a"))
        self.assertEqual(cache.get("b"), ["B"])
        self.assertEqual(cache.get("c"), ["C"])

    def testReadingAnEntryKeepsIt(self):
        """What the shared standard tree relies on: it is read every namespace."""
        cache = InMemoryParseCache(maxEntries=2)
        cache.set("shared", ["S"])
        cache.set("first", ["1"])

        cache.get("shared")
        cache.set("second", ["2"])

        self.assertEqual(cache.get("shared"), ["S"])
        self.assertIsNone(cache.get("first"))

    def testZeroMeansUnbounded(self):
        cache = InMemoryParseCache(maxEntries=0)
        for n in range(50):
            cache.set(str(n), [n])

        self.assertEqual(cache.get("0"), [0])


class FileParseCacheTestCase(unittest.TestCase):
    """The provider for a build that spans processes."""

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)
        self.modules = {"ON-DISK-MIB": module("ON-DISK-MIB", 5001, "disk")}

    def _compile(self, cache):
        documents = {}
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(
                lambda mibname, data, cbCtx: documents.__setitem__(mibname, data)
            ),
            parseCache=cache,
        )
        compiler.add_sources(reader(self.modules))
        compiler.compile(*self.modules, rebuild=True)

        return documents

    def testASecondCompilerReusesTheFirstsTrees(self):
        """The point of it: a fresh process, an already-warm cache."""
        first = self._compile(FileParseCache(self.directory))

        with ParseCounter() as counter:
            second = self._compile(FileParseCache(self.directory))

        self.assertEqual(
            counter.total, 0, "a fresh compiler still parsed with a warm cache"
        )
        self.assertEqual(
            json.loads(first["ON-DISK-MIB"]), json.loads(second["ON-DISK-MIB"])
        )

    def testACorruptEntryIsAMissNotAFailure(self):
        self._compile(FileParseCache(self.directory))

        for name in os.listdir(self.directory):
            with open(os.path.join(self.directory, name), "wb") as fd:
                fd.write(b"not a pickle")

        documents = self._compile(FileParseCache(self.directory))

        self.assertIn("ON-DISK-MIB", documents)

    def testAnEntryOfTheWrongShapeIsIgnored(self):
        """Written by something else, or by a version whose trees differed."""
        cache = FileParseCache(self.directory)
        cache.set("k", [1, 2])

        with open(cache._entry("k"), "wb") as fd:
            pickle.dump({"not": "a list"}, fd)

        self.assertIsNone(cache.get("k"))

    def testClearRemovesOnlyItsOwnEntries(self):
        """A directory may hold files this cache did not write.

        Filtering on `.pickle` alone would delete a build's own
        `metadata.pickle`; filtering on the key's shape would not work either,
        because a key is whatever the compiler composed. Entries carry an owned
        prefix instead.
        """
        cache = FileParseCache(self.directory)
        cache.set("k", [1])

        foreign = {
            os.path.join(self.directory, "README"): "not ours",
            os.path.join(self.directory, "metadata.pickle"): "also not ours",
        }
        for path, text in foreign.items():
            with open(path, "w") as fd:
                fd.write(text)

        cache.clear()

        self.assertIsNone(cache.get("k"))
        for path in foreign:
            self.assertTrue(os.path.exists(path), path)

    def testEntriesAreNamedSoTheyCanBeRecognised(self):
        cache = FileParseCache(self.directory)
        cache.set("k", [1])

        written = os.listdir(self.directory)

        self.assertEqual(len(written), 1, written)
        self.assertTrue(written[0].startswith(FileParseCache.ENTRY_PREFIX))


class FailingToCacheIsNotACompilationFailureTestCase(unittest.TestCase):
    """A cache is an optimisation, so every way it can fail is a miss.

    The claim is made in `AbstractParseCache` and relied on by
    `FileParseCache`, which touches a filesystem and can therefore fail in
    ways an in-memory provider cannot.
    """

    def setUp(self):
        self.directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.directory, ignore_errors=True)

    def testAnUnwritableDirectoryDoesNotRaise(self):
        """The directory is removed rather than chmod-ed: the suite may run as
        root, where mode bits are not enforced and the test would pass for the
        wrong reason."""
        cache = FileParseCache(self.directory)
        shutil.rmtree(self.directory)

        cache.set("k", [1])

        self.assertIsNone(cache.get("k"))

    def testAnUnwritableDirectoryStillCompiles(self):
        """The property that matters: output does not depend on the cache."""
        cache = FileParseCache(self.directory)
        shutil.rmtree(self.directory)

        modules = {"UNWRITABLE-MIB": module("UNWRITABLE-MIB", 7001, "unwritable")}
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
            parseCache=cache,
        )
        compiler.add_sources(reader(modules))
        processed = compiler.compile(*modules, rebuild=True)

        self.assertEqual(processed["UNWRITABLE-MIB"], "compiled")

    def testAnUnpicklableValueIsNotAnError(self):
        cache = FileParseCache(self.directory)

        cache.set("k", [lambda: None])

        self.assertIsNone(cache.get("k"))

    def testNoPartialFileIsLeftBehind(self):
        """A failed write must not leave a temporary for the next run to read."""
        cache = FileParseCache(self.directory)

        cache.set("k", [lambda: None])

        self.assertEqual(
            [n for n in os.listdir(self.directory) if n.endswith(".partial")], []
        )

    def testClearingAMissingDirectoryDoesNotRaise(self):
        cache = FileParseCache(self.directory)
        shutil.rmtree(self.directory)

        cache.clear()


class TheInterfaceIsAbstractTestCase(unittest.TestCase):
    """A provider that forgets a method fails loudly, not silently."""

    def testEveryMethodMustBeImplemented(self):
        incomplete = AbstractParseCache()

        for call in (
            lambda: incomplete.get("k"),
            lambda: incomplete.set("k", []),
            incomplete.clear,
        ):
            with self.assertRaises(NotImplementedError):
                call()


class TheProvidersDescribeThemselvesTestCase(unittest.TestCase):
    """`repr` names the provider and its configuration, for a build log."""

    def testEachReprNamesItsClass(self):
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, ignore_errors=True)

        for cache, expected in (
            (InMemoryParseCache(maxEntries=8), "InMemoryParseCache(maxEntries=8)"),
            (NullParseCache(), "NullParseCache()"),
            (FileParseCache(directory), f"FileParseCache({directory!r})"),
        ):
            self.assertEqual(repr(cache), expected)


class TheCacheKeyCarriesItsProducerTestCase(unittest.TestCase):
    """A persisted tree must not outlive the parser that made it.

    A parse tree is one parser's output at one pysmi version, not a versioned
    interchange format. Within a process that can never bite; a cache on disk
    outlives the release that filled it, so the producer goes in the key.
    """

    def _key(self, **kwargs):
        compiler = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
            **kwargs,
        )
        return compiler, compiler._parse_cache_key("some-digest")

    def testTheKeyIsNotTheBareDigest(self):
        _, key = self._key()

        self.assertNotEqual(key, "some-digest")

    def testADifferentPysmiVersionKeysDifferently(self):
        compiler, before = self._key()
        compiler._parserId = compiler._parserId.replace("2.", "99.")

        self.assertNotEqual(before, compiler._parse_cache_key("some-digest"))

    def testADifferentParserKeysDifferently(self):
        compiler, before = self._key()
        compiler._parserId = "same-version/other.OtherParser"

        self.assertNotEqual(before, compiler._parse_cache_key("some-digest"))

    def testEveryShippedDialectKeysDifferently(self):
        """The class alone cannot tell them apart.

        `parserFactory` names every specialization it builds `SmiParser`, so
        all three shipped parsers are `pysmi.parser.smi.SmiParser`. They do not
        accept the same grammar -- see the test below -- so a file cache keyed
        on the class would serve one dialect's tree to another.
        """
        keys = {
            name: MibCompiler(
                parser(),
                JsonCodeGen(),
                CallbackWriter(lambda *args, **kwargs: None),
            )._parse_cache_key("one-digest")
            for name, parser in (
                ("v1", SmiV1Parser),
                ("v1compat", SmiV1CompatParser),
                ("v2", SmiV2Parser),
            )
        }

        self.assertEqual(len(set(keys.values())), 3, keys)

    def testTheDialectsThoseKeysSeparateReallyDisagree(self):
        """The premise of the test above, rather than an assumption.

        A trailing comma in IMPORTS is tolerated by the relaxed dialect and
        rejected by strict SMIv2. Sharing a cache between them would hand the
        strict build a tree for text it should have refused.
        """
        trailing_comma = textwrap.dedent(
            """\
            COMMA-MIB DEFINITIONS ::= BEGIN
            IMPORTS
                OBJECT-TYPE,
                Integer32,
                    FROM SNMPv2-SMI;
            testObj OBJECT-TYPE SYNTAX Integer32 MAX-ACCESS read-only
                STATUS current DESCRIPTION "d" ::= { 1 3 6 1 4 1 9999 1 }
            END
            """
        )

        self.assertTrue(SmiV1CompatParser().parse(trailing_comma))

        with self.assertRaises(error.PySmiParserError):
            SmiV2Parser().parse(trailing_comma)

    def testTheStartSymbolIsPartOfTheIdentity(self):
        """It selects a grammar as surely as a relaxation does.

        Two real parsers, differing only in where they start: `mibFile` reads a
        file of modules, `module` reads one. Nothing is mutated, so the
        assertion fails if `_parserId` ever stops carrying the start symbol --
        which is the whole point of having it.
        """
        default = MibCompiler(
            SmiV1CompatParser(),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )
        other = MibCompiler(
            SmiV1CompatParser(startSym="module"),
            JsonCodeGen(),
            CallbackWriter(lambda *args, **kwargs: None),
        )

        self.assertNotEqual(default._parse_cache_key("d"), other._parse_cache_key("d"))

    def testTheSameProducerAndTextAgree(self):
        _, first = self._key()
        _, second = self._key()

        self.assertEqual(first, second)
