#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Metadata describing a single MIB module."""

from datetime import datetime
from typing import Any, Optional


class MibInfo:
    #: actual MIB name
    name: str = ""

    #: possible alternative to MIB name
    alias: str = ""

    #: URL to MIB file
    path: str = ""

    #: MIB file name
    file: str = ""

    #: MIB file modification time
    mtime: float = 0

    #: module OID
    oid: str = ""

    #: MIB revision as `datetime`
    revision: Optional["datetime"] = None

    #: all OIDs defined in this module
    oids: tuple[str, ...] = ()

    #: MODULE-IDENTITY OID
    identity: str = ""

    #: Enterprise OID
    enterprise: tuple[str, ...] = ()

    #: MODULE-COMPLIANCE OIDs
    compliance: tuple[str, ...] = ()

    #: imported MIB names
    imported: tuple[str, ...] = ()

    def __init__(self, **kwargs: Any) -> None:
        for k in kwargs:
            setattr(self, k, kwargs[k])
