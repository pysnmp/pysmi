#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Passing transformed modules to a user-supplied callable."""

import logging
from collections.abc import Callable
from typing import Any

from pysmi import error
from pysmi.writer.base import AbstractWriter

logger = logging.getLogger(__name__)


class CallbackWriter(AbstractWriter):
    """Invokes user-specified callable and passes transformed
    MIB module to it.

    Note: user callable object signature must be as follows

    .. function:: cbFun(mibname, contents, cbCtx)

    """

    def __init__(self, cbFun: Callable[[str, str, Any], Any], cbCtx: Any = None) -> None:
        """Creates an instance of *CallbackWriter* class.

        Args:
            cbFun (callable): user-supplied callable
        Keyword Args:
            cbCtx: user-supplied object passed intact to user callback
        """
        self._cbFun = cbFun
        self._cbCtx = cbCtx

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._cbFun}"}}'

    def putData(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
        if dryRun:
            logger.debug("dry run mode", extra={"mib": mibname})
            return

        try:
            self._cbFun(mibname, data, self._cbCtx)

        # The callback is arbitrary user code, so anything it raises is turned
        # into a writer error rather than escaping as itself.
        except Exception as exc:
            raise error.PySmiWriterError(
                f"user callback {self._cbFun} failure writing {mibname}: {exc}", writer=self
            ) from exc

        logger.debug("user callback for %s succeeded", mibname, extra={"mib": mibname})

    def getData(self, filename: str) -> str:
        return ""
