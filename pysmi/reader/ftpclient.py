#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import sys
import time
import ftplib  # nosec
from pysmi.reader.base import AbstractReader
from pysmi.mibinfo import MibInfo
from pysmi.compat import decode
from pysmi import error
from pysmi import debug


class FtpReader(AbstractReader):
    """Fetch ASN.1 MIB text by name from FTP server.
    *FtpReader* class instance tries to download ASN.1 MIB files
    by name and return their contents to caller.
    """

    def __init__(  # nosec
        self,
        host,
        locationTemplate,
        timeout=5,
        ssl=False,
        port=21,
        user="anonymous",
        password="anonymous@",
    ):
        """Create an instance of *FtpReader* bound to specific FTP server
        directory.

        Args:
            host (str): domain name or IP address of web server
            locationTemplate (str): location part of the directory containing @mib@ magic placeholder to be
                replaced with MIB name fetch.

        Keyword Args:
            timeout (int): response timeout
            ssl (bool): access HTTPS web site
            port (int): TCP port web server is listening
            user (str): username at FTP server
            password (str): password for *username* at FTP server
        """
        self._host = host
        self._locationTemplate = locationTemplate
        self._timeout = timeout
        self._ssl = ssl
        self._port = port
        self._user = user
        self._password = password
        if "@mib@" not in locationTemplate:
            raise error.PySmiError(
                "@mib@ placeholder not specified in location at %s" % self
            )

    def __str__(self):
        return (
            f'{self.__class__.__name__}{{"ftp://{self._host}{self._locationTemplate}"}}'
        )

    def getData(self, mibname, **options):
        if self._ssl:
            conn = ftplib.FTP_TLS()  # nosec
        else:
            conn = ftplib.FTP()  # nosec

        try:
            conn.connect(self._host, self._port, self._timeout)

        except ftplib.all_errors:
            raise error.PySmiReaderFileNotFoundError(
                f"failed to connect to FTP server {self._host}:{self._port}: {sys.exc_info()[1]}",
                reader=self,
            )

        try:
            conn.login(self._user, self._password)

        except ftplib.all_errors:
            conn.close()
            raise error.PySmiReaderFileNotFoundError(
                f"failed to log in to FTP server {self._host}:{self._port} as {self._user}/{self._password}: {sys.exc_info()[1]}",
                reader=self,
            )

        mibname = decode(mibname)

        debug.logger & debug.flagReader and debug.logger("looking for MIB %s" % mibname)

        for mibalias, mibfile in self.getMibVariants(mibname, **options):
            location = self._locationTemplate.replace("@mib@", mibfile)

            mtime = time.time()

            debug.logger & debug.flagReader and debug.logger(
                f"trying to fetch MIB {location} from {self._host}:{self._port}"
            )

            data = []

            try:
                try:
                    response = conn.sendcmd("MDTM %s" % location)

                except ftplib.all_errors:
                    debug.logger & debug.flagReader and debug.logger(
                        "server {}:{} does not support MDTM command, fetching file {}".format(
                            self._host, self._port, location
                        )
                    )

                else:
                    debug.logger & debug.flagReader and debug.logger(
                        f"server {self._host}:{self._port} MDTM response is {response}"
                    )

                    if response[:3] == 213:
                        mtime = time.mktime(time.strptime(response[4:], "%Y%m%d%H%M%S"))

                debug.logger & debug.flagReader and debug.logger(
                    "fetching source MIB {}, mtime {}".format(
                        location,
                        time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
                    )
                )

                conn.retrlines("RETR %s" % location, lambda x, y=data: y.append(x))

            except ftplib.all_errors:
                debug.logger & debug.flagReader and debug.logger(
                    f"failed to fetch MIB {location} from {self._host}:{self._port}: {sys.exc_info()[1]}"
                )
                continue

            data = decode("\n".join(data))

            debug.logger & debug.flagReader and debug.logger(
                f"fetched {len(data)} bytes in {location}"
            )

            conn.close()

            return (
                MibInfo(
                    path=f"ftp://{self._host}{location}",
                    file=mibfile,
                    name=mibalias,
                    mtime=mtime,
                ),
                data,
            )

        conn.close()

        raise error.PySmiReaderFileNotFoundError(
            "source MIB %s not found" % mibname, reader=self
        )
