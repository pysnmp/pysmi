#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""A MIB symbol spelled like a Python keyword reaches both back ends.

``global``, ``if``, ``in``, ``as`` and ``continue`` are ordinary SMI
descriptors -- RFC 2578 says a descriptor is letters, digits and hyphens, and
has nothing to say about Python. Vendors use them: 13 modules in the corpus
pysnmp/mibs builds do, and every one of them compiled to a pysnmp module and
failed to a JSON document, because the symbol table both back ends read is
keyed by the ``pysmi_``-prefixed spelling and only one of them addressed it
that way. The two output trees then described different sets of modules, and
because a module that fails takes down what imports it, 212 more went with the
13.

See pysnmp/pysmi#225.
"""

import unittest
from keyword import iskeyword

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from tests.harness import render_json, render_source
from tests.mibs import SNMPV2_SMI

KEYWORDS = ("global", "if", "in", "as", "continue")


def module(symbol):
    """A module registering an arc under *symbol* and an object beneath it."""
    return f"""
TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, OBJECT-IDENTITY, Integer32, enterprises
        FROM SNMPv2-SMI;

testMI MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "test"
    CONTACT-INFO "test"
    DESCRIPTION  "a module whose symbol is a Python keyword"
    ::= {{ enterprises 99999 }}

{symbol} OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "an arc named for a Python keyword"
    ::= {{ testMI 1 }}

testObject OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "hangs off that arc, so the name is resolved as well as defined"
    ::= {{ {symbol} 1 }}
END
"""


class TranslationTestCase(unittest.TestCase):
    """Every back end spells a symbol the way the symbol table is keyed."""

    def testTheKeywordPrefixIsTheSymbolTablesOwn(self):
        for keyword in KEYWORDS:
            with self.subTest(keyword=keyword):
                expected = SymtableCodeGen.trans_opers(keyword)

                self.assertEqual(expected, JsonCodeGen.trans_opers(keyword))
                self.assertEqual(expected, PySnmpCodeGen.trans_opers(keyword))

    def testHyphensAreStillTranslated(self):
        self.assertEqual("foo_bar", JsonCodeGen.trans_opers("foo-bar"))

    def testAnOrdinaryNameIsUntouched(self):
        self.assertEqual("ifDescr", JsonCodeGen.trans_opers("ifDescr"))

    def testTheKeywordsUsedHereReallyAreKeywords(self):
        """Guard the fixture: Python's keyword list is what defines the case."""
        for keyword in KEYWORDS:
            self.assertTrue(iskeyword(keyword), keyword)


class DocumentTestCase(unittest.TestCase):
    """The JSON document is produced at all, and describes what the MIB says."""

    def testEveryKeywordSymbolReachesTheDocument(self):
        for keyword in KEYWORDS:
            with self.subTest(keyword=keyword):
                document = render_json(module(keyword), deps=[SNMPV2_SMI])

                self.assertIn(f"pysmi_{keyword}", document)

    def testTheArcIsResolvedForWhatHangsOffIt(self):
        # The failure was not only in defining the symbol: an object whose
        # OID names it has to resolve that name through the symbol table,
        # which is the lookup that was being made under the wrong spelling.
        document = render_json(module("global"), deps=[SNMPV2_SMI])

        self.assertEqual("1.3.6.1.4.1.99999.1", document["pysmi_global"]["oid"])
        self.assertEqual("1.3.6.1.4.1.99999.1.1", document["testObject"]["oid"])

    def testBothBackEndsAgreeOnTheSymbolSet(self):
        # The property #182 asks for: the trees describe the same modules,
        # and within a module the same symbols.
        for keyword in KEYWORDS:
            with self.subTest(keyword=keyword):
                document = render_json(module(keyword), deps=[SNMPV2_SMI])
                source = render_source(module(keyword), deps=[SNMPV2_SMI])

                self.assertIn(f"pysmi_{keyword}", source)
                self.assertIn(f"pysmi_{keyword}", document)

    def testThePysnmpModuleStillCarriesTheDescriptorAsWritten(self):
        # setLabel is how the generated module keeps the name the MIB uses.
        # The document has no equivalent, for keywords or for hyphens; that
        # is a schema question and is left where it was -- see #225.
        source = render_source(module("global"), deps=[SNMPV2_SMI])

        self.assertIn('setLabel("global")', source)


if __name__ == "__main__":
    unittest.main()
