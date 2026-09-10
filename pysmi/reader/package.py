#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Fetch ASN.1 MIB text bundled inside a Python package."""

import importlib.resources
import logging
from collections.abc import Iterable
from typing import Any

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.mibinfo import MibInfo, module_names
from pysmi.reader.base import AbstractReader

logger = logging.getLogger(__name__)


@deprecated_camel_case
class PackageReader(AbstractReader):
    """Fetch ASN.1 MIB text bundled as package data.

    Reads through :py:mod:`importlib.resources`, so it works the same way
    whether the package is installed as a directory or sits inside a zipped
    wheel -- unlike :py:class:`~pysmi.reader.localfile.FileReader`, which
    needs a real filesystem path and cannot see into a zip.

    No mtime is reported (:py:class:`~pysmi.mibinfo.MibInfo` defaults it to
    0), since package data does not change between runs: once a MIB served
    from here compiles, the result is reused for as long as the installed
    pysmi that produced it is unchanged. A pysmi upgrade that changes what
    the MIB compiles to is still caught by the "Produced by" version check
    on the compiled output, mtime aside.
    """

    isLocal = True

    def __init__(self, package: str) -> None:
        """Create an instance of *PackageReader* serving *package*'s resources.

        Args:
            package (str): dotted package name holding the MIB text, e.g.
                ``"pysmi.mibs.asn1"``. Every file directly inside it is a
                candidate, named exactly as the MIB module it holds.
        """
        self._package = package

    def __str__(self) -> str:
        """Identify this reader by the package whose resources it reads."""
        return f'{self.__class__.__name__}{{"{self._package}"}}'

    def list_mibs(self) -> Iterable[str]:
        """Names of the modules bundled in the package.

        Only files directly inside the package are candidates, matching what
        :py:meth:`~pysmi.reader.base.AbstractReader.get_data` searches. Each is read and its module headers
        lexed; ``.py`` files and anything else that declares no module
        contributes nothing.
        """
        seen: dict[str, None] = {}

        try:
            root = importlib.resources.files(self._package)

        except ModuleNotFoundError as exc:
            logger.debug(
                "package %s is not available: %s",
                self._package,
                exc,
                extra={"error": str(exc)},
            )
            return []

        for candidate in sorted(root.iterdir(), key=lambda x: x.name):
            if candidate.name.startswith(".") or candidate.name.endswith(
                (".py", ".pyc")
            ):
                continue

            try:
                if not candidate.is_file():
                    continue

                data = candidate.read_bytes()

            except OSError as exc:
                logger.debug(
                    "package resource %s read failure: %s",
                    candidate.name,
                    exc,
                    extra={"error": str(exc)},
                )
                continue

            if len(data) > self.maxMibSize:
                continue

            for name in module_names(data.decode("utf-8", "replace")):
                seen.setdefault(name, None)

        logger.debug(
            "package %s holds %d MIB modules",
            self._package,
            len(seen),
            extra={"modules": len(seen)},
        )

        return list(seen)

    def fetch_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Read a MIB out of the package's bundled resources.

        Raises:
            PySmiReaderFileNotFoundError: no bundled file holds the module.
        """
        logger.debug(
            "looking for MIB %s in package %s",
            mibname,
            self._package,
            extra={"mib": mibname},
        )

        try:
            root = importlib.resources.files(self._package)

        except ModuleNotFoundError as exc:
            raise error.PySmiReaderFileNotFoundError(
                f"package {self._package} is not available: {exc}", reader=self
            ) from exc

        for mibalias, mibfile in self.get_mib_variants(mibname, **options):
            candidate = root.joinpath(mibfile)

            try:
                if not candidate.is_file():
                    continue

            except OSError as exc:
                # A candidate the filesystem will not even stat is one this
                # package cannot be holding -- a name longer than NAME_MAX is
                # the case that turns up in practice, since get_mib_variants()
                # appends extensions and pushes a merely long MIB name over the
                # limit. Path.is_file() only swallows ENOENT, ENOTDIR, EBADF
                # and ELOOP, so ENAMETOOLONG would otherwise escape as a
                # traceback where every other reader reports the module
                # missing.
                logger.debug(
                    "package resource %s stat failure: %s",
                    mibfile,
                    exc,
                    extra={"mib": mibname, "error": str(exc)},
                )
                continue

            logger.debug(
                "trying MIB %s in package %s",
                mibfile,
                self._package,
                extra={"mib": mibname},
            )

            try:
                mibData = candidate.read_bytes()

            except OSError as exc:
                logger.debug(
                    "package resource %s open failure: %s",
                    mibfile,
                    exc,
                    extra={"mib": mibname, "error": str(exc)},
                )
                continue

            return (
                MibInfo(
                    path=f"package://{self._package}/{mibfile}",
                    file=mibfile,
                    name=mibalias,
                ),
                decode(mibData),
            )

        raise error.PySmiReaderFileNotFoundError(
            f"MIB {mibname} not found in package {self._package}", reader=self
        )
