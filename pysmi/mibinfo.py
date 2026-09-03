#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Metadata describing a single MIB module."""

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Optional

_PRODUCER_RE = re.compile(r"Produced by (?P<name>\S+?)-(?P<version>\S+)")
_DIGEST_RE = re.compile(r"Source digest (?P<digest>\S+)")


def producer_of(text: str) -> tuple[str, str] | None:
    """Read back the "Produced by <package>-<version>" marker *compiler*
    records in every module it stores.

    Checked directly against a "#"-commented Python source, and against the
    ``meta.comments`` array of a JSON document -- the two shapes the marker
    is recorded in today. A file carrying neither, or naming some other
    package, was not produced by this tool, or predates this marker being
    read back; either way there is nothing to compare.

    Args:
        text: the stored MIB module, as written by a writer.

    Returns:
        The recorded package name and version, or ``None``.
    """
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        doc = None

    if isinstance(doc, dict):
        comments = doc.get("meta", {}).get("comments") or []
        text = "\n".join(comments)

    match = _PRODUCER_RE.search(text)
    return (match["name"], match["version"]) if match else None


def digest_of(text: str) -> str | None:
    """Read back the "Source digest <digest>" marker *compiler* records
    alongside the "Produced by" marker in every module it stores.

    Same two shapes as :py:func:`producer_of`: a "#"-commented line in
    Python source, or the ``meta.comments`` array of a JSON document. A
    file carrying neither predates this marker, or was not produced by
    this tool.

    Args:
        text: the stored MIB module, as written by a writer.

    Returns:
        The recorded digest of the ASN.1 source it was compiled from, or
        ``None``.
    """
    try:
        doc = json.loads(text)
    except (TypeError, ValueError):
        doc = None

    if isinstance(doc, dict):
        comments = doc.get("meta", {}).get("comments") or []
        text = "\n".join(comments)

    match = _DIGEST_RE.search(text)
    return match["digest"] if match else None


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
        """Set the given fields, leaving the rest at their class defaults.

        Every attribute documented above is accepted as a keyword argument, so
        a reader fills in only what it knows about the MIB it just fetched.
        """
        for k in kwargs:
            setattr(self, k, kwargs[k])
