#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tests for looking up compiled MIBs inside a Python package."""

import os
import shutil
import sys
import tempfile
import unittest

from pysmi import error
from pysmi.searcher.pypackage import PyPackageSearcher


class PyPackageSearcherTestCase(unittest.TestCase):
    def testNamespacePackage(self):
        """A namespace package is reported as not found, not as a TypeError.

        A namespace package has a ``__file__`` attribute whose value is None,
        so testing for the attribute is not enough to know there is a path.
        """
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)

        # No __init__.py, which is what makes it a namespace package.
        os.mkdir(os.path.join(tmpdir, "pysmi_test_ns"))

        sys.path.insert(0, tmpdir)
        self.addCleanup(sys.path.remove, tmpdir)
        self.addCleanup(sys.modules.pop, "pysmi_test_ns", None)

        self.assertRaises(
            error.PySmiFileNotFoundError,
            PyPackageSearcher("pysmi_test_ns").fileExists,
            "IF-MIB",
            0,
        )

    def testMissingPackage(self):
        """A package that cannot be imported is reported as not found."""
        self.assertRaises(
            error.PySmiFileNotFoundError,
            PyPackageSearcher("pysmi_no_such_package").fileExists,
            "IF-MIB",
            0,
        )


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
