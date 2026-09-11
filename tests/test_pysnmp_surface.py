#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""What pysmi emits against pysnmp is declared, and the declaration is true.

:py:mod:`pysmi.codegen.pysnmp_surface` states which parts of pysnmp's loader
contract the generator calls. Stating it is only worth anything if the
statement is held to the generator, so this reads every call back out of the
emitted source and asserts the two match exactly.

The assertion runs both ways on purpose. A call the generator gained without an
entry is undeclared, which is what let ``setFixedLength`` be emitted for years
with no test naming it. An entry nothing emits any more is a stale declaration,
which would have the consumer smoke test checking pysnmp for a member pysmi no
longer needs, and would let the corpus quietly stop reaching a call.

Nothing here imports pysnmp: these are assertions on pysmi's own output and
they gate. Whether the members exist upstream is the consumer layer's question.
See pysnmp/pysmi#127.
"""

import ast
import collections
import sys
import unittest

from pysmi.codegen.pysnmp import PySnmpCodeGen
from pysmi.codegen.pysnmp_surface import (
    BUILDER_MEMBERS,
    NODE_METHODS,
    VALUE_METHODS,
    method_names,
)
from tests.harness import render_source
from tests.surface_corpus import CORPUS

#: The pseudo-modules and base modules pysnmp implements in Python rather than
#: compiling from ASN.1. A symbol bound from one of these is pysnmp's; anything
#: else a module imports came from another MIB and is not part of this surface.
PYSNMP_BASE_MODULES = frozenset(
    {
        "ASN1",
        "ASN1-ENUMERATION",
        "ASN1-REFINEMENT",
        "SNMPv2-SMI",
        "SNMPv2-TC",
        "SNMPv2-CONF",
    }
)

#: Macros that name a type rather than a node. What the generator emits for
#: these is a syntax, so they take the value calls -- ``subtype`` to constrain
#: and ``clone`` to default -- and none of the node calls.
TYPE_MACROS = frozenset({"BITS", "TEXTUAL-CONVENTION"})

#: Every class the generator emits a MIB node as.
NODE_CLASSES = frozenset(
    name
    for macro, names in PySnmpCodeGen.symsTable.items()
    if macro not in TYPE_MACROS
    for name in names
)


def _import_module(call):
    """The base module *call* binds symbols from, or None."""
    if (
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and call.func.attr == "importSymbols"
        and call.args
        and isinstance(call.args[0], ast.Constant)
        and call.args[0].value in PYSNMP_BASE_MODULES
    ):
        return call.args[0].value
    return None


def _constructor(node):
    """The class *node* is built by, unwinding any chain of setters."""
    while isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        node = node.func.value
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        return node.func.id
    return None


class EmittedSurface:
    """The calls one generated module makes, read off its source."""

    def __init__(self, source):
        self.tree = ast.parse(source)
        self.builder = set()
        self.node_methods = collections.defaultdict(set)
        self.value_methods = set()
        self._read()

    def _base_symbols(self):
        """Names bound from a pysnmp base module."""
        bound = {}
        for node in ast.walk(self.tree):
            module = _import_module(node)
            if module:
                bound.update(
                    (arg.value, module)
                    for arg in node.args[1:]
                    if isinstance(arg, ast.Constant)
                )
        return bound

    def _symbol_classes(self, bound):
        """Module-level names, mapped to the base class each was built from."""
        classes = {}
        for node in ast.walk(self.tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                built = _constructor(node.value)
                if isinstance(target, ast.Name) and built in bound:
                    classes[target.id] = built
            elif isinstance(node, ast.ClassDef):
                for base in node.bases:
                    if isinstance(base, ast.Name) and base.id in bound:
                        classes[node.name] = base.id
        return classes

    def _receiver(self, node, classes):
        """The class a call is made on, whether chained or through a name."""
        chained = _constructor(node)
        if chained:
            return chained
        while isinstance(node, ast.Attribute):
            node = node.value
        if isinstance(node, ast.Name):
            return classes.get(node.id, node.id)
        return None

    def _read(self):
        bound = self._base_symbols()
        classes = self._symbol_classes(bound)

        for node in ast.walk(self.tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                receiver = self._receiver(node.func.value, classes)
                if receiver == "mibBuilder":
                    self.builder.add(node.func.attr)
                elif receiver in NODE_CLASSES:
                    self.node_methods[node.func.attr].add(receiver)
                elif receiver in bound or receiver in classes:
                    self.value_methods.add(node.func.attr)

            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                if node.value.id == "mibBuilder":
                    self.builder.add(node.attr)


def surface_of_corpus():
    """Every call the whole corpus emits, merged."""
    builder = set()
    node_methods = collections.defaultdict(set)
    value_methods = set()

    for source in CORPUS.values():
        emitted = EmittedSurface(render_source(source))
        builder |= emitted.builder
        value_methods |= emitted.value_methods
        for name, receivers in emitted.node_methods.items():
            node_methods[name] |= receivers

    return builder, node_methods, value_methods


class DeclaredSurfaceTestCase(unittest.TestCase):
    """The declaration and the generator say the same thing."""

    @classmethod
    def setUpClass(cls):
        cls.builder, cls.node_methods, cls.value_methods = surface_of_corpus()

    def testTheBuilderMembersAreTheOnesDeclared(self):
        self.assertEqual(self.builder, set(BUILDER_MEMBERS))

    def testTheNodeMethodsAreTheOnesDeclared(self):
        self.assertEqual(set(self.node_methods), set(NODE_METHODS))

    def testEachNodeMethodIsEmittedOnTheClassesDeclared(self):
        for name, receivers in sorted(NODE_METHODS.items()):
            with self.subTest(method=name):
                self.assertEqual(self.node_methods[name], set(receivers))

    def testTheValueMethodsAreTheOnesDeclared(self):
        self.assertEqual(self.value_methods, set(VALUE_METHODS))

    def testNoMethodIsDeclaredTwice(self):
        # A name in both mappings would be checked against a receiver it is not
        # always called on, so the split has to stay a partition.
        self.assertEqual(set(NODE_METHODS) & set(VALUE_METHODS), set())
        self.assertEqual(len(method_names()), len(NODE_METHODS) + len(VALUE_METHODS))


class ReceiverTestCase(unittest.TestCase):
    """The declared receivers are classes the generator actually emits."""

    def testEveryReceiverIsAClassTheGeneratorEmits(self):
        for name, receivers in sorted(NODE_METHODS.items()):
            for receiver in receivers:
                with self.subTest(method=name, receiver=receiver):
                    self.assertIn(receiver, NODE_CLASSES)

    def testEveryNodeClassTakesAtLeastOneCall(self):
        # A class nothing is called on is either unreachable or a gap in the
        # corpus; either way the declaration below it is untested.
        called = {r for receivers in NODE_METHODS.values() for r in receivers}
        self.assertEqual(called, set(NODE_CLASSES))


class CorpusTestCase(unittest.TestCase):
    """The corpus is what makes the assertions above non-vacuous."""

    def testEveryModuleRenders(self):
        for name, source in sorted(CORPUS.items()):
            with self.subTest(module=name):
                self.assertIn("mibBuilder.exportSymbols", render_source(source))

    def testTheGuardedSettersSurviveOnlyWithTexts(self):
        # Rendering without texts drops the narrative setters, so a corpus
        # rendered that way would under-report the surface. Asserted here so
        # that the day the surface test renders both ways it is a deliberate
        # change rather than a silent one.
        bare = render_source(CORPUS["SURFACE-MIB"], genTexts=False)
        self.assertNotIn(".setDescription(", bare)
        self.assertIn(".setStatus(", bare)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
