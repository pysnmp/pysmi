#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A DISPLAY-HINT is carried, not interpreted.

RFC 2579 section 3.1 gives the format grammar. pysmi passes the hint through to
both backends verbatim, so these assert faithful pass-through of every shape
the standard textual conventions use rather than validating the grammar.

See pysnmp/pysmi#95.
"""

import sys
import unittest

from tests.harness import render_json, render_source

MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

TestConvention ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "%s"
    STATUS       current
    DESCRIPTION  "The convention under test."
    SYNTAX       %s

END
"""

HINTS = {
    "octetPairsWithColons": ("1x:", "OCTET STRING"),
    "repeatCountWithAscii": ("255a", "OCTET STRING"),
    "dottedDecimal": ("1d.1d.1d.1d", "OCTET STRING"),
    "dateAndTime": ("2d-1d-1d,1d:1d:1d.1d,1a1d:1d", "OCTET STRING"),
    "octal": ("1o", "OCTET STRING"),
    "binary": ("1b", "OCTET STRING"),
    "dynamicLength": ("*1x:", "OCTET STRING"),
    "integerDecimal": ("d", "INTEGER"),
    "integerScaled": ("d-2", "INTEGER"),
}


class DisplayHintTestCase(unittest.TestCase):
    """Every hint reaches both artifacts exactly as it was written."""

    def testEveryFormSurvivesIntoBothArtifacts(self):
        for name, (hint, syntax) in HINTS.items():
            with self.subTest(form=name, hint=hint):
                mib = MIB % (hint, syntax)
                self.assertEqual(render_json(mib)["TestConvention"]["displayhint"], hint)
                self.assertIn(f"    displayHint = '{hint}'", render_source(mib))

    def testAbsentHintProducesNoKey(self):
        # An absent hint must not become an empty one: "" is a hint that renders
        # every value as blank, not the absence of a hint.
        mib = MIB.replace('    DISPLAY-HINT "%s"\n', "") % "OCTET STRING"
        self.assertNotIn("displayhint", render_json(mib)["TestConvention"])
        self.assertNotIn("displayHint", render_source(mib))

    def testHintSurvivesWithoutTexts(self):
        # The hint says how to render a value, so it is not narrative and is
        # kept when DESCRIPTION and REFERENCE are dropped.
        mib = MIB % ("1x:", "OCTET STRING")
        doc = render_json(mib, genTexts=False)
        self.assertEqual(doc["TestConvention"]["displayhint"], "1x:")
        self.assertNotIn("description", doc["TestConvention"])
        self.assertIn("    displayHint = '1x:'", render_source(mib, genTexts=False))


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
