#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the searchers."""

from typing import Any

from pysmi._aliases import deprecated_camel_case


@deprecated_camel_case
class AbstractSearcher:
    """Base class for searchers of already-compiled MIBs.

    A searcher answers one question for the compiler: is the compiled form of
    this MIB new enough to leave alone? It reports the answer by raising, so
    subclasses implement :py:meth:`file_exists` and never return a verdict.
    """

    def set_options(self, **kwargs: Any) -> "AbstractSearcher":
        """Set searcher options as attributes.

        Keyword Args:
            kwargs: option names and values, each assigned to the searcher

        Returns:
            The searcher, so calls can be chained.
        """
        for k in kwargs:
            setattr(self, k, kwargs[k])
        return self

    def file_exists(self, mibname: str, mtime: float, rebuild: bool = False, digest: str | None = None) -> None:
        """Report whether a compiled MIB is current, by raising.

        Args:
            mibname (str): MIB module to look for
            mtime (float): modification time of the MIB source, which the
                compiled form must be at least as new as

        Keyword Args:
            rebuild: ignore whatever is stored and report nothing, so the
                caller recompiles
            digest: digest of the MIB source about to be compiled, as
                returned by ``pysmi.mibinfo.source_digest``. Lets a
                subclass tell a stored file apart from one produced from a
                *different* source that merely has an equal or older
                modification time -- the case a primary source with a stale
                mtime, following a fallback source's compile, would
                otherwise pass. ``None`` skips the check.

        Raises:
            PySmiFileNotModifiedError: the compiled MIB is up to date and the
                compiler should skip this module.
            PySmiFileNotFoundError: nothing usable is stored, so the module
                must be compiled.
            PySmiSearcherError: something is stored but could not be examined.
        """
        raise NotImplementedError()
