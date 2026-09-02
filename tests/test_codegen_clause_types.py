#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The clause type aliases must keep describing what the parser really produces.

The aliases in pysmi.codegen.base were written from shapes observed across a MIB
corpus. Nothing in the grammar is pinned to them, so a change to a production
could leave a handler annotated with a shape it no longer receives. mypy cannot
catch that: it checks the handler against its annotation, not the annotation
against the parser.

These tests compile a MIB that exercises the annotated clauses and check every
value actually handed to a handler against the alias that handler declares.
"""

import types
import typing
import unittest

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory

MIB = """
TYPES-TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, Integer32, Unsigned32
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION, DisplayString
        FROM SNMPv2-TC
    OBJECT-GROUP, AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

testMib MODULE-IDENTITY
    LAST-UPDATED "202601010000Z"
    ORGANIZATION "PySMI test suite"
    CONTACT-INFO "nobody@example.com"
    DESCRIPTION  "Exercises the annotated clauses."
    REVISION     "202601010000Z"
    DESCRIPTION  "First revision."
    ::= { 1 3 6 1 2 1 9999 }

TestHint ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "A textual convention carrying a display hint."
    SYNTAX       OCTET STRING

testScalar OBJECT-TYPE
    SYNTAX      Integer32
    UNITS       "seconds"
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A scalar with units."
    REFERENCE   "RFC 9999"
    ::= { testMib 1 }

testEnum OBJECT-TYPE
    SYNTAX      INTEGER { up(1), down(2), testing(3) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A scalar with an enumeration."
    ::= { testMib 2 }

testBits OBJECT-TYPE
    SYNTAX      BITS { readable(0), writable(1) }
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A scalar carrying BITS."
    DEFVAL      { { readable } }
    ::= { testMib 3 }

testTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A table, for INDEX and SEQUENCE."
    ::= { testMib 4 }

testEntry OBJECT-TYPE
    SYNTAX      TestEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A row."
    INDEX       { testIndex }
    ::= { testTable 1 }

TestEntry ::= SEQUENCE {
    testIndex  Unsigned32,
    testLabel  DisplayString
}

testIndex OBJECT-TYPE
    SYNTAX      Unsigned32
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The index column."
    ::= { testEntry 1 }

testLabel OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A column."
    ::= { testEntry 2 }

testCaps AGENT-CAPABILITIES
    PRODUCT-RELEASE "PySMI test agent 1.0"
    STATUS          current
    DESCRIPTION     "Exercises PRODUCT-RELEASE and variation BITS."
    SUPPORTS        TYPES-TEST-MIB
        INCLUDES    { testGroup }
        VARIATION   testBits
            SYNTAX      BITS { readable(0) }
            ACCESS      read-only
            CREATION-REQUIRES { testLabel }
            DESCRIPTION "A variation."
    ::= { 1 3 6 1 2 1 9999 6 }

testGroup OBJECT-GROUP
    OBJECTS     { testScalar, testEnum, testBits }
    STATUS      current
    DESCRIPTION "A group, for OBJECTS."
    ::= { testMib 5 }

END
"""


def conforms(value, hint):
    """Check *value* against a typing hint built from list, tuple and scalars."""
    origin = typing.get_origin(hint)

    if origin is None:
        if hint is typing.Any:
            return True
        # bool is an int subclass; the aliases never mean bool where they say int
        if hint is int and isinstance(value, bool):
            return False
        return isinstance(value, hint)

    if origin is list:
        if not isinstance(value, list):
            return False
        (item,) = typing.get_args(hint)
        return all(conforms(v, item) for v in value)

    if origin is tuple:
        if not isinstance(value, tuple):
            return False
        args = typing.get_args(hint)
        if len(args) == 2 and args[1] is Ellipsis:
            return all(conforms(v, args[0]) for v in value)
        return len(value) == len(args) and all(conforms(v, a) for v, a in zip(value, args, strict=True))

    if origin in (typing.Union, types.UnionType):
        return any(conforms(value, a) for a in typing.get_args(hint))

    raise AssertionError(f"unhandled hint {hint!r}")


def annotatedHandlers(cls):
    """Map handler name to its declared `data` type, for handlers not left Any."""
    out = {}
    for name in dir(cls):
        if not name.startswith("gen_"):
            continue
        fn = getattr(cls, name)
        fn = getattr(fn, "__func__", fn)
        if not callable(fn):
            continue
        try:
            hints = typing.get_type_hints(fn)
        except (NameError, TypeError):
            # an annotation that cannot be resolved is simply not checked
            continue
        hint = hints.get("data")
        if hint is not None and hint is not typing.Any:
            out[name] = hint
    return out


def compileWatching(backend, seen, violations):
    """Render MIB with every annotated handler on *backend* checked at runtime."""
    hints = annotatedHandlers(backend)
    original = {}

    def watch(name, hint, fn):
        def inner(self, data, *args, **kwargs):
            seen.add(name)
            if not conforms(data, hint):
                violations.append((backend.__name__, name, hint, repr(data)[:200]))
            return fn(self, data, *args, **kwargs)

        return inner

    for name, hint in hints.items():
        fn = getattr(backend, name)
        fn = getattr(fn, "__func__", fn)
        original[name] = getattr(backend, name)
        setattr(backend, name, watch(name, hint, fn))

    # handlersTable holds the functions themselves, so it must be rebuilt to
    # route through the wrappers
    originalTable = backend.handlersTable
    backend.handlersTable = {tag: getattr(backend, fn.__name__) for tag, fn in originalTable.items()}

    try:
        ast = parserFactory()().parse(MIB)[0]
        mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=True)
        if backend is not SymtableCodeGen:
            backend().gen_code(ast, {mibInfo.name: symtable}, genTexts=True)
    finally:
        backend.handlersTable = originalTable
        for name, fn in original.items():
            setattr(backend, name, fn)

    return hints


class ClauseTypeTestCase(unittest.TestCase):
    """Every annotated handler receives what its annotation claims."""

    backends = (PySnmpCodeGen, JsonCodeGen, SymtableCodeGen)

    def testAnnotatedHandlersReceiveTheDeclaredShape(self):
        for backend in self.backends:
            with self.subTest(backend=backend.__name__):
                seen, violations = set(), []
                hints = compileWatching(backend, seen, violations)
                self.assertTrue(hints, f"{backend.__name__} has no annotated handlers")
                self.assertEqual(violations, [])

    def testTheMibExercisesEveryAnnotatedHandler(self):
        # A conformance test that never runs the handlers proves nothing. This
        # MIB is built to reach all of them, so a newly annotated handler that
        # it does not reach fails here rather than passing unchecked.
        for backend in self.backends:
            with self.subTest(backend=backend.__name__):
                seen, violations = set(), []
                hints = compileWatching(backend, seen, violations)
                self.assertEqual(sorted(set(hints) - seen), [])

    def testBackendsAgreeOnClauseShape(self):
        # The same clause must not be annotated differently in two backends.
        byName = {}
        for backend in self.backends:
            for name, hint in annotatedHandlers(backend).items():
                byName.setdefault(name, {})[backend.__name__] = hint

        for name, hints in byName.items():
            with self.subTest(handler=name):
                self.assertEqual(len(set(hints.values())), 1, hints)

    def testConformsRejectsWrongShapes(self):
        from pysmi.codegen.base import IndexClause, NamedNumbersClause, TextClause

        self.assertTrue(conforms(["a text"], TextClause))
        self.assertFalse(conforms("a text", TextClause))
        self.assertFalse(conforms([1], TextClause))
        self.assertTrue(conforms([[("up", 1)]], NamedNumbersClause))
        self.assertFalse(conforms([[("up", "1")]], NamedNumbersClause))
        self.assertTrue(conforms([[(0, "testIndex")]], IndexClause))
        self.assertFalse(conforms([[("testIndex", 0)]], IndexClause))


suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
