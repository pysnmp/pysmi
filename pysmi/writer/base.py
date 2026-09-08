#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the writers."""

import os
from collections.abc import Iterable
from typing import Any

from pysmi._aliases import deprecated_camel_case


def readable_mode() -> int:
    """The mode a written file should carry, as the process's umask allows.

    ``tempfile.mkstemp`` creates a file readable by its owner and nobody else,
    which is right for a temporary file and wrong for the thing it becomes: a
    writer renames that file into place, so every module a build stores ends up
    0600. That is invisible while output is read back by the user who wrote it,
    and it is not invisible at all when the output is published -- a corpus
    served by a container running as another uid answers 403 for every module
    in it (pysnmp/mibs#365).

    The umask is what says how permissive a new file should be, and reading it
    means setting it, so it is set back immediately. A thread creating a file
    in that window would see the temporary value; nothing in pysmi does, and
    the alternative is hard-coding a mode that ignores the caller's umask
    entirely.

    Returns:
        0666 less the umask -- 0644 under the usual 022, and honouring a
        stricter umask where one is set.
    """
    umask = os.umask(0o022)
    os.umask(umask)

    return 0o666 & ~umask


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
        for k, v in kwargs.items():
            setattr(self, k, v)
        return self

    def put_data(
        self,
        mibname: str,
        data: str,
        comments: tuple[str, ...] = (),
        dryRun: bool = False,
    ) -> None:
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
        raise NotImplementedError

    def get_data(self, filename: str) -> str:
        """Read back something this writer stored.

        Args:
            filename (str): name the data was stored under

        Returns:
            The stored text, or an empty string when there is none.
        """
        raise NotImplementedError

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
        raise NotImplementedError
