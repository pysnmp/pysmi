#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""MibCompiler.prune removes stored output whose source MIB no longer
exists anywhere among the configured readers -- compile only ever acts on
MIBs it is asked for, so nothing else notices a MIB was removed upstream.
See pysnmp/pysmi#61.
"""

import os
import tempfile
import unittest

from pysmi import error
from pysmi.codegen import JsonCodeGen
from pysmi.compiler import MibCompiler
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import FileReader
from pysmi.writer import CallbackWriter, FileWriter

MIB_A = "MIB-A DEFINITIONS ::= BEGIN END\n"
MIB_B = "MIB-B DEFINITIONS ::= BEGIN END\n"

# The compiler resolves these whether or not a module names them, so the
# source directory has to hold something for each.
IMPLICIT_BASE_MIBS = ("SNMPv2-SMI", "SNMPv2-TC", "SNMPv2-CONF")


class MibCompilerPruneTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.src = os.path.join(self._tmp.name, "src")
        self.dst = os.path.join(self._tmp.name, "dst")
        os.mkdir(self.src)

        with open(os.path.join(self.src, "MIB-A"), "w") as fp:
            fp.write(MIB_A)

        with open(os.path.join(self.src, "MIB-B"), "w") as fp:
            fp.write(MIB_B)

        for mib in IMPLICIT_BASE_MIBS:
            with open(os.path.join(self.src, mib), "w") as fp:
                fp.write(f"{mib} DEFINITIONS ::= BEGIN\nEND\n")

        self.writer = FileWriter(self.dst).set_options(suffix=".json")
        self.compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), self.writer)
        self.compiler.add_sources(FileReader(self.src))
        self.compiler.compile("MIB-A", "MIB-B")

    def tearDown(self):
        self._tmp.cleanup()

    def testNothingIsPrunedWhileEverySourceStillExists(self):
        processed = self.compiler.prune()

        self.assertEqual("untouched", processed["MIB-A"])
        self.assertEqual("untouched", processed["MIB-B"])
        self.assertIn("MIB-A.json", os.listdir(self.dst))
        self.assertIn("MIB-B.json", os.listdir(self.dst))

    def testARemovedSourceIsPruned(self):
        os.unlink(os.path.join(self.src, "MIB-B"))

        processed = self.compiler.prune()

        self.assertEqual("untouched", processed["MIB-A"])
        self.assertEqual("pruned", processed["MIB-B"])
        self.assertIn("MIB-A.json", os.listdir(self.dst))
        self.assertNotIn("MIB-B.json", os.listdir(self.dst))

    def testDryRunReportsWithoutRemoving(self):
        os.unlink(os.path.join(self.src, "MIB-B"))

        processed = self.compiler.prune(dryRun=True)

        self.assertEqual("pruned", processed["MIB-B"])
        self.assertIn("MIB-B.json", os.listdir(self.dst))

    def testAHandWrittenFileInTheDestinationIsNeverPruned(self):
        os.unlink(os.path.join(self.src, "MIB-B"))

        with open(os.path.join(self.dst, "HAND-WRITTEN.json"), "w") as fp:
            fp.write('{"hand": "written"}')

        processed = self.compiler.prune()

        self.assertNotIn("HAND-WRITTEN", processed)
        self.assertIn("HAND-WRITTEN.json", os.listdir(self.dst))

    def testAWriterThatCannotEnumerateItsOutputIsSkippedWithoutError(self):
        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(lambda *a: None))
        compiler.add_sources(FileReader(self.src))

        self.assertEqual({}, compiler.prune())

    def testAnUnreadableSourceIsNotTreatedAsRemoved(self):
        # A source that cannot even be asked -- as opposed to one that
        # cleanly answers "not found" -- is not evidence the MIB is gone, so
        # ignoreErrors keeps rather than prunes it.
        class BrokenReader:
            def get_data(self, mibname, **options):
                if mibname == "MIB-A":
                    raise error.PySmiReaderFileNotFoundError(mibname=mibname, reader=self)
                raise error.PySmiError("reader is down")

            def clear_cache(self):
                pass

            def __str__(self):
                return "BrokenReader"

        os.unlink(os.path.join(self.src, "MIB-A"))
        os.unlink(os.path.join(self.src, "MIB-B"))

        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), self.writer)
        compiler.add_sources(BrokenReader())

        processed = compiler.prune(ignoreErrors=True)

        self.assertEqual("pruned", processed["MIB-A"])
        self.assertEqual("untouched", processed["MIB-B"])

    def testAnUnreadableSourceWithoutIgnoreErrorsRaises(self):
        class BrokenReader:
            def get_data(self, mibname, **options):
                raise error.PySmiError("reader is down")

            def clear_cache(self):
                pass

            def __str__(self):
                return "BrokenReader"

        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), self.writer)
        compiler.add_sources(BrokenReader())

        with self.assertRaises(error.PySmiError):
            compiler.prune()

    def testAWriterThatFailsToRemoveIsReportedAsFailedWithIgnoreErrors(self):
        class FailingDeleteWriter(FileWriter):
            def del_data(self, mibname, dryRun=False):
                raise error.PySmiWriterError(f"cannot remove {mibname}", writer=self)

        os.unlink(os.path.join(self.src, "MIB-B"))

        writer = FailingDeleteWriter(self.dst).set_options(suffix=".json")
        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), writer)
        compiler.add_sources(FileReader(self.src))

        processed = compiler.prune(ignoreErrors=True)

        self.assertEqual("failed", processed["MIB-B"])
        self.assertIn("MIB-B.json", os.listdir(self.dst))

    def testAWriterThatFailsToRemoveRaisesWithoutIgnoreErrors(self):
        class FailingDeleteWriter(FileWriter):
            def del_data(self, mibname, dryRun=False):
                raise error.PySmiWriterError(f"cannot remove {mibname}", writer=self)

        os.unlink(os.path.join(self.src, "MIB-B"))

        writer = FailingDeleteWriter(self.dst).set_options(suffix=".json")
        compiler = MibCompiler(SmiV1CompatParser(), JsonCodeGen(), writer)
        compiler.add_sources(FileReader(self.src))

        with self.assertRaises(error.PySmiError):
            compiler.prune()

    def testABaseMibResolvableThroughTheBundledFallbackIsNeverPruned(self):
        # SNMPv2-SMI compiled to self.dst as a dependency of MIB-A/MIB-B in
        # setUp. Its user-supplied stub disappearing must not make prune
        # treat it as gone -- pysmi's own bundled copy still resolves it,
        # see pysnmp/pysmi#113, and that has to count as "still sourced" the
        # same way a user source would.
        os.unlink(os.path.join(self.src, "SNMPv2-SMI"))

        processed = self.compiler.prune()

        self.assertEqual("untouched", processed["SNMPv2-SMI"])
        self.assertIn("SNMPv2-SMI.json", os.listdir(self.dst))


if __name__ == "__main__":
    unittest.main()
