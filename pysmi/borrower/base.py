#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import logging
from typing import ClassVar

from pysmi import error

logger = logging.getLogger(__name__)


class AbstractBorrower:
    genTexts = False
    exts: ClassVar[list[str]] = []

    def __init__(self, reader, genTexts=False):
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

    def __str__(self):
        return f"{self.__class__.__name__}{{{self._reader}, genTexts={self.genTexts}, exts={self.exts}}}"

    def setOptions(self, **kwargs):
        self._reader.setOptions(**kwargs)

        for k in kwargs:
            setattr(self, k, kwargs[k])

        return self

    def getData(self, mibname, **options):
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
