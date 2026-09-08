#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Asking which copy of a module the sources supply, without compiling it.

``compile()`` answers this on the way past, on ``MibStatus.path``, but only
for a module it went on to compile and only after it has. A corpus driver has
to publish the ASN.1 beside the compiled output, for every module it holds
including the ones that fail, and the two have to be the same text. Asking
the same code the same question is what makes them agree.
"""

import os
import shutil
import tempfile
import textwrap
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.compiler import PRECEDENCE_NEWEST_REVISION, MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.writer import CallbackWriter


def module(revision, description):
    """One module at a given revision."""
    return textwrap.dedent(
        f"""\
        SHARED-MIB DEFINITIONS ::= BEGIN
        IMPORTS
            MODULE-IDENTITY, enterprises FROM SNMPv2-SMI;

        sharedMI MODULE-IDENTITY
            LAST-UPDATED "{revision}"
            ORGANIZATION "test"
            CONTACT-INFO "test"
            DESCRIPTION  "{description}"
            ::= {{ enterprises 51 }}
        END
        """
    )


def compiler(*sources):
    """A compiler that resolves and does nothing else."""
    mibCompiler = MibCompiler(
        SmiV1CompatParser(tempdir=""),
        JsonCodeGen(),
        CallbackWriter(lambda *args, **kwargs: None),
    )
    mibCompiler.add_sources(*sources)

    return mibCompiler


class ResolveTestCase(unittest.TestCase):
    """What resolve() reports.

    Over directories on disk rather than a callback source: the copies passed
    over are reported by path, so two sources that answer under one path
    cannot show the behaviour.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def reader(self, name, modules):
        """A directory holding *modules*, as a source."""
        directory = os.path.join(self.root, name)
        os.makedirs(directory, exist_ok=True)

        for mibname, text in modules.items():
            with open(os.path.join(directory, mibname), "w") as fileObj:
                fileObj.write(text)

        return FileReader(directory)

    def testAModuleNoSourceHasIsNone(self):
        self.assertIsNone(compiler(self.reader("empty", {})).resolve("NOWHERE-MIB"))

    def testTheTextIsTheOneTheCompileWouldUse(self):
        mibCompiler = compiler(
            self.reader("one", {"SHARED-MIB": module("202401010000Z", "new")})
        )

        self.assertIn("new", mibCompiler.resolve("SHARED-MIB").data)

    def testASingleCopyDecidesNothing(self):
        resolution = compiler(
            self.reader("one", {"SHARED-MIB": module("202401010000Z", "new")})
        ).resolve("SHARED-MIB")

        self.assertEqual((), resolution.shadowed)
        self.assertEqual("", resolution.precedence)

    def testTheNewestRevisionWins(self):
        resolution = compiler(
            self.reader("old", {"SHARED-MIB": module("201001010000Z", "old")}),
            self.reader("new", {"SHARED-MIB": module("202401010000Z", "new")}),
        ).resolve("SHARED-MIB")

        self.assertIn("new", resolution.data)
        self.assertEqual(PRECEDENCE_NEWEST_REVISION, resolution.precedence)
        self.assertEqual(1, len(resolution.shadowed))

    def testAnIdenticalSecondCopyIsNotShadowing(self):
        # Two sources holding the same bytes is not a collision; nothing was
        # passed over.
        same = module("202401010000Z", "new")
        resolution = compiler(
            self.reader("first", {"SHARED-MIB": same}),
            self.reader("second", {"SHARED-MIB": same}),
        ).resolve("SHARED-MIB")

        self.assertEqual((), resolution.shadowed)

    def testResolveAgreesWithCompile(self):
        # The property the corpus driver rests on: the ASN.1 it publishes for
        # a module is the text the compiled artifact beside it was generated
        # from, because both come from this one rule.
        sources = (
            self.reader("old", {"SHARED-MIB": module("201001010000Z", "old")}),
            self.reader("new", {"SHARED-MIB": module("202401010000Z", "new")}),
        )

        resolution = compiler(*sources).resolve("SHARED-MIB")

        written = {}
        mibCompiler = MibCompiler(
            SmiV1CompatParser(tempdir=""),
            JsonCodeGen(),
            CallbackWriter(
                lambda mibname, data, *args, **kwargs: written.__setitem__(
                    mibname, data
                )
            ),
        )
        mibCompiler.add_sources(*sources)
        processed = mibCompiler.compile("SHARED-MIB", genTexts=True)

        self.assertEqual("compiled", processed["SHARED-MIB"])
        self.assertEqual(
            list(resolution.shadowed), list(processed["SHARED-MIB"].shadowed)
        )
        self.assertIn("new", resolution.data)
        self.assertIn("new", written["SHARED-MIB"])
