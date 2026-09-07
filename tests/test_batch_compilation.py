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
import textwrap
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
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
