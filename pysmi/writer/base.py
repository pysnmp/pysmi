#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the writers."""

from typing import Any


class AbstractWriter:
    """Base class for writers of generated MIBs.

    A writer stores what a code generator produced -- to a directory, into a
    Python package, or by handing it to a callback. Subclasses implement
    :py:meth:`putData` and :py:meth:`getData`.
    """

    def setOptions(self, **kwargs: Any) -> "AbstractWriter":
        """Set writer options as attributes.

        Keyword Args:
            kwargs: option names and values, each assigned to the writer

        Returns:
            The writer, so calls can be chained.
        """
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def putData(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
        """Store the generated form of a MIB module.

        Args:
            mibname (str): MIB module the output belongs to
            data (str): generated MIB, as produced by a code generator

        Keyword Args:
            comments: lines to record in the output, where the format has
                somewhere to put them
            dryRun: go through the motions without storing anything

        Raises:
            PySmiWriterError: the output could not be stored.
        """
        raise NotImplementedError()

    def getData(self, filename: str) -> str:
        """Read back something this writer stored.

        Args:
            filename (str): name the data was stored under

        Returns:
            The stored text, or an empty string when there is none.
        """
        raise NotImplementedError()
