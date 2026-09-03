#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Metadata describing a single MIB module."""

import hashlib
from datetime import datetime
from typing import Any, Optional


def source_digest(source: str) -> str:
    """Return the SHA-256 of a MIB source, identifying it across platforms.

    Newlines are normalised to ``\n`` first, so a MIB checked out with CRLF
    line endings hashes the same as the LF copy it was made from. The digest
    identifies the ASN.1 text, not the exact bytes on any one disk.

    Args:
        source: the ASN.1 source of a MIB module.

    Returns:
        The hex digest, prefixed with the algorithm, e.g. ``sha256:1f3a...``.
    """
    normalised = source.replace("\r\n", "\n").replace("\r", "\n")
    return "sha256:" + hashlib.sha256(normalised.encode("utf-8")).hexdigest()


class MibInfo:
    """What PySMI knows about one MIB module.

    Readers fill in where the module came from; code generators fill in what
    it contains. Every field has a default, and any of them can be set from
    keyword arguments at construction.
    """

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

    #: NOTIFICATION-TYPE OIDs, including converted TRAP-TYPEs
    notification: tuple[str, ...] = ()

    #: imported MIB names
    imported: tuple[str, ...] = ()

    #: SHA-256 of the ASN.1 source, newlines normalised to ``\n``
    digest: str = ""

    def __init__(self, **kwargs: Any) -> None:
        for k in kwargs:
            setattr(self, k, kwargs[k])
