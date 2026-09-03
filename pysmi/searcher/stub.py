#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Treating a fixed list of MIB modules as always up to date."""

import logging

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.searcher.base import AbstractSearcher

logger = logging.getLogger(__name__)


@deprecated_camel_case
class StubSearcher(AbstractSearcher):
    """Figures out if given MIB module is present in a fixed list of modules."""

    def __init__(self, *mibnames: str) -> None:
        """Create an instance of *StubSearcher* initialized with a fixed list
        or MIB modules names.

        Args:
            mibnames (str): blacklisted MIB names
        """
        self._mibnames = mibnames

    def __str__(self) -> str:
        """Identify this searcher by class alone; it holds no location."""
        return f"{self.__class__.__name__}"

    def file_exists(self, mibname: str, mtime: float, rebuild: bool = False, digest: str | None = None) -> None:
        """Report the configured modules as permanently up to date.

        These MIBs are supplied by the target implementation, so they must
        never be compiled regardless of ``rebuild``.
        """
        if mibname in self._mibnames:
            logger.debug("pretend compiled %s exists and is very new", mibname, extra={"mib": mibname})
            raise error.PySmiFileNotModifiedError(
                f"compiled file {mibname} is among {', '.join(self._mibnames)}", searcher=self
            )

        raise error.PySmiFileNotFoundError(
            f"no compiled file {mibname} found among {', '.join(self._mibnames)}", searcher=self
        )
