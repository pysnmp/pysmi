#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Parser for SMIv1 modules."""

from pysmi.parser.dialect import smiV1
from pysmi.parser.smi import parserFactory

# compatibility stub
SmiV1Parser = parserFactory(**smiV1)
