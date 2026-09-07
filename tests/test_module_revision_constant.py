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
same comparison is available to anything that can parse Python. It carries
LAST-UPDATED, because that is what ``revision_of`` compares -- a constant
carrying anything else would let the two disagree about which copy wins. See
pysnmp/pysnmp#198.
"""

import ast
import unittest
from importlib import resources

from pysmi.codegen import PySnmpCodeGen
from pysmi.compiler import MibCompiler, revision_of
from pysmi.mibinfo import normalise_revision, strip_comments
from pysmi.parser import SmiV1CompatParser
from pysmi.reader import PackageReader
from pysmi.writer import CallbackWriter
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

#: A MODULE-IDENTITY with no REVISION clause. RFC 2578 Section 5.5 requires
#: LAST-UPDATED and makes REVISION optional, and 50 of the bundled modules are
#: written this way.
NO_REVISION_MIB = """
NOREV-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    LAST-UPDATED "200210160000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "No REVISION clause."
    ::= { 1 3 0 }

END
"""

#: LAST-UPDATED newer than the newest REVISION, as eight bundled modules are.
LATER_UPDATE_MIB = REVISED_MIB.replace("TEST-MIB", "LATER-MIB").replace(
    'LAST-UPDATED "200210160000Z"', 'LAST-UPDATED "202002181507Z"'
)

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
    def testTheRevisionIsStated(self):
        self.assertEqual("200210160000Z", constant_in(render(REVISED_MIB)))

    def testAModuleWithNoRevisionClauseStillStatesOne(self):
        """LAST-UPDATED is what is carried, and REVISION is optional.

        Reading the newest REVISION instead left 50 of the 365 bundled modules
        with no constant at all, while `revision_of` had a LAST-UPDATED to
        compare for every one of them -- so pysmi could choose between two
        copies and a loader could not.
        """
        self.assertEqual("200210160000Z", constant_in(render(NO_REVISION_MIB)))

    def testLastUpdatedWinsOverAnOlderRevisionClause(self):
        """The two disagree in eight bundled modules, LAST-UPDATED newer each time.

        `revision_of` compares LAST-UPDATED. A constant carrying the newest
        REVISION would make a loader pick the other copy in exactly those cases.
        """
        self.assertEqual("202002181507Z", constant_in(render(LATER_UPDATE_MIB)))

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


class CommentedOutModuleIdentityTestCase(unittest.TestCase):
    """`revision_of` reads raw text, so it has to skip ASN.1 comments.

    ATM-FORUM-MIB and the three LAN-EMULATION modules carry a MODULE-IDENTITY
    that is commented out with ``--``. The parser ignores it and emits no
    constant, but the regex matched inside it, so pysmi reported a revision for
    a module that has none -- and would have let a commented-out timestamp
    decide which copy of a module wins.
    """

    COMMENTED = """
COMMENTED-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI;

--  commentedModule MODULE-IDENTITY
--      LAST-UPDATED "200003010000Z"
--      ORGANIZATION "Org."
--      ::= { 1 3 0 }

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An object."
    ::= { 1 3 1 }

END
"""

    def testACommentedOutLastUpdatedIsNotARevision(self):
        self.assertIsNone(revision_of(self.COMMENTED))

    def testARealLastUpdatedIsStillFound(self):
        self.assertEqual("200210160000Z", revision_of(NO_REVISION_MIB))


class StripCommentsTestCase(unittest.TestCase):
    """`strip_comments` has to know where a string is.

    None of the 365 bundled modules puts a ``--`` inside a quoted value ahead
    of its LAST-UPDATED, so the whole-bundle comparison below passes just as
    happily with a string-unaware stripper. These pin the property directly.
    """

    def testACommentRunsToEndOfLine(self):
        self.assertEqual("a \nb", strip_comments("a -- comment\nb"))

    def testASecondPairClosesTheComment(self):
        self.assertEqual(" keep", strip_comments("-- gone -- keep"))

    def testNewlinesSurvive(self):
        self.assertEqual("a \nb \n", strip_comments("a -- x\nb -- y\n"))

    def testHyphensInsideAStringAreNotAComment(self):
        """The case that makes a regex wrong.

        ``--.*?(?:--|$)`` deletes from the hyphens in the DESCRIPTION to the
        end of the line, taking the LAST-UPDATED with it, and `revision_of`
        then reports nothing for a module that states a revision.
        """
        line = 'DESCRIPTION "a -- b" LAST-UPDATED "200210160000Z"'

        self.assertEqual(line, strip_comments(line))

    def testADoubledQuoteDoesNotEndTheString(self):
        line = 's "quote "" inside -- still" tail'

        self.assertEqual(line, strip_comments(line))

    def testRevisionOfSurvivesHyphensInAString(self):
        mib = """
HYPHEN-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY
        FROM SNMPv2-SMI;

testModule MODULE-IDENTITY
    DESCRIPTION "Range is 1--10." LAST-UPDATED "200210160000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    ::= { 1 3 0 }

END
"""

        self.assertEqual("200210160000Z", revision_of(mib))


class ConstantMatchesTheCompilerTestCase(unittest.TestCase):
    """The property the constant exists for, over every module pysmi bundles.

    A loader comparing constants has to reach the same answer the compiler
    reaches comparing ASN.1. That only holds if the constant carries exactly
    what `revision_of` returns, for every module and for the modules where it
    returns nothing. Anything less and the two disagree about which copy of a
    module wins, silently.
    """

    def testEveryBundledModuleAgreesWithRevisionOf(self):
        sources = resources.files("pysmi.mibs.asn1")
        names = sorted(
            entry.name
            for entry in sources.iterdir()
            if entry.is_file() and not entry.name.startswith("__")
        )
        rendered = {}
        compiler = MibCompiler(
            SmiV1CompatParser(),
            PySnmpCodeGen(),
            CallbackWriter(
                lambda mibname, data, cbCtx: rendered.__setitem__(mibname, data)
            ),
            useBundledMibs=False,
        )
        compiler.add_sources(PackageReader("pysmi.mibs.asn1"))
        compiler.compile(*names, noDeps=True, rebuild=True)

        # Every bundled module has to render. Skipping the ones that did not
        # would let a compile failure pass this test without its module ever
        # being compared -- the same silent pass the constant exists to remove.
        self.assertEqual(sorted(rendered), names)

        for name in names:
            asn1 = sources.joinpath(name).read_text(encoding="utf-8", errors="replace")

            with self.subTest(module=name):
                self.assertEqual(revision_of(asn1), constant_in(rendered[name]))


if __name__ == "__main__":
    unittest.main()
