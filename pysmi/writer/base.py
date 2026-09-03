#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the writers."""

from collections.abc import Iterable
from typing import Any

from pysmi._aliases import deprecated_camel_case


@deprecated_camel_case
class AbstractWriter:
    """Base class for writers of generated MIBs.

    A writer stores what a code generator produced -- to a directory, into a
    Python package, or by handing it to a callback. Subclasses implement
    :py:meth:`put_data` and :py:meth:`get_data`.
    """

    def set_options(self, **kwargs: Any) -> "AbstractWriter":
        """Set writer options as attributes.

        Keyword Args:
            kwargs: option names and values, each assigned to the writer

        Returns:
            The writer, so calls can be chained.
        """
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def put_data(self, mibname: str, data: str, comments: tuple[str, ...] = (), dryRun: bool = False) -> None:
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

    def get_data(self, filename: str) -> str:
        """Read back something this writer stored.

        Args:
            filename (str): name the data was stored under

        Returns:
            The stored text, or an empty string when there is none.
        """
        raise NotImplementedError()

    def list_data(self) -> Iterable[str]:
        """List the MIB module names this writer currently holds output for.

        Used by :py:meth:`~pysmi.compiler.MibCompiler.prune` to find output
        whose source MIB has since disappeared. A writer that cannot
        enumerate what it holds -- :py:class:`~pysmi.writer.callback.CallbackWriter`
        hands data to a callback and keeps none of its own -- reports
        nothing, which excludes it from pruning entirely rather than
        raising.

        Returns:
            Names of the modules stored, empty if there are none or this
            writer does not track what it holds.
        """
        return ()

    def del_data(self, mibname: str, dryRun: bool = False) -> None:
        """Remove previously stored output for a MIB module.

        Only ever called for a name :py:meth:`list_data` itself reported, so
        the default implementation here is unreachable unless a subclass
        overrides one of the pair without the other.

        Keyword Args:
            mibname (str): MIB module whose output should be removed
            dryRun: report what would be removed without removing anything

        Raises:
            PySmiWriterError: the output could not be removed.
        """
        raise NotImplementedError()
