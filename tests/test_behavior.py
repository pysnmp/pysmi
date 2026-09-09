#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Hand-written runtime behavior reaches the module it belongs to.

``pysmi/mibs/behavior/`` holds the Python for the few runtime relations SMIv2
has no syntax to state -- RFC 4001 section 4 puts the ``InetAddress`` index
encoding rule in a DESCRIPTION clause -- and the code generator appends the
fragment to the module it names. What that behavior *does* is a question for
pysnmp, and is asked in the consumer layer -- the one file allowed to import
it. What is asked here is that the mechanism carries the fragment at all,
which is answerable from the emitted source alone.

See pysnmp/pysmi#231.
"""

import pathlib
import sys
import unittest

from pysmi.mibs import behavior, bundled
from tests.harness import render_source

BEHAVIOR = pathlib.Path(__file__).parent.parent / "pysmi" / "mibs" / "behavior"

#: A module with a fragment, and one without, rendered from the same shape so
#: that the only difference between the two outputs is the mechanism.
TEMPLATE = """
%s DEFINITIONS ::= BEGIN

testOid OBJECT IDENTIFIER ::= { 1 3 }

END
"""

WITH_BEHAVIOR = "INET-ADDRESS-MIB"
WITHOUT_BEHAVIOR = "TEST-MIB"


class BehaviorDirectoryTestCase(unittest.TestCase):
    """What the directory holds, before anything is rendered with it."""

    def setUp(self):
        self.fragments = sorted(path.stem for path in BEHAVIOR.glob("*.py"))

    def testTheDirectoryIsNotEmpty(self):
        """A directory that emptied would pass every other check here."""
        self.assertIn(WITH_BEHAVIOR, self.fragments)

    def testEveryFragmentNamesAModulePysmiBundles(self):
        """A fragment for a module we do not carry can never be appended."""
        self.assertEqual([], sorted(set(self.fragments) - bundled()))

    def testEveryFragmentIsValidPython(self):
        """It is appended verbatim, so a syntax error here breaks the module."""
        for name in self.fragments:
            with self.subTest(module=name):
                compile(behavior(name), f"{name}.py", "exec")

    def testEveryFragmentIsReadable(self):
        for name in self.fragments:
            with self.subTest(module=name):
                self.assertTrue(behavior(name))

    def testAModuleWithNoFragmentAnswersEmpty(self):
        self.assertEqual("", behavior(WITHOUT_BEHAVIOR))

    def testANameThatIsAPathAnswersEmpty(self):
        """The key is a module name off a parse tree, never joined onto a path."""
        for name in ("../asn1/IF-MIB", "/etc/passwd", "__init__"):
            with self.subTest(name=name):
                self.assertEqual("", behavior(name))


class AppendedOutputTestCase(unittest.TestCase):
    """Where the fragment lands in what the pysnmp backend renders."""

    def setUp(self):
        self.withBehavior = render_source(TEMPLATE % WITH_BEHAVIOR)
        self.withoutBehavior = render_source(TEMPLATE % WITHOUT_BEHAVIOR)

    def testTheFragmentIsAppendedVerbatim(self):
        self.assertIn(behavior(WITH_BEHAVIOR), self.withBehavior)

    def testTheFragmentFollowsTheExports(self):
        """It runs in the module's namespace, so every symbol must exist first."""
        self.assertLess(
            self.withBehavior.index("mibBuilder.exportSymbols"),
            self.withBehavior.index(behavior(WITH_BEHAVIOR)),
        )

    def testTheAppendedSourceSaysWhereItCameFrom(self):
        """Whoever reads the generated module needs the file to edit."""
        self.assertIn(f"pysmi/mibs/behavior/{WITH_BEHAVIOR}.py", self.withBehavior)

    def testAModuleWithNoFragmentIsUntouched(self):
        self.assertNotIn("pysmi/mibs/behavior/", self.withoutBehavior)


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
