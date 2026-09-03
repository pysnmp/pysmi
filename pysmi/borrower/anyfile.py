#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Borrowing pre-compiled MIB modules of any format."""

from pysmi.borrower.base import AbstractBorrower


class AnyFileBorrower(AbstractBorrower):
    """Create arbitrary MIB file borrowing object"""
