#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the borrowers."""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pysmi.mibinfo import MibInfo
    from pysmi.reader.base import AbstractReader

from pysmi import error

logger = logging.getLogger(__name__)


class AbstractBorrower:
    """Base class for borrowers of pre-compiled MIBs.

    A borrower is the compiler's fallback: when a MIB cannot be compiled from
    source, it fetches an already-compiled copy from somewhere else. Each
    borrower wraps a reader and serves one flavour of output, since a MIB
    built with human-readable texts cannot stand in for one built without.
    """

    genTexts: bool = False
    exts: list[str] = []  # noqa: RUF012

    def __init__(self, reader: "AbstractReader", genTexts: bool = False) -> None:
        """Creates an instance of *Borrower* class.

        Args:
            reader: a *reader* object

        Keyword Args:
            genText: indicates whether this borrower should be looking
                     for transformed MIBs that include human-oriented texts
        """
        if genTexts is not None:
            self.genTexts = genTexts

        self._reader = reader

    def __str__(self) -> str:
        return f"{self.__class__.__name__}{{{self._reader}, genTexts={self.genTexts}, exts={self.exts}}}"

    def setOptions(self, **kwargs: Any) -> "AbstractBorrower":
        """Set options on this borrower and on the reader behind it.

        Keyword Args:
            kwargs: option names and values, each assigned to both objects

        Returns:
            The borrower, so calls can be chained.
        """
        self._reader.setOptions(**kwargs)

        for k in kwargs:
            setattr(self, k, kwargs[k])

        return self

    def getData(self, mibname: str, **options: Any) -> tuple["MibInfo", str]:
        """Fetch a pre-compiled MIB module.

        Args:
            mibname (str): MIB module to borrow

        Keyword Args:
            genTexts: whether the caller wants MIBs carrying human-readable
                texts; a borrower that does not match is skipped
            options: passed through to the underlying reader

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its compiled form.

        Raises:
            PySmiFileNotFoundError: this borrower does not serve the flavour
                asked for, or its reader does not have the MIB.
        """
        if bool(options.get("genTexts")) != self.genTexts:
            logger.debug(
                "skipping incompatible borrower %s for file %s",
                self,
                mibname,
                extra={"mib": mibname, "borrower": str(self)},
            )
            raise error.PySmiFileNotFoundError(mibname=mibname, reader=self._reader)

        logger.debug(
            "trying to borrow file %s from %s",
            mibname,
            self._reader,
            extra={"mib": mibname, "reader": str(self._reader)},
        )

        if "exts" not in options:
            options["exts"] = self.exts

        return self._reader.getData(mibname, **options)
