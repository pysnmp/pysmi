#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""A code generator that renders nothing."""

import logging
from typing import Any

from pysmi._aliases import deprecated_camel_case
from pysmi.codegen.base import AbstractCodeGen
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)


@deprecated_camel_case
class NullCodeGen(AbstractCodeGen):
    """Dummy code generation backend.

    Could be used for disabling code generation at *MibCompiler*.
    """

    def gen_code(self, ast: Any, symbolTable: dict[str, Any], **kwargs: Any) -> tuple[MibInfo, str]:
        """Discard the module and return an empty result."""
        logger.debug("%s invoked", self.__class__.__name__, extra={"codegen": self.__class__.__name__})
        return MibInfo(oid=None, name="", imported=[]), ""

    def gen_index(self, processed: dict[str, Any], **kwargs: Any) -> str:
        """Return an empty index."""
        return ""
