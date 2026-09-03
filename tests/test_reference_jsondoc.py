#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The JSON document carries REFERENCE for every macro that may hold one.

The pysnmp side is asserted in test_reference_smiv2_pysnmp; three of its
classes cannot take a reference at all, so the JSON document is the only place
the clause survives for them. That makes this the load-bearing assertion for
pysnmp/mibs, which republishes the document.

See pysnmp/pysmi#100.
"""

import sys
import unittest

from tests import test_reference_smiv2_pysnmp as reference_fixtures
from tests.harness import render_json

MIB = reference_fixtures.ReferenceTestCase.__doc__

REFERENCES = {
    "testObjectIdentity": "RFC 2578 Section 4",
    "testObjectType": "RFC 2578 Section 7",
    "testNotificationType": "RFC 2578 Section 8",
    "testObjectGroup": "RFC 2580 Section 3",
    "testNotificationGroup": "RFC 2580 Section 4",
    "testModuleCompliance": "RFC 2580 Section 5",
    "testAgentCapabilities": "RFC 2580 Section 6",
}


class JsonReferenceTestCase(unittest.TestCase):
    def setUp(self):
        self.doc = render_json(MIB)

    def testEveryMacroCarriesItsReference(self):
        for symbol, reference in REFERENCES.items():
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], reference)

    def testReferenceSurvivesWherePySnmpCannotTakeIt(self):
        # ObjectGroup, ModuleCompliance and NotificationGroup have no
        # setReference(), so the document is the only artifact that keeps it.
        for symbol in ("testObjectGroup", "testModuleCompliance", "testNotificationGroup"):
            with self.subTest(symbol=symbol):
                self.assertEqual(self.doc[symbol]["reference"], REFERENCES[symbol])

    def testEveryReferenceIsDroppedWithoutTexts(self):
        doc = render_json(MIB, genTexts=False)
        for symbol in REFERENCES:
            with self.subTest(symbol=symbol):
                self.assertNotIn("reference", doc[symbol])


TC_MIB = """
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TEXTUAL-CONVENTION
        FROM SNMPv2-TC;

TestConvention ::= TEXTUAL-CONVENTION
    STATUS       current
    DESCRIPTION  "A convention."
    REFERENCE    "RFC 2579 Section 3"
    SYNTAX       OCTET STRING

END
"""


class TextualConventionReferenceTestCase(unittest.TestCase):
    """RFC 2579 section 3.5 permits REFERENCE on a TEXTUAL-CONVENTION."""

    def testConventionCarriesItsReference(self):
        self.assertEqual(render_json(TC_MIB)["TestConvention"]["reference"], "RFC 2579 Section 3")

    def testReferenceIsDroppedWithoutTexts(self):
        self.assertNotIn("reference", render_json(TC_MIB, genTexts=False)["TestConvention"])


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
