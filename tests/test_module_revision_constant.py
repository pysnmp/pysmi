#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The MODULE-IDENTITY revision, stated as data in the emitted module.

pysmi decides between two copies of a module by comparing their revisions, and
reads that from the ASN.1 (:py:func:`pysmi.compiler.revision_of`). A loader
handed generated Python has no ASN.1 to read: there the revision reaches the
output only as an argument to ``setRevisions()``, so getting it back means
running the module or pattern-matching its source.

``PYSNMP_MODULE_REVISION`` states it as a module-level constant instead, so the
same comparison is available to anything that can parse Python. See
pysnmp/pysnmp#198.
"""

import ast
import unittest

from pysmi.codegen import PySnmpCodeGen
from pysmi.mibinfo import normalise_revision
from tests.harness import symbol_table

CONSTANT = "PYSNMP_MODULE_REVISION"

#: Two revisions, so the newest is the one that has to be picked.
REVISED_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    LAST-UPDATED "200210160000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "Module."
    REVISION     "200210160000Z"
    DESCRIPTION  "Newer."
    REVISION     "199511090000Z"
    DESCRIPTION  "Older."
    ::= { 1 3 0 }

END
"""

#: The two-digit-year form RFC 2578 Section 2 also allows.
SHORT_YEAR_MIB = (
    REVISED_MIB.replace("TEST-MIB", "SHORT-MIB")
    .replace('"200210160000Z"', '"9908190000Z"')
    .replace('"199511090000Z"', '"9501010000Z"')
)

#: No MODULE-IDENTITY at all -- every SMIv1 module, and the SMI modules.
UNDATED_MIB = """
UNDATED-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { 1 3 1 }

END
"""


def constant_in(source):
    """The constant's value, read by parsing rather than by executing.

    Reading it must not require running the module: a loader choosing between
    two candidates would otherwise have to execute both to compare them, and
    executing a pysnmp MIB registers its symbols as a side effect.
    """
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == CONSTANT for t in node.targets
        ):
            return ast.literal_eval(node.value)

    return None


def render(mib, codegen=None):
    """Render *mib*, optionally through a codegen already used for another."""
    tree, _, table = symbol_table(mib)

    return (codegen or PySnmpCodeGen()).gen_code(tree, table, genTexts=True)[1]


class NormaliseRevisionTestCase(unittest.TestCase):
    def testTheShortFormIsWidened(self):
        self.assertEqual("199908190000Z", normalise_revision("9908190000Z"))

    def testTheWideFormIsUntouched(self):
        self.assertEqual("200210160000Z", normalise_revision("200210160000Z"))

    def testSeventyIsThePivot(self):
        """RFC 2578 Section 2 reads 70-99 as 1900s and 00-69 as 2000s."""
        self.assertEqual("197001010000Z", normalise_revision("7001010000Z"))
        self.assertEqual("206901010000Z", normalise_revision("6901010000Z"))


class ModuleRevisionConstantTestCase(unittest.TestCase):
    def testTheNewestRevisionIsStated(self):
        self.assertEqual("200210160000Z", constant_in(render(REVISED_MIB)))

    def testAModuleWithoutModuleIdentityStatesNothing(self):
        self.assertIsNone(constant_in(render(UNDATED_MIB)))

    def testTheConstantIsReadableWithoutExecutingTheModule(self):
        """`constant_in` never runs the source, and still gets the value."""
        source = render(REVISED_MIB)

        self.assertIn(CONSTANT, source)
        self.assertEqual("200210160000Z", constant_in(source))

    def testAShortYearIsWidenedSoThatStampsSortChronologically(self):
        """Emitting the raw stamp would put 1999 above 2002.

        ``"9908190000Z" > "200210160000Z"`` as strings, so a consumer comparing
        the constants directly would take the older module. The 24 bundled
        modules using the short form make this the live case, not a corner one.
        """
        short = constant_in(render(SHORT_YEAR_MIB))

        self.assertEqual("199908190000Z", short)
        self.assertLess(short, constant_in(render(REVISED_MIB)))

    def testOneCodegenDoesNotCarryARevisionIntoTheNextModule(self):
        """`gen_code` resets it with the rest of the per-module state.

        It did not, and a corpus build reuses one codegen across every module,
        so a module carrying no MODULE-IDENTITY inherited whichever revision the
        previous module had -- into its MibInfo, and into this constant.
        """
        codegen = PySnmpCodeGen()
        dated = render(REVISED_MIB, codegen)
        undated = render(UNDATED_MIB, codegen)

        self.assertEqual("200210160000Z", constant_in(dated))
        self.assertIsNone(constant_in(undated))


if __name__ == "__main__":
    unittest.main()
