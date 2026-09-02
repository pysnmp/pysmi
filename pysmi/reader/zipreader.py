#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
import datetime
import io
import logging
import os
import time
import zipfile

from pysmi import error
from pysmi.compat import decode
from pysmi.mibinfo import MibInfo
from pysmi.reader.base import AbstractReader

logger = logging.getLogger(__name__)


class ZipReader(AbstractReader):
    """Fetch ASN.1 MIB text by name from a ZIP archive.

    *ZipReader* class instance tries to locate ASN.1 MIB files
    by name, fetch and return their contents to caller.
    """

    useIndexFile = False

    def __init__(self, path, ignoreErrors=True):
        """Create an instance of *ZipReader* serving a ZIP archive.

        Args:
            path (str): path to ZIP archive containing MIB files

        Keyword Args:
            ignoreErrors (bool): ignore ZIP archive access errors
        """
        self._name = path
        self._members = {}
        self._pendingError = None

        try:
            with open(path, "rb") as f:
                self._members = self._readZipDirectory(fileObj=io.BytesIO(f.read()))

        except OSError as exc:
            logger.debug("ZIP file %s open failure: %s", self._name, exc, extra={"path": self._name, "error": str(exc)})

            if not ignoreErrors:
                self._pendingError = error.PySmiError(f"file {self._name} access error: {exc}")

    def _readZipDirectory(self, fileObj):
        archive = zipfile.ZipFile(fileObj)

        members = {}

        for member in archive.infolist():
            filename = os.path.basename(member.filename)
            if not filename:
                continue

            if member.filename.endswith(".zip") or member.filename.endswith(".ZIP"):
                innerZipBlob = archive.read(member.filename)

                innerMembers = self._readZipDirectory(io.BytesIO(innerZipBlob))

                for innerFilename, ref in innerMembers.items():
                    while innerFilename in members:
                        innerFilename += "+"

                    members[innerFilename] = [[fileObj, member.filename, None]]
                    members[innerFilename].extend(ref)

            else:
                mtime = time.mktime(datetime.datetime(*member.date_time[:6]).timetuple())

                members[filename] = [[fileObj, member.filename, mtime]]

        return members

    def _readZipFile(self, refs):
        dataObj = None
        mtime = None

        for fileObj, filename, ref_mtime in refs:
            if not fileObj:
                fileObj = io.BytesIO(dataObj)

            if ref_mtime is not None:
                mtime = ref_mtime

            archive = zipfile.ZipFile(fileObj)

            try:
                dataObj = archive.read(filename)

            except Exception as exc:
                logger.debug(
                    "ZIP read component %s read error: %s",
                    fileObj.name,
                    exc,
                    extra={"path": fileObj.name, "error": str(exc)},
                )
                return "", 0

        return dataObj, mtime

    def __str__(self):
        return f'{self.__class__.__name__}{{"{self._name}"}}'

    def getData(self, mibname, **options):
        logger.debug("looking for MIB %s at %s", mibname, self._name, extra={"mib": mibname, "path": self._name})

        if self._pendingError:
            raise self._pendingError

        if not self._members:
            raise error.PySmiReaderFileNotFoundError(f"source MIB {mibname} not found", reader=self)

        for mibalias, mibfile in self.getMibVariants(mibname, **options):
            logger.debug("trying MIB %s", mibfile, extra={"mib": mibname, "mib_file": mibfile})

            try:
                refs = self._members[mibfile]

            except KeyError:
                continue

            mibData, mtime = self._readZipFile(refs)

            if not mibData:
                continue

            logger.debug(
                "source MIB %s, mtime %s, read from %s/%s",
                mibfile,
                time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(mtime)),
                self._name,
                mibfile,
                extra={"mib": mibname, "mib_file": mibfile, "path": self._name, "mtime": mtime},
            )

            if len(mibData) == self.maxMibSize:
                raise OSError(f"MIB {self._name}/{mibfile} too large")

            return MibInfo(path=f"zip://{self._name}/{mibfile}", file=mibfile, name=mibalias, mtime=mtime), decode(
                mibData
            )

        raise error.PySmiReaderFileNotFoundError(f"source MIB {mibname} not found", reader=self)
