#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2017, Ilya Etingof <etingof@gmail.com>
# License: http://pysmi.sf.net/license.html
#
from pysmi.reader.callback import CallbackReader
from pysmi.reader.ftpclient import FtpReader
from pysmi.reader.httpclient import HttpReader
from pysmi.reader.zipreader import ZipReader
from pysmi.reader.localfile import FileReader
from pysmi.reader.url import getReadersFromUrls
