#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for the camelCase names the snake_case API replaced."""

import sys
import unittest
import warnings

from pysmi._aliases import to_camel_case
from pysmi.borrower.base import AbstractBorrower
from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.base import AbstractCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.compiler import MibCompiler, MibStatus
from pysmi.parser import SmiV2Parser
from pysmi.reader import CallbackReader
from pysmi.reader.base import AbstractReader
from pysmi.searcher.base import AbstractSearcher
from pysmi.writer import CallbackWriter
from pysmi.writer.base import AbstractWriter

# One class per part of the API a caller or an extender touches.
PUBLIC_CLASSES = [
    MibCompiler,
    MibStatus,
    AbstractReader,
    AbstractSearcher,
    AbstractWriter,
    AbstractBorrower,
    AbstractCodeGen,
    JsonCodeGen,
    PySnmpCodeGen,
    SymtableCodeGen,
]


def makeCompiler():
    """Build a compiler with nothing that reaches outside this process."""
    return MibCompiler(SmiV2Parser(), JsonCodeGen(), CallbackWriter(lambda *args: None))


class NameConversionTestCase(unittest.TestCase):
    """The old spelling has to be recoverable from the new one."""

    def testConvertsWordBoundaries(self):
        self.assertEqual(to_camel_case("add_sources"), "addSources")
        self.assertEqual(to_camel_case("get_mib_variants"), "getMibVariants")
        self.assertEqual(to_camel_case("file_exists"), "fileExists")

    def testLeavesSingleWordsAlone(self):
        self.assertEqual(to_camel_case("compile"), "compile")

    def testKnowsTheIrregularAcronym(self):
        """A name ending in an acronym cannot be derived, so it is listed."""
        self.assertEqual(to_camel_case("gen_type_declaration_rhs"), "genTypeDeclarationRHS")


class AliasCoverageTestCase(unittest.TestCase):
    """Every renamed method keeps its old name."""

    def testEveryRenamedMethodHasAnAlias(self):
        missing = []

        for cls in PUBLIC_CLASSES:
            for old, new in cls._camelCaseAliases.items():
                if not hasattr(cls, old) or not hasattr(cls, new):
                    missing.append(f"{cls.__name__}.{old}")

        self.assertEqual(missing, [])

    def testAliasesAreNotEmpty(self):
        """Guard against the decorator silently doing nothing."""
        for cls in PUBLIC_CLASSES:
            self.assertTrue(cls._camelCaseAliases, cls.__name__)


class AliasBehaviourTestCase(unittest.TestCase):
    """Both spellings do the same thing; only the old one complains."""

    def testOldNameWarnsAndForwards(self):
        compiler = makeCompiler()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            returned = compiler.addSources(CallbackReader(lambda mibname, ctx: ""))

        self.assertIs(returned, compiler)
        self.assertEqual(len(caught), 1)
        self.assertTrue(issubclass(caught[0].category, DeprecationWarning))
        self.assertIn("addSources", str(caught[0].message))
        self.assertIn("add_sources", str(caught[0].message))

    def testNewNameIsSilent(self):
        compiler = makeCompiler()

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compiler.add_sources(CallbackReader(lambda mibname, ctx: ""))

        self.assertEqual(caught, [])

    def testStaticMethodAliasForwards(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            translated = PySnmpCodeGen.transOpers("foo-bar")

        self.assertEqual(translated, PySnmpCodeGen.trans_opers("foo-bar"))
        self.assertEqual(len(caught), 1)
        self.assertIn("transOpers", str(caught[0].message))

    def testAliasKeepsTheDocumentedSignature(self):
        """Arguments and keywords reach the real method unchanged."""
        seen = {}

        def store(mibname, data, comments=(), dryRun=False):
            seen.update(mibname=mibname, data=data)

        writer = CallbackWriter(store)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            writer.putData("SOME-MIB", "body", dryRun=False)

        self.assertEqual(seen["mibname"], "SOME-MIB")
        self.assertEqual(seen["data"], "body")


class LegacySubclassTestCase(unittest.TestCase):
    """A subclass written against the old names still gets called.

    PySMI calls the new name internally, so an override under the old name
    would otherwise be inherited past and never run.
    """

    def testOverrideUnderOldNameIsInstalledUnderNew(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class LegacyReader(CallbackReader):
                def getData(self, mibname, **options):
                    return "from the legacy override"

        self.assertEqual(len(caught), 1)
        self.assertIn("getData", str(caught[0].message))
        self.assertIn("get_data", str(caught[0].message))

        reader = LegacyReader(lambda mibname, ctx: "")

        self.assertEqual(reader.get_data("SOME-MIB"), "from the legacy override")

    def testOverrideUnderNewNameIsLeftAlone(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            class ModernReader(CallbackReader):
                def get_data(self, mibname, **options):
                    return "from the modern override"

        self.assertEqual(caught, [])

        reader = ModernReader(lambda mibname, ctx: "")

        self.assertEqual(reader.get_data("SOME-MIB"), "from the modern override")

    def testRerouteSurvivesFurtherSubclassing(self):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")

            class LegacyReader(CallbackReader):
                def getData(self, mibname, **options):
                    return "outer"

            class DeeperReader(LegacyReader):
                def getData(self, mibname, **options):
                    return "inner"

        reader = DeeperReader(lambda mibname, ctx: "")

        self.assertEqual(reader.get_data("SOME-MIB"), "inner")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
