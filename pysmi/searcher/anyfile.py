#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Looking for an already-transformed MIB file of any format."""

import logging
import os
import time

from pysmi import __name__ as packageName
from pysmi import __version__ as packageVersion
from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.mibinfo import producer_of
from pysmi.searcher.base import AbstractSearcher

logger = logging.getLogger(__name__)


@deprecated_camel_case
class AnyFileSearcher(AbstractSearcher):
    """Figures out if given file exists at given location."""

    exts: list[str] = []  # noqa: RUF012

    def __init__(self, path: str) -> None:
        """Create an instance of *AnyFileSearcher* bound to specific directory.

        Args:
          path (str): path to local directory
        """
        self._path = os.path.normpath(decode(path))

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._path}"}}'

    def file_exists(self, mibname: str, mtime: float, rebuild: bool = False) -> None:
        """Compare a stored file's modification time against the MIB source.

        A file that is otherwise fresh is also checked against the
        "Produced by" marker this package's own writer leaves behind --
        read as a "#"-commented line, or from a JSON document's
        ``meta.comments`` -- so a MIB compiled by a since-fixed pysmi is
        stale even though its source never changed.
        """
        if rebuild:
            logger.debug("pretend %s is very old", mibname, extra={"mib": mibname})
            return

        mibname = decode(mibname)
        basename = os.path.join(self._path, mibname)

        for sfx in self.exts:
            f = basename + sfx
            if not os.path.exists(f) or not os.path.isfile(f):
                logger.debug("%s not present or not a file", f, extra={"mib": mibname, "path": f})
                continue

            try:
                fileTime = os.stat(f).st_mtime

            except OSError as exc:
                raise error.PySmiSearcherError(f"failure opening compiled file {f}: {exc}", searcher=self) from exc

            logger.debug(
                "found %s, mtime %s",
                f,
                time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(fileTime)),
                extra={"mib": mibname, "path": f, "mtime": fileTime},
            )

            if fileTime < mtime:
                continue

            try:
                with open(f, "rb") as fp:
                    text = decode(fp.read())

            except (OSError, UnicodeDecodeError) as exc:
                raise error.PySmiSearcherError(f"failure opening compiled file {f}: {exc}", searcher=self) from exc

            producer = producer_of(text)

            if producer is not None and producer != (packageName, packageVersion):
                logger.debug(
                    "%s was produced by %s-%s, this is %s-%s, will rebuild",
                    f,
                    *producer,
                    packageName,
                    packageVersion,
                    extra={"mib": mibname, "path": f, "producer": producer},
                )
                continue

            raise error.PySmiFileNotModifiedError()

        raise error.PySmiFileNotFoundError(f"no compiled file {mibname} found", searcher=self)
