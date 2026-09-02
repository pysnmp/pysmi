#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Fetching ASN.1 MIB text from wherever it lives."""

from pysmi.reader.callback import CallbackReader
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.url import getReadersFromUrls
from pysmi.reader.zipreader import ZipReader
