#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the writers."""

import errno
import os
import secrets
import tempfile
from collections.abc import Iterable
from typing import Any, Final

from pysmi._aliases import deprecated_camel_case

#: How many names to try before giving up, as :py:mod:`tempfile` counts it.
_ATTEMPTS: Final = tempfile.TMP_MAX

#: What the temporary file is called while it is being written. Prefixed so
#: that one left behind by a killed process is recognisable, and long enough
#: that colliding with an existing name is not something to plan around.
_PREFIX: Final = "pysmi-"

#: O_BINARY on Windows, nothing anywhere else. Without it the C runtime opens
#: in text mode and translates every newline written through the descriptor,
#: which would give Windows a different file for the same MIB.
_BINARY: Final = getattr(os, "O_BINARY", 0)


def open_new_file(directory: str) -> tuple[int, str]:
    """Create a uniquely named file in *directory* and return it open.

    What a writer wants here is an ordinary new file under a name nothing else
    holds -- it writes the content, then renames it over the destination, so a
    failure part-way leaves the previous version in place rather than a
    truncated one.

    ``tempfile.mkstemp`` is the obvious way to get that and the wrong one. It
    creates the file 0600, because a temporary file is nobody else's business;
    the rename then carries that mode onto the module, and a build's whole
    output is readable only by the user who ran it. That is invisible until
    the output is published -- a corpus served by a container running as
    another uid answers 403 for every module in it (pysnmp/mibs#365).

    Opening the file ourselves asks the kernel for 0666 and lets the umask
    subtract from it, which is what happens for every other file a program
    creates and is what the caller's umask is for. Nothing here reads or sets
    the umask, so there is no window in which another thread creates a file
    under a mask this function installed, and no mode is chosen on the
    caller's behalf.

    Args:
        directory: where to create the file

    Returns:
        An open write-only descriptor and the path it belongs to. The caller
        owns both.

    Raises:
        OSError: the file could not be created.
    """
    for _ in range(_ATTEMPTS):
        path = os.path.join(directory, _PREFIX + secrets.token_hex(8))

        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | _BINARY, 0o666)

        except FileExistsError:
            continue

        return fd, path

    raise FileExistsError(errno.EEXIST, "no unused name found in", directory)


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
