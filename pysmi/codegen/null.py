#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""A code generator that renders nothing."""

import logging

from pysmi.codegen.base import AbstractCodeGen
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)


class NullCodeGen(AbstractCodeGen):
    """Dummy code generation backend.

    Could be used for disabling code generation at *MibCompiler*.
    """

    def genCode(self, ast, symbolTable, **kwargs):
        logger.debug("%s invoked", self.__class__.__name__, extra={"codegen": self.__class__.__name__})
        return MibInfo(oid=None, name="", imported=[]), ""

    def genIndex(self, processed, **kwargs):
        return ""
