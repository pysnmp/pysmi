#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# Python 2 compatibility shims removed in 1.2.0.
# These helpers are kept as thin wrappers for backward compatibility
# with any external code that imports from pysmi.compat.
"""Text encoding helpers.

Python 2 support is gone; these remain because external code imports them.
"""


def encode(s):
    """Encode str to bytes using UTF-8."""
    if isinstance(s, str):
        s = s.encode("utf-8", "ignore")
    return s


def decode(s):
    """Decode bytes to str using UTF-8."""
    if isinstance(s, bytes):
        s = s.decode("utf-8", "ignore")
    return s
