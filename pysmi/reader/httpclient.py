#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Reading MIB text from a web server."""

import logging
import sys
import time
from typing import Any

from requests import session
from requests.exceptions import RequestException

from pysmi import __version__ as pysmi_version
from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.compat import decode
from pysmi.mibinfo import MibInfo
from pysmi.reader.base import AbstractReader

logger = logging.getLogger(__name__)


@deprecated_camel_case
class HttpReader(AbstractReader):
    """Fetch ASN.1 MIB text by name from a web site.

    *HttpReader* class instance tries to download ASN.1 MIB files
    by name and return their contents to caller.
    """

    MIB_MAGIC = "@mib@"

    def __init__(self, url: str) -> None:
        """Create an instance of *HttpReader* bound to specific URL.

        Note:
            The `http_proxy` and `https_proxy` environment variables are
            respected by the underlying `urllib` stdlib module.

        Args:
            host (str): domain name or IP address of web server
            port (int): TCP port web server is listening
            locationTemplate (str): location part of the URL optionally containing @mib@
                magic placeholder to be replaced with MIB name. If @mib@ magic is not present,
                MIB name is appended to `locationTemplate`

        Keyword Args:
            timeout (int): response timeout
            ssl (bool): access HTTPS web site
        """
        self._url = url

        self.session = session()

        self._user_agent = f"pysmi-{pysmi_version}; python-{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}; {sys.platform}"

    def __str__(self) -> str:
        return self._url

    def get_data(self, mibname: str, **options: Any) -> tuple[MibInfo, str]:
        """Download a MIB over HTTP, trying each candidate file name in turn.

        Raises:
            PySmiReaderFileNotFoundError: the server has none of the candidate
                names, or the request failed.
            PySmiReaderFileNotModifiedError: the server reports the MIB is
                older than requested.
        """
        headers = {"Accept": "text/plain", "User-Agent": self._user_agent}

        mibname = decode(mibname)

        logger.debug("looking for MIB %s", mibname, extra={"mib": mibname})

        for mibalias, mibfile in self.get_mib_variants(mibname, **options):
            url = self._url.replace(self.MIB_MAGIC, mibfile) if self.MIB_MAGIC in self._url else self._url + mibfile

            logger.debug("trying to fetch MIB from %s", url, extra={"mib": mibname, "url": url})

            try:
                response = self.session.get(url, headers=headers)

            except RequestException as exc:
                logger.debug(
                    "failed to fetch MIB from %s: %s",
                    url,
                    exc,
                    extra={"mib": mibname, "url": url, "error": str(exc)},
                )
                continue

            logger.debug(
                "HTTP response %s",
                response.status_code,
                extra={"mib": mibname, "url": url, "status_code": response.status_code},
            )

            if response.status_code == 200:
                try:
                    mtime = time.mktime(time.strptime(response.headers["Last-Modified"], "%a, %d %b %Y %H:%M:%S %Z"))

                except (KeyError, ValueError, OverflowError) as exc:
                    # Header absent, unparsable, or outside the platform's time range.
                    logger.debug(
                        "malformed HTTP headers: %s", exc, extra={"mib": mibname, "url": url, "error": str(exc)}
                    )
                    mtime = time.time()

                # Not response.headers["Last-Modified"]: the server need not send
                # it, and mtime already holds the fallback for when it does not.
                logger.debug(
                    "fetching source MIB %s, mtime %s",
                    url,
                    time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
                    extra={"mib": mibname, "url": url, "mtime": mtime},
                )

                return MibInfo(path=url, file=mibfile, name=mibalias, mtime=mtime), response.content.decode("utf-8")

        raise error.PySmiReaderFileNotFoundError(f"source MIB {mibname} not found", reader=self)
