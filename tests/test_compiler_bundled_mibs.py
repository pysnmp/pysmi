#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""MibCompiler falls back to pysmi's bundled base MIBs only once every
add_sources reader has failed -- a user-supplied copy always wins, and
useBundledMibs=False turns the fallback off entirely. See pysnmp/pysmi#113.
"""

import importlib.resources
import os
import tempfile
import unittest

from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.mibinfo import source_digest
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.writer import CallbackWriter


class BundledMibsTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.written = {}
        self.compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda n, d, ctx: self.written.update({n: d}))
        )

    def tearDown(self):
        self._tmp.cleanup()

    def testBundledMibsAreRegisteredAsFallbackByDefault(self):
        self.assertEqual(1, len(self.compiler._fallback_sources))
        self.assertEqual([], self.compiler._sources)

    def testUseBundledMibsFalseRegistersNoFallback(self):
        compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None), useBundledMibs=False
        )
        self.assertEqual([], compiler._fallback_sources)

    def testAUserSourceWithNothingFallsBackToTheBundledCopy(self):
        self.compiler.add_sources(FileReader(self._tmp.name))
        processed = self.compiler.compile("SNMPv2-CONF", ignoreErrors=True)
        self.assertEqual("compiled", processed["SNMPv2-CONF"])

    def testAUserSourceThatHasItWinsOverTheBundledCopy(self):
        # Every compiled module carries a "Source digest" comment of the
        # exact ASN.1 text it was read from (see pysnmp/pysmi#63) -- the one
        # signal that distinguishes which copy was actually used, since the
        # symtable codegen adds the same SNMPv2-CONF/-SMI/-TC imports
        # boilerplate to every module's output regardless of content.
        stub = "SNMPv2-CONF DEFINITIONS ::= BEGIN\nEND\n"
        with open(os.path.join(self._tmp.name, "SNMPv2-CONF"), "w") as fp:
            fp.write(stub)

        self.compiler.add_sources(FileReader(self._tmp.name))
        self.compiler.compile("SNMPv2-CONF", ignoreErrors=True)

        self.assertIn(source_digest(stub), self.written["SNMPv2-CONF"])

    def testABundledCopyIsUsedWhenNoUserSourceHasIt(self):
        bundled_text = (importlib.resources.files("pysmi.mibs.asn1") / "SNMPv2-CONF").read_text()

        self.compiler.add_sources(FileReader(self._tmp.name))
        self.compiler.compile("SNMPv2-CONF", ignoreErrors=True)

        self.assertIn(source_digest(bundled_text), self.written["SNMPv2-CONF"])

    def testWithoutBundlingAMissingBaseMibStaysMissing(self):
        compiler = MibCompiler(
            SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None), useBundledMibs=False
        )
        compiler.add_sources(FileReader(self._tmp.name))
        processed = compiler.compile("SNMPv2-CONF", ignoreErrors=True)
        self.assertEqual("missing", processed["SNMPv2-CONF"])

    def testAddFallbackSourcesIsTriedAfterEveryAddSourcesReader(self):
        calls = []

        class RecordingReader:
            def __init__(self, label):
                self.label = label

            def get_data(self, mibname, **options):
                calls.append(self.label)
                from pysmi import error

                raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self)

            def clear_cache(self):
                pass

            def __str__(self):
                return self.label

        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None))
        compiler.add_fallback_sources(RecordingReader("fallback"))
        compiler.add_sources(RecordingReader("primary"))
        compiler.compile("NO-SUCH-MIB", ignoreErrors=True)

        self.assertEqual(["primary", "fallback"], calls)


if __name__ == "__main__":
    unittest.main()
