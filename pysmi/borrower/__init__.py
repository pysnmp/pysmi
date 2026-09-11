#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Sources of pre-compiled MIB modules."""

from pysmi.borrower.anyfile import AnyFileBorrower
from pysmi.borrower.pyfile import PyFileBorrower

__all__ = [
    "AnyFileBorrower",
    "PyFileBorrower",
]
