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

import collections.abc
import functools
import operator
import types
import typing
import unittest

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory

MIB = """
TYPES-TEST-MIB DEFINITIONS ::= BEGIN
IMPORTS
    MODULE-IDENTITY, OBJECT-TYPE, OBJECT-IDENTITY, NOTIFICATION-TYPE, Integer32, Unsigned32
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION, DisplayString
        FROM SNMPv2-TC
    OBJECT-GROUP, NOTIFICATION-GROUP, AGENT-CAPABILITIES, MODULE-COMPLIANCE
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

testRanged OBJECT-TYPE
    SYNTAX      Integer32 (0..100 | 200)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A scalar with a range, for the range constraint."
    DEFVAL      { 7 }
    ::= { testMib 7 }

testSized OBJECT-TYPE
    SYNTAX      OCTET STRING (SIZE(0..16 | 32))
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A scalar with a size, for the size constraint."
    DEFVAL      { "abc" }
    ::= { testMib 8 }

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

testCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "A compliance, for the MODULE clause."
    MODULE
        MANDATORY-GROUPS { testGroup }
        GROUP       testGroup
        DESCRIPTION "A group requirement."
    ::= { testMib 9 }

testGroup OBJECT-GROUP
    OBJECTS     { testScalar, testEnum, testBits }
    STATUS      current
    DESCRIPTION "A group, for OBJECTS."
    ::= { testMib 5 }

testIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "An identity, for objectIdentityClause."
    ::= { testMib 10 }

testNotify NOTIFICATION-TYPE
    OBJECTS     { testScalar }
    STATUS      current
    DESCRIPTION "A notification, for notificationTypeClause."
    ::= { testMib 11 }

testNotifyGroup NOTIFICATION-GROUP
    NOTIFICATIONS { testNotify }
    STATUS        current
    DESCRIPTION   "A notification group, for notificationGroupClause."
    ::= { testMib 12 }

testValue OBJECT IDENTIFIER ::= { testMib 13 }

END
"""


#: TRAP-TYPE is SMIv1, so it needs a module of its own rather than a clause
#: added to the SMIv2 one above.
V1_MIB = """
TYPES-TEST-V1-MIB DEFINITIONS ::= BEGIN
IMPORTS
    TRAP-TYPE
        FROM RFC-1215;

-- Numeric, like the OIDs above: each module is compiled against a fresh
-- symbol table, so a name from another module has nothing to resolve against.
testV1 OBJECT IDENTIFIER ::= { 1 3 6 1 4 1 99996 }

testV1Trap TRAP-TYPE
    ENTERPRISE  testV1
    DESCRIPTION "A v1 trap, for trapTypeClause."
    ::= 3

END
"""


# Every annotated handler is now reachable from the MIB below. A handler that
# cannot be reached is either dead, as SymtableCodeGen.gen_time was, or the MIB
# has stopped covering it; either way the test should fail rather than pass over
# it, so this stays empty unless there is a reason on record.
UNREACHABLE: set[tuple[str, str]] = set()


def withoutNone(hint):
    """Drop None from a union, leaving the shape the clause actually carries."""
    if typing.get_origin(hint) in (typing.Union, types.UnionType):
        args = tuple(a for a in typing.get_args(hint) if a is not type(None))
        if len(args) == 1:
            return args[0]
        return functools.reduce(operator.or_, args)
    return hint


def conforms(value, hint):
    """Check *value* against a typing hint built from Sequence, list, tuple and scalars."""
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

    if origin is collections.abc.Sequence:
        # What prep_data hands a handler. A str is a Sequence[str] as far as
        # typing is concerned, but never what a clause carries, so reject it
        # rather than let a bare string satisfy Sequence[str].
        if not isinstance(value, (list, tuple)):
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
        for source in (MIB, V1_MIB):
            ast = parserFactory()().parse(source)[0]
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
                unreached = {n for n in set(hints) - seen if (backend.__name__, n) not in UNREACHABLE}
                self.assertEqual(sorted(unreached), [])

    def testBackendsAgreeOnClauseShape(self):
        # The same clause must not be annotated with a different shape in two
        # backends. Whether a backend also accepts None is a property of how it
        # reaches the handler, not of the clause: pysnmp and JSON call
        # gen_def_val from gen_object_type whether or not a default was given,
        # while the symbol table only ever reaches it by dispatch on DEFVAL.
        byName = {}
        for backend in self.backends:
            for name, hint in annotatedHandlers(backend).items():
                byName.setdefault(name, {})[backend.__name__] = withoutNone(hint)

        for name, hints in byName.items():
            with self.subTest(handler=name):
                self.assertEqual(len(set(hints.values())), 1, hints)

    def testConformsRejectsWrongShapes(self):
        from pysmi.codegen.base import (
            ComplianceClause,
            DefValClause,
            IndexClause,
            NamedNumbersClause,
            OidClause,
            RangesClause,
            RevisionsClause,
            TextClause,
        )

        # An OID arc is a name, a number, or the name(number) form.
        self.assertTrue(conforms([["mib-2", 1, ("org", 3)]], OidClause))
        self.assertFalse(conforms([[1.5]], OidClause))
        self.assertFalse(conforms([[("org", "3")]], OidClause))

        # A default is an int, a bits list, or a string.
        self.assertTrue(conforms([7], DefValClause))
        self.assertTrue(conforms(["enabled"], DefValClause))
        self.assertTrue(conforms([["readable"]], DefValClause))
        self.assertFalse(conforms([{"bits": 1}], DefValClause))

        # A range or size entry is one bound or two, and a bound written as a
        # hex or binary literal stays a string.
        self.assertTrue(conforms([[(0, 100), (200,)]], RangesClause))
        self.assertTrue(conforms([[(1, "'ffffffff'h")]], RangesClause))
        self.assertFalse(conforms([[(0, 1, 2)]], RangesClause))
        self.assertFalse(conforms([[[0, 1]]], RangesClause))

        self.assertTrue(conforms([[("202601010000Z", ("DESCRIPTION", "text"))]], RevisionsClause))
        self.assertFalse(conforms([[("202601010000Z", "text")]], RevisionsClause))

        # The module name is absent when the clause means the current module.
        # The third element carries the sub-clause detail the name list drops.
        group = ("ComplianceGroup", "aGroup", "applies when...")
        self.assertTrue(conforms([[(None, ["aGroup"], (["aGroup"], []))]], ComplianceClause))
        self.assertTrue(conforms([[("SNMPv2-MIB", ["aGroup"], ([], [group]))]], ComplianceClause))
        self.assertFalse(conforms([[(None, "aGroup", ([], []))]], ComplianceClause))
        self.assertFalse(conforms([[(None, ["aGroup"])]], ComplianceClause))

        self.assertTrue(conforms(["a text"], TextClause))
        self.assertFalse(conforms("a text", TextClause))
        self.assertFalse(conforms([1], TextClause))
        self.assertTrue(conforms([[("up", 1)]], NamedNumbersClause))
        self.assertFalse(conforms([[("up", "1")]], NamedNumbersClause))
        self.assertTrue(conforms([[(0, "testIndex")]], IndexClause))
        self.assertFalse(conforms([[("testIndex", 0)]], IndexClause))

        # prep_data hands a handler a tuple, so the clause aliases have to
        # accept one -- a list stays acceptable for anyone calling a handler
        # directly. See https://github.com/pysnmp/pysmi/issues/47.
        self.assertTrue(conforms(("a text",), TextClause))
        self.assertTrue(conforms((7,), DefValClause))
        self.assertTrue(conforms(([["mib-2", 1]]), OidClause))
        self.assertTrue(conforms(([[(0, "testIndex")]]), IndexClause))
        # A bare string is a Sequence[str] to typing, but never a clause.
        self.assertFalse(conforms("a text", TextClause))


suite = unittest.TestLoader().loadTestsFromModule(__import__(__name__))

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
