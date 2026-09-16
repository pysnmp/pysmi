#
# This file is part of pysmi software.
#
# Copyright (c) 2005-2019, Ilya Etingof deceased
#
"""Taking one module out of a file that holds several.

A vendor publishing a product line as one file is an ordinary shape, and a
corpus keyed by module name has nowhere to put such a file but under each of
the names in it. Publishing the whole file under every one of them is what
that used to cost: in pysnmp/mibs, 758 KB of ASN.1 declaring 34 modules became
26 MB of published tree, and nothing ever asks for the file by its own name.

What is pinned here is the extraction: the boundaries come from the lexer, so
the word END inside a DESCRIPTION is text; the vendor's copyright header
survives onto every module, because that is what it is there for; and a file
holding one module comes back byte for byte, because that is nearly every file
in a corpus and none of them should change.
"""

import textwrap
import unittest

from pysmi.mibinfo import module_names, module_text

ONE = textwrap.dedent(
    """\
    -- (c) 1997 Example Networks
    ONLY-MIB DEFINITIONS ::= BEGIN
    IMPORTS MODULE-IDENTITY FROM SNMPv2-SMI;
    onlyThing OBJECT-TYPE
        DESCRIPTION "The word END appears here, and in the middle: END."
        ::= { 1 2 3 }
    END
    """
)

PAIR = textwrap.dedent(
    """\
    -- (c) 1997 Example Networks
    -- Every module in this file is covered by the notice above.

    FIRST-MIB DEFINITIONS ::= BEGIN
    firstThing OBJECT-TYPE
        DESCRIPTION "Ends with the word END."
        ::= { 1 2 3 }
    END

    --
    -- The second product line
    --

    SECOND-MIB DEFINITIONS ::= BEGIN
    secondThing OBJECT-TYPE
        DESCRIPTION "Also fine."
        ::= { 1 2 4 }
    END
    """
)


class ModuleTextTestCase(unittest.TestCase):
    """What is published for one module out of a file."""

    def testAFileHoldingOneModuleIsUnchanged(self):
        """Nearly every file in a corpus, and none of them may move a byte."""
        self.assertEqual(ONE, module_text(ONE, "ONLY-MIB"))

    def testEachModuleComesBackAlone(self):
        """The point: one name, one module."""
        for name, other in (("FIRST-MIB", "SECOND-MIB"), ("SECOND-MIB", "FIRST-MIB")):
            with self.subTest(module=name):
                found = module_text(PAIR, name)

                self.assertEqual([name], module_names(found))
                self.assertNotIn(f"{other} DEFINITIONS", found)

    def testTheModuleTextIsVerbatim(self):
        """The result is the input rearranged, not rewritten."""
        for name in ("FIRST-MIB", "SECOND-MIB"):
            with self.subTest(module=name):
                found = module_text(PAIR, name)
                body = found[found.index(f"{name} DEFINITIONS") :].rstrip()

                self.assertIn(body, PAIR)

    def testTheSharedHeaderIsKeptOnEachModule(self):
        """A vendor's copyright covers every module in the file it heads."""
        for name in ("FIRST-MIB", "SECOND-MIB"):
            with self.subTest(module=name):
                self.assertIn("(c) 1997 Example Networks", module_text(PAIR, name))

    def testTheCommentIntroducingAModuleGoesWithIt(self):
        """So no text in the file is lost by the split."""
        self.assertIn("The second product line", module_text(PAIR, "SECOND-MIB"))
        self.assertNotIn("The second product line", module_text(PAIR, "FIRST-MIB"))

    def testAnEndInsideADescriptionIsNotABoundary(self):
        """The lexer decides, so prose containing the keyword stays prose."""
        found = module_text(PAIR, "FIRST-MIB")

        self.assertIn('DESCRIPTION "Ends with the word END."', found)

    def testANameTheFileDoesNotDeclareLeavesItAlone(self):
        """Nothing is invented for a module that is not in the text."""
        self.assertEqual(PAIR, module_text(PAIR, "ABSENT-MIB"))

    def testTextThatIsNotAMibIsUnchanged(self):
        """A reader handed a login page must get back what it was handed."""
        self.assertEqual(
            "<html>not a MIB</html>", module_text("<html>not a MIB</html>", "X-MIB")
        )


if __name__ == "__main__":
    unittest.main()
