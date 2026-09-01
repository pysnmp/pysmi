#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
from pysmi.parser.base import AbstractParser


class NullParser(AbstractParser):
    def __init__(self, startSym='mibFile', tempdir=''):
        # Intentionally empty: NullParser performs no initialization.
        pass

    def reset(self):
        # Intentionally empty: NullParser holds no state to reset.
        pass

    def parse(self, data, **kwargs):
        return []
