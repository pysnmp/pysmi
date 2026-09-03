#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Run the whole test suite with ``python -m tests``.

Modules are discovered rather than listed, so a new one is picked up by
being named ``test_*.py``. CI runs the same tests through pytest.
"""

import os
import sys
import unittest

suite = unittest.TestLoader().discover(
    start_dir=os.path.dirname(__file__),
    pattern="test_*.py",
    top_level_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
