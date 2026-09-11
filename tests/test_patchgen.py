#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Deriving a MIB's repair as a diff instead of making it in memory.

pysmi repairs a missing base-SMI import as a module compiles, which leaves the
source alone and the correction unrecorded. :py:mod:`pysmi.patchgen` works out
the same correction and writes it into the module's *text*, so it can be kept
as a patch.

The claim these tests are here to hold is one thing, stated at the end: a module
that fails ``repairImports=False`` before its generated patch is applied passes
afterwards. Everything above that checks the diff is one a human would want to
read -- minimal, in the module's own layout, and the same bytes on a second run.
"""

import unittest

from pysmi import error
from pysmi.patches import ALREADY_APPLIED, APPLIED, NOT_APPLICABLE, apply_patch
from pysmi.patchgen import (
    CLEAN,
    REPAIRABLE,
    UNPARSEABLE,
    inspect,
    missing_imports,
    repair_imports,
)
from tests import mibs
from tests.harness import symbol_table
from tests.test_repair_imports import BROKEN, NO_IMPORTS_CLAUSE

DEPS = (mibs.SNMPV2_SMI, mibs.SNMPV2_TC, mibs.SNMPV2_MIB)

#: A module that imports everything it uses, so nothing is derived for it.
CLEAN_MIB = """CLEAN-MIB DEFINITIONS ::= BEGIN

IMPORTS
    OBJECT-TYPE, Integer32, enterprises
        FROM SNMPv2-SMI;

fineObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION
        "An object relying on nothing the module left out."
    ::= { enterprises 99999 1 }

END
"""


def compiles_strictly(text):
    """Whether *text* builds a symbol table with the in-memory repair turned off."""
    try:
        symbol_table(text, deps=DEPS, repairImports=False)

    except error.PySmiError:
        return False

    return True


class DerivedDiffTestCase(unittest.TestCase):
    """What comes out is a diff a reviewer can read."""

    def testTheSymbolGoesOnTheExistingFromLineWhenThereIsOne(self):
        """A module already importing from SNMPv2-SMI gains a one-line diff."""
        defect = inspect(BROKEN["Opaque"])

        self.assertEqual(REPAIRABLE, defect.status)
        self.assertIn("-    OBJECT-TYPE\n", defect.patch)
        self.assertIn("+    OBJECT-TYPE, Opaque\n", defect.patch)

    def testANewFromGroupOpensWhenTheModuleIsNotImportedYet(self):
        """SNMPv2-TC is not in the clause, so the symbol cannot join a group."""
        defect = inspect(BROKEN["TruthValue"])

        self.assertEqual(REPAIRABLE, defect.status)
        self.assertIn("+    TruthValue\n", defect.patch)
        self.assertIn("+        FROM SNMPv2-TC;\n", defect.patch)

    def testTheTerminatingSemicolonMovesToTheNewGroup(self):
        """Otherwise the clause would end twice, or not at all."""
        defect = inspect(BROKEN["TruthValue"])

        self.assertIn("-        FROM SNMPv2-SMI;\n", defect.patch)
        self.assertIn("+        FROM SNMPv2-SMI\n", defect.patch)

    def testAWholeClauseIsWrittenForAModuleWithNone(self):
        """A module with no IMPORTS at all has nothing to append to."""
        defect = inspect(NO_IMPORTS_CLAUSE)

        self.assertEqual(REPAIRABLE, defect.status)
        self.assertIn("+IMPORTS\n", defect.patch)
        self.assertIn("+        FROM SNMPv2-SMI\n", defect.patch)
        self.assertIn("+        FROM SNMPv2-TC;\n", defect.patch)

    def testTheDiffNamesTheModuleRatherThanAFile(self):
        """A patch is keyed by module name, so its headers carry that name."""
        defect = inspect(BROKEN["Opaque"], mibname="whatever-the-file-was-called")

        self.assertTrue(defect.patch.startswith("--- a/REPAIR-SMI-TYPE-MIB\n"))
        self.assertIn("+++ b/REPAIR-SMI-TYPE-MIB\n", defect.patch)

    def testTheSameModuleDerivesTheSameBytesTwice(self):
        """A regenerated patch that differs would churn every review."""
        self.assertEqual(
            inspect(NO_IMPORTS_CLAUSE).patch, inspect(NO_IMPORTS_CLAUSE).patch
        )

    def testOnlyTheImportsClauseIsTouched(self):
        """A diff reaching the objects would be a rewrite, not a repair."""
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                added = [
                    line
                    for line in inspect(text).patch.split("\n")
                    if line.startswith("+") and not line.startswith("+++")
                ]

                self.assertTrue(added)
                self.assertTrue(
                    all("FROM" in line or symbol in line for line in added), added
                )


class NothingToDeriveTestCase(unittest.TestCase):
    """Modules that get no patch, and the two different reasons for it."""

    def testAModuleImportingWhatItUsesIsClean(self):
        defect = inspect(CLEAN_MIB)

        self.assertEqual(CLEAN, defect.status)
        self.assertEqual("", defect.patch)
        self.assertEqual({}, defect.imports)

    def testAModuleThatDoesNotParseIsReportedRatherThanGuessedAt(self):
        """No symbol table means no correction can be worked out."""
        defect = inspect("this is not a MIB at all {{{", mibname="GARBAGE-MIB")

        self.assertEqual(UNPARSEABLE, defect.status)
        self.assertEqual("", defect.patch)
        self.assertIn("Bad grammar", defect.reason)

    def testAnUnparseableModuleKeepsTheNameItWasGiven(self):
        """It cannot be asked its own name, so the file's name has to do."""
        self.assertEqual(
            "GARBAGE-MIB", inspect("not a MIB {{{", mibname="GARBAGE-MIB").mibname
        )

    def testRepairingWithNothingMissingChangesNothing(self):
        self.assertEqual(CLEAN_MIB, repair_imports(CLEAN_MIB, {}))


class SameAnswerAsTheCompilerTestCase(unittest.TestCase):
    """The generator must not have its own opinion about what is broken."""

    def testItFindsWhatTheSymbolTableWouldHaveRepaired(self):
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                _, missing = missing_imports(text)

                self.assertIn(symbol, missing)

    def testItFindsNothingInAModuleTheCompilerWouldNotRepair(self):
        self.assertEqual(
            ({}, "CLEAN-MIB"), (missing_imports(CLEAN_MIB)[1], "CLEAN-MIB")
        )

    def testAnUnparseableModuleRaisesRatherThanReturningEmpty(self):
        with self.assertRaises(error.PySmiError):
            missing_imports("this is not a MIB at all {{{")


class RoundTripTestCase(unittest.TestCase):
    """A derived patch behaves like a hand-written one."""

    def testTheDiffAppliesToTheTextItWasCutFrom(self):
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                defect = inspect(text)

                self.assertEqual(
                    APPLIED, apply_patch(text, defect.patch, defect.mibname)[1]
                )

    def testOfferingItTwiceIsDetectedRatherThanDoubleApplied(self):
        """--apply over an already patched tree must be a no-op, not a mess."""
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                defect = inspect(text)
                patched, _ = apply_patch(text, defect.patch, defect.mibname)

                self.assertEqual(
                    ALREADY_APPLIED,
                    apply_patch(patched, defect.patch, defect.mibname)[1],
                )

    def testAPatchedModuleNeedsNoFurtherRepair(self):
        """Rerunning the generator over a patched tree derives nothing."""
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                defect = inspect(text)
                patched, _ = apply_patch(text, defect.patch, defect.mibname)

                self.assertEqual(CLEAN, inspect(patched).status)

    def testTheDiffDoesNotApplyToAModuleItWasNotCutFrom(self):
        defect = inspect(BROKEN["Opaque"])

        self.assertEqual(
            NOT_APPLICABLE, apply_patch(CLEAN_MIB, defect.patch, defect.mibname)[1]
        )

    def testLineEndingsSurviveTheRepair(self):
        """A CRLF module stays CRLF, since patching is not a reformat."""
        crlf = BROKEN["Opaque"].replace("\n", "\r\n")
        _, missing = missing_imports(crlf)
        repaired = repair_imports(crlf, missing)

        self.assertIn("\r\n", repaired)
        self.assertEqual(repaired.count("\n"), repaired.count("\r\n"))

    def testALfModuleDoesNotGainCarriageReturns(self):
        lf = BROKEN["Opaque"]
        _, missing = missing_imports(lf)

        self.assertNotIn("\r", repair_imports(lf, missing))


class ReplacesTheRuntimeRepairTestCase(unittest.TestCase):
    """The point of the whole tool.

    Each of these modules fails to compile with ``repairImports`` off, and
    compiles with it still off once its generated patch has been applied. That
    is what lets a tree be patched once and compiled strictly forever after,
    with the in-memory repair never consulted.
    """

    def testEveryBrokenModuleFailsStrictlyBeforeItIsPatched(self):
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                self.assertFalse(compiles_strictly(text))

    def testEveryBrokenModuleCompilesStrictlyOnceItIsPatched(self):
        for symbol, text in BROKEN.items():
            with self.subTest(symbol=symbol):
                defect = inspect(text)
                patched, status = apply_patch(text, defect.patch, defect.mibname)

                self.assertEqual(APPLIED, status)
                self.assertTrue(compiles_strictly(patched), defect.patch)

    def testTheModuleWithNoImportsClauseCompilesStrictlyOnceItIsPatched(self):
        defect = inspect(NO_IMPORTS_CLAUSE)
        patched, status = apply_patch(NO_IMPORTS_CLAUSE, defect.patch, defect.mibname)

        self.assertEqual(APPLIED, status)
        self.assertFalse(compiles_strictly(NO_IMPORTS_CLAUSE))
        self.assertTrue(compiles_strictly(patched), defect.patch)


if __name__ == "__main__":
    unittest.main()
