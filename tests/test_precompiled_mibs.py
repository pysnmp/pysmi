#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The wheel carries a pysnmp module for every MIB pysmi bundles.

``hatch_build.py`` generates them as the wheel is built, so nothing in the
repository shows whether the generation still works -- only a release would,
and only by failing. This runs the same function the hook runs. That the
output then loads is asserted in the consumer-layer test file, the only one
allowed to reach pysnmp.
"""

import pathlib
import shutil
import unittest

from hatch_build import build
from pysmi.codegen import PySnmpCodeGen

ROOT = pathlib.Path(__file__).parent.parent


class PrecompiledMibsTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = build(ROOT)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.out, ignore_errors=True)

    def testEveryGeneratableBundledMibHasACompiledModule(self):
        """Every bundled MIB is compiled except the ones that cannot be.

        The pysnmp back end emits an unconditional import from each module in
        ``constImports``, so rendering one of those modules produces an import
        from itself, which can never resolve. Those three are stubbed rather
        than emitted broken. See pysnmp/pysmi#196.
        """
        bundled = {
            entry.name
            for entry in (ROOT / "pysmi" / "mibs" / "asn1").iterdir()
            if entry.is_file() and not entry.name.startswith("__")
        }
        ungeneratable = frozenset(PySnmpCodeGen.constImports) - frozenset(
            PySnmpCodeGen.fakeMibs
        )
        compiled = {
            entry.stem for entry in self.out.iterdir() if entry.name != "__init__.py"
        }

        self.assertEqual(bundled - ungeneratable, compiled)

    def testTheGeneratedDirectoryIsAPackage(self):
        self.assertTrue((self.out / "__init__.py").is_file())

    def testACompiledModuleCarriesTheSymbolsItsMibDefines(self):
        source = (self.out / "IF-MIB.py").read_text()

        self.assertIn("ifDescr", source)
        self.assertIn("MibTableColumn", source)


if __name__ == "__main__":
    unittest.main()
