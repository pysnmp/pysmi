#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Fetch ASN.1 MIB text bundled inside a Python package."""

import importlib.resources
import logging
from typing import Any

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.mibinfo import MibInfo
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

    def __init__(self, package: str) -> None:
        """Create an instance of *PackageReader* serving *package*'s resources.

        Args:
            package (str): dotted package name holding the MIB text, e.g.
                ``"pysmi.mibs.asn1"``. Every file directly inside it is a
                candidate, named exactly as the MIB module it holds.
        """
        self._package = package

    def __str__(self) -> str:
        return f'{self.__class__.__name__}{{"{self._package}"}}'

    def get_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Read a MIB out of the package's bundled resources.

        Raises:
            PySmiReaderFileNotFoundError: no bundled file holds the module.
        """
        logger.debug("looking for MIB %s in package %s", mibname, self._package, extra={"mib": mibname})

        try:
            root = importlib.resources.files(self._package)

        except ModuleNotFoundError as exc:
            raise error.PySmiReaderFileNotFoundError(
                f"package {self._package} is not available: {exc}", reader=self
            ) from exc

        for mibalias, mibfile in self.get_mib_variants(mibname, **options):
            candidate = root.joinpath(mibfile)

            if not candidate.is_file():
                continue

            logger.debug("trying MIB %s in package %s", mibfile, self._package, extra={"mib": mibname})

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
                MibInfo(path=f"package://{self._package}/{mibfile}", file=mibfile, name=mibalias),
                decode(mibData),
            )

        raise error.PySmiReaderFileNotFoundError(f"MIB {mibname} not found in package {self._package}", reader=self)
