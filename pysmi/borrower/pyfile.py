#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Borrowing pre-compiled PySNMP MIB modules."""

import importlib.machinery
from typing import Final

from pysmi.borrower.base import AbstractBorrower

SOURCE_SUFFIXES: Final = importlib.machinery.SOURCE_SUFFIXES


class PyFileBorrower(AbstractBorrower):
    """Create PySNMP MIB file borrowing object"""

    exts = SOURCE_SUFFIXES
