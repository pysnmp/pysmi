#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""AbstractReader.clear_cache is a no-op by default, so MibCompiler.prune
(pysnmp/pysmi#61) can call it on any configured source -- not just
FileReader, which is the only one that actually caches anything -- without
checking what kind of reader it is first.
"""

import unittest

from pysmi.reader.httpclient import HttpReader
from pysmi.reader.zipreader import ZipReader


class ClearCacheDefaultTestCase(unittest.TestCase):
    def testHttpReaderAcceptsClearCacheAsANoOp(self):
        HttpReader("https://example.invalid/@mib@").clear_cache()

    def testZipReaderAcceptsClearCacheAsANoOp(self):
        ZipReader("/nonexistent.zip").clear_cache()


if __name__ == "__main__":
    unittest.main()
