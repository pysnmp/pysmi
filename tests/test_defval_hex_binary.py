#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""A hexadecimal or binary DEFVAL means different things to different types.

For an OCTET STRING the digits are the octets themselves. For an integer they
spell a number, which several MIBs write this way. The code generators resolve
this against the object's base type, so what they emit has to say which of the
two it is.
"""

import json
import textwrap
import unittest

from pysmi.codegen.jsondoc import JsonCodeGen
from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory

MIB = textwrap.dedent(
    """\
    HEX-DEFVAL-MIB DEFINITIONS ::= BEGIN
    IMPORTS
      OBJECT-TYPE
        FROM SNMPv2-SMI;

    hexInt OBJECT-TYPE
        SYNTAX      Integer32
        MAX-ACCESS  read-only
        STATUS      current
        DESCRIPTION "hex default on an integer"
        DEFVAL      { '0A'H }
     ::= { 1 1 }

    binInt OBJECT-TYPE
        SYNTAX      Integer32
        MAX-ACCESS  read-only
        STATUS      current
        DESCRIPTION "binary default on an integer"
        DEFVAL      { '1010'B }
     ::= { 1 2 }

    hexOctets OBJECT-TYPE
        SYNTAX      OCTET STRING
        MAX-ACCESS  read-only
        STATUS      current
        DESCRIPTION "hex default on an octet string"
        DEFVAL      { '0A0B'H }
     ::= { 1 3 }

    binOctets OBJECT-TYPE
        SYNTAX      OCTET STRING
        MAX-ACCESS  read-only
        STATUS      current
        DESCRIPTION "binary default on an octet string"
        DEFVAL      { '1010'B }
     ::= { 1 4 }

    END
    """
)


def generate(codegen):
    """Run *codegen* over the MIB above and return what it emitted."""
    ast = parserFactory()().parse(MIB)[0]
    mibInfo, symtable = SymtableCodeGen().gen_code(ast, {})
    _, out = codegen().gen_code(ast, {mibInfo.name: symtable})
    return out


class JsonHexDefValTestCase(unittest.TestCase):
    """The JSON document has to label the value it actually carries."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(generate(JsonCodeGen))

    def default(self, name):
        """Return the default clause the JSON document holds for *name*."""
        return self.doc[name]["default"]

    def testHexOnIntegerIsReportedAsDecimal(self):
        """0x0A on an Integer32 is the number ten, and says so."""
        self.assertEqual({"value": 10, "format": "decimal"}, self.default("hexInt"))

    def testBinaryOnIntegerIsReportedAsDecimal(self):
        """0b1010 on an Integer32 is the number ten, and says so."""
        self.assertEqual({"value": 10, "format": "decimal"}, self.default("binInt"))

    def testHexOnOctetStringKeepsItsDigits(self):
        """The digits are the octets here, so they survive unconverted."""
        self.assertEqual({"value": "0A0B", "format": "hex"}, self.default("hexOctets"))

    def testBinaryOnOctetStringBecomesHexDigits(self):
        """Binary octets are rewritten as hex, which is what the format says."""
        self.assertEqual({"value": "a", "format": "hex"}, self.default("binOctets"))

    def testEveryValueParsesBackAsItsStatedFormat(self):
        """Reading each value the way its own format directs returns the value.

        This is the property the bug broke: a converted integer was still
        labelled hex, so a reader decoding it arrived at a different number.
        """
        for name, expected in (("hexInt", 10), ("binInt", 10)):
            with self.subTest(name):
                clause = self.default(name)
                self.assertEqual("decimal", clause["format"])
                self.assertEqual(expected, int(clause["value"]))

        for name, expected in (("hexOctets", b"\x0a\x0b"), ("binOctets", b"\x0a")):
            with self.subTest(name):
                clause = self.default(name)
                self.assertEqual("hex", clause["format"])
                self.assertEqual(expected, bytes.fromhex(clause["value"].rjust(2, "0")))


class PySnmpHexDefValTestCase(unittest.TestCase):
    """The pysnmp backend already resolved these; pin it so it stays that way."""

    @classmethod
    def setUpClass(cls):
        cls.source = generate(PySnmpCodeGen)

    def line(self, name):
        """Return the generated line defining *name*."""
        for line in self.source.splitlines():
            if line.strip().startswith(f"{name} = "):
                return line
        raise AssertionError(f"{name} is not in the generated module")

    def testHexOnIntegerBecomesANumber(self):
        """An integer default is cloned from a number, not from hexValue."""
        self.assertIn("clone(10)", self.line("hexInt"))
        self.assertNotIn("hexValue", self.line("hexInt"))

    def testBinaryOnIntegerBecomesANumber(self):
        """Same for a binary literal standing in for a number."""
        self.assertIn("clone(10)", self.line("binInt"))
        self.assertNotIn("hexValue", self.line("binInt"))

    def testHexOnOctetStringStaysHexValue(self):
        """An octet string keeps hexValue, which is how pysnmp spells octets."""
        self.assertIn('clone(hexValue="0A0B")', self.line("hexOctets"))


class SymtableDefValTestCase(unittest.TestCase):
    """The symbol table records the default without interpreting it.

    It is the pass that discovers base types, so it has none to consult, and a
    hexadecimal literal is ambiguous without one.
    """

    def testDefaultIsRecordedAsWritten(self):
        """The literal is stored verbatim, not rendered as pysnmp source."""
        gen = SymtableCodeGen()
        for written in ("'0A'H", "'1010'B", '"text"', 42):
            with self.subTest(written):
                self.assertEqual(written, gen.gen_def_val([written]))


if __name__ == "__main__":
    unittest.main()
