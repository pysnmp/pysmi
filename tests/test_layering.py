#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Only the consumer layer may reach pysnmp.

pysmi's tests decide correctness by reading pysmi's own output against the SMI
specifications. A test that reads the output back off a pysnmp object cannot do
that: pysnmp normalises, tolerates and discards, so what it hands back is its
reading of the module rather than the module. Where pysmi and pysnmp share a
wrong assumption, such a test passes over the defect -- which is how a
not-accessible column came to be emitted as read-only for years, and why
pysnmp/pysmi#128 was found by an assertion on the emitted source instead.

This file is the mechanical gate for pysnmp/pysmi#127. It is deliberately
structural rather than a search for accessor names: a test cannot assert
through pysnmp without acquiring an import path to it, so the import graph is
what gets checked. Grepping for ``getMaxAccess`` would both miss a new accessor
and trip over one named inside a string.
"""

import ast
import pathlib
import sys
import unittest

TESTS = pathlib.Path(__file__).parent

#: ``harness`` reaches pysnmp inside ``render_pysnmp`` alone, which is what
#: keeps the import out of every module that only wants the other renderers.
#: ``test_pysnmp_consumer`` is the consumer layer. Nothing else may.
ALLOWED = frozenset({"harness.py", "test_pysnmp_consumer.py"})

#: Reaching pysnmp through the harness rather than importing it directly is the
#: same thing by another route, so the gate has to name it too.
PYSNMP_HARNESS_ENTRY_POINTS = frozenset({"render_pysnmp", "render"})


def modules():
    """Every Python file under tests/, parsed."""
    for path in sorted(TESTS.glob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def pysnmp_references(tree):
    """Names in *tree* that reach pysnmp, whether directly or via the harness."""
    found = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names if alias.name.split(".")[0] == "pysnmp")

        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] == "pysnmp":
                found.add(node.module)
            elif node.module in ("tests.harness", "harness"):
                found.update(alias.name for alias in node.names if alias.name in PYSNMP_HARNESS_ENTRY_POINTS)

    return found


class ImportGraphTestCase(unittest.TestCase):
    """No test module outside the consumer layer may import pysnmp."""

    def testOnlyTheConsumerLayerReachesPysnmp(self):
        for path, tree in modules():
            if path.name in ALLOWED:
                continue
            with self.subTest(module=path.name):
                self.assertEqual(
                    pysnmp_references(tree),
                    set(),
                    f"{path.name} reaches pysnmp; assert on pysmi's output instead, "
                    f"or move the assertion into tests/test_pysnmp_consumer.py",
                )

    def testTheHarnessKeepsItsPysnmpImportInsideTheFunctionThatNeedsIt(self):
        # A module-scope import would put pysnmp back on the import path of
        # every test that only wants render_json or render_source.
        tree = ast.parse((TESTS / "harness.py").read_text())
        top_level = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
        self.assertTrue(top_level, "harness.py imports nothing at all")
        for node in top_level:
            with self.subTest(statement=ast.unparse(node)):
                self.assertNotIn("pysnmp", ast.unparse(node))

    def testTheHarnessStillOffersThePysnmpRenderer(self):
        # The gate above passes vacuously if the entry point is renamed, which
        # would leave the consumer layer testing nothing.
        from tests import harness

        for name in PYSNMP_HARNESS_ENTRY_POINTS:
            with self.subTest(entry_point=name):
                self.assertTrue(callable(getattr(harness, name, None)))


class ConsumerLayerTestCase(unittest.TestCase):
    """The consumer layer stays one file, and stays non-gating."""

    def testItIsMarkedSoItCanBeDeselected(self):
        source = (TESTS / "test_pysnmp_consumer.py").read_text()
        self.assertIn("pytestmark = pytest.mark.pysnmp_consumer", source)

    def testTheMarkerIsRegistered(self):
        # An unregistered marker is silently a no-op under --strict-markers and
        # a warning otherwise, either of which would leave CI gating on it.
        pyproject = (TESTS.parent / "pyproject.toml").read_text()
        self.assertIn('markers = ["pysnmp_consumer', pyproject)

    def testNoOtherModuleClaimsTheMarker(self):
        for path, _ in modules():
            if path.name in ("test_pysnmp_consumer.py", pathlib.Path(__file__).name):
                continue
            with self.subTest(module=path.name):
                self.assertNotIn("pysnmp_consumer", path.read_text())


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
