#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Borrowing pre-compiled MIB modules of any format."""

from pysmi.borrower.base import AbstractBorrower


class AnyFileBorrower(AbstractBorrower):
    """Create arbitrary MIB file borrowing object"""
