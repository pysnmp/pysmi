#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Parser for SMIv2 modules."""

from pysmi.parser.dialect import smiV2
from pysmi.parser.smi import parserFactory

# compatibility stub
SmiV2Parser = parserFactory(**smiV2)
