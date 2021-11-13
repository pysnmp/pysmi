#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
from pysmi.parser.dialect import smiV1
from pysmi.parser.smi import parserFactory

# compatibility stub
SmiV1Parser = parserFactory(**smiV1)
