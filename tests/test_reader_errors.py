#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Failure paths of the readers.

These cover handlers that report a problem and carry on. Logging arguments are
evaluated whether or not anything is listening, so an expression that only
holds for the happy path breaks the failure path for everyone.
"""

import io
import logging
import os
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

from pysmi import error
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.zipreader import ZipReader


class NoLastModifiedHandler(BaseHTTPRequestHandler):
    """Serve a MIB without a Last-Modified header, as many servers do."""

    body = b"TEST-MIB DEFINITIONS ::= BEGIN\nEND\n"

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(self.body)))
        self.end_headers()
        self.wfile.write(self.body)

    def log_message(self, *args):
        pass


class HttpReaderTestCase(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), NoLastModifiedHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/@mib@"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def testMibWithoutLastModifiedHeader(self):
        mibInfo, data = HttpReader(self.url).getData("TEST-MIB")

        self.assertEqual(data, NoLastModifiedHandler.body.decode())
        # Falls back to now rather than failing.
        self.assertTrue(mibInfo.mtime > 0)

    def testMibWithoutLastModifiedHeaderWhileLogging(self):
        # The same fetch with a handler attached, so every logging argument is
        # formatted rather than merely evaluated.
        logger = logging.getLogger("pysmi.reader.httpclient")
        records = []
        handler = logging.Handler()
        handler.emit = records.append
        level = logger.level

        logger.setLevel(logging.DEBUG)
        logger.addHandler(handler)
        try:
            HttpReader(self.url).getData("TEST-MIB")
            for record in records:
                record.getMessage()
        finally:
            logger.removeHandler(handler)
            logger.setLevel(level)

        self.assertTrue(records)

    def testUnreachableServerIsReportedAsNotFound(self):
        reader = HttpReader("http://127.0.0.1:9/@mib@")

        self.assertRaises(error.PySmiReaderFileNotFoundError, reader.getData, "TEST-MIB")

    def testMalformedUrlIsReportedAsNotFound(self):
        reader = HttpReader("not-a-url")

        self.assertRaises(error.PySmiReaderFileNotFoundError, reader.getData, "TEST-MIB")


class ZipReaderTestCase(unittest.TestCase):
    @staticmethod
    def makeArchive(**members):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as archive:
            for name, content in members.items():
                archive.writestr(name, content)
        return buf.getvalue()

    def testUnreadableMemberOfNestedArchive(self):
        # A nested archive is read out of a BytesIO, which has no .name. The
        # reference to it lived in the failure handler, so nothing noticed until
        # a member of an inner archive failed to read.
        blob = self.makeArchive(**{"INNER-MIB": "content"})

        reader = ZipReader.__new__(ZipReader)
        data, mtime = reader._readZipFile([[io.BytesIO(blob), "NOT-IN-ARCHIVE", None]])

        self.assertEqual((data, mtime), ("", 0))

    def testCorruptArchiveIsReportedAsNotFound(self):
        blob = bytearray(self.makeArchive(**{"TEST-MIB": "content" * 50}))
        blob[len(blob) // 2] ^= 0xFF

        fd, path = tempfile.mkstemp()
        try:
            os.write(fd, bytes(blob))
            os.close(fd)

            self.assertRaises(error.PySmiReaderFileNotFoundError, ZipReader(path).getData, "TEST-MIB")
        finally:
            os.remove(path)

    def testMissingArchiveIsReportedAsNotFound(self):
        reader = ZipReader(os.path.join(tempfile.gettempdir(), "no-such-archive.zip"))

        self.assertRaises(error.PySmiReaderFileNotFoundError, reader.getData, "TEST-MIB")


suite = unittest.TestLoader().loadTestsFromModule(sys.modules[__name__])

if __name__ == "__main__":
    unittest.TextTestRunner(verbosity=2).run(suite)
