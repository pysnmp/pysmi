#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Metadata describing a single MIB module."""

import hashlib
import json
import re
import threading
from collections.abc import Iterator
from datetime import datetime
from typing import Any, Optional

_PRODUCER_RE = re.compile(r"Produced by (?P<name>\S+?)-(?P<version>\S+)")
_DIGEST_RE = re.compile(r"Source digest (?P<digest>\S+)")

#: One lexer per thread. PLY lexers carry position state across calls, and
#: nothing stops two threads from scanning MIB text at the same time.
_lexers = threading.local()

#: Token types a module name can be lexed as. Upper case is the convention
#: and very nearly universal, but modules named ``companyMIB`` or
#: ``proware-SNMP-MIB`` exist and compile, so the lower-case identifier
#: counts too.
_NAME_TOKENS: tuple[str, ...] = ("UPPERCASE_IDENTIFIER", "LOWERCASE_IDENTIFIER")


def _module_name_lexer() -> Any:
    """The ASN.1 lexer this thread scans module headers with.

    Built for the relaxed SMIv1 dialect, the widest one pysmi parses, so
    that a header this recognises belongs to a module the parser will at
    least attempt.
    """
    existing = getattr(_lexers, "lexer", None)

    if existing is None:
        from pysmi.lexer.smi import lexerFactory
        from pysmi.parser.dialect import smiV1Relaxed

        existing = lexerFactory(**smiV1Relaxed)()
        _lexers.lexer = existing

    return existing


def _module_name_tokens(text: str) -> Iterator[Any]:
    """Lex *text*, yielding tokens until it ends or stops making sense.

    Text that stops lexing partway still yields what came before. Vendor
    MIB text is not uniformly clean, and a byte the lexer refuses deep
    inside a module says nothing about whether the file is one.
    """
    lexer = _module_name_lexer()
    lexer.reset()
    lexer.lexer.input(text)

    while True:
        try:
            token = lexer.lexer.token()
        except Exception:  # noqa: BLE001 - a lexer error just ends the scan
            return

        if token is None:
            return

        yield token


def module_names(text: str) -> list[str]:
    """Every MIB module *text* declares a header for, in the order written.

    A MIB module is named inside the file rather than by it, and one file
    may hold several. This reads the ``<name> DEFINITIONS ::= BEGIN``
    headers with pysmi's own lexer rather than with an expression of its
    own: vendors break a header across lines and drop a ``-- REVISION``
    note into the middle of it, and the lexer already knows how ASN.1
    comments and line breaks work.

    Args:
        text: MIB source.

    Returns:
        The module names declared, empty when *text* is not MIB source at
        all -- which is how a login wall or an error page served as 200
        tells itself apart from a module.
    """
    found: list[str] = []
    previous: str | None = None

    for token in _module_name_tokens(text):
        if token.type == "DEFINITIONS" and previous is not None:
            found.append(previous)

        previous = token.value if token.type in _NAME_TOKENS else None

    return found


def strip_comments(text: str) -> str:
    """Remove ASN.1 comments from *text*, leaving quoted strings intact.

    A comment runs from ``--`` to the next ``--`` or to end of line (RFC 2578
    Section 3.1). Inside a quoted string ``--`` is ordinary text, so this
    tracks strings rather than matching ``--`` everywhere: a DESCRIPTION
    reading ``"a -- b"`` must not swallow whatever follows it on the line.
    ASN.1 writes a literal double quote as ``""``, which is handled the same
    way -- it does not end the string.

    Newlines are preserved, so line numbers and anything anchored to them
    survive.

    Args:
        text: MIB source.

    Returns:
        The same text with comment spans removed.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    inString = False

    while index < length:
        char = text[index]

        if inString:
            if char == '"':
                if index + 1 < length and text[index + 1] == '"':
                    out.append('""')
                    index += 2
                    continue

                inString = False

            out.append(char)
            index += 1
            continue

        if char == '"':
            inString = True
            out.append(char)
            index += 1
            continue

        if char == "-" and index + 1 < length and text[index + 1] == "-":
            index += 2

            while index < length:
                if text[index] == "\n":
                    break

                if text[index] == "-" and index + 1 < length and text[index + 1] == "-":
                    index += 2
                    break

                index += 1

            continue

        out.append(char)
        index += 1

    return "".join(out)


def normalise_revision(stamp: str) -> str | None:
    """Widen a MODULE-IDENTITY timestamp so that stamps sort chronologically.

    RFC 2578 Section 2 allows both ``YYMMDDHHMMZ`` and ``YYYYMMDDHHMMZ``, and
    the two do not compare against each other: ``"9908190000Z"`` sorts above
    ``"200210160000Z"``, making a 1999 revision beat a 2002 one. Widening the
    short form the way that section reads it -- two-digit years from 70 are
    1900s, the rest 2000s -- makes plain string comparison correct.

    73 of the 433 bundled modules carrying a MODULE-IDENTITY use the short
    form, so this is not a theoretical case.

    A stamp that does not denote a date is refused rather than widened. The
    comparison this feeds is lexicographic, so a value that is merely the right
    *length* rides it without ever being a time: ``HPR-MIB`` is published with
    ``LAST-UPDATED "970514000000Z"``, thirteen characters, which read as the
    wide form is year 9705 of month 14. That sorts above every date there will
    ever be, so the copy carrying it won against every other copy of the module
    for good. The code generator already refuses the same value --
    :py:func:`~pysmi.codegen.base.format_ext_utc_time` cannot read it,
    substitutes the epoch and logs that it did -- and this is that check on the
    side that decides which copy is used.

    Refusing is not a lost revision: a module whose revision cannot be placed
    falls to source order, which is what
    :py:meth:`~pysmi.compiler.MibCompiler.compile` already documents for a copy
    carrying no revision at all. Treating an unreadable stamp as the newest one
    possible is the alternative, and it is worse.

    Args:
        stamp: the timestamp as written in the MIB.

    Returns:
        The timestamp as ``YYYYMMDDHHMMZ``, or ``None`` when it is not one of
        the two forms RFC 2578 admits or does not name a real date.
    """
    if len(stamp) == 11:
        stamp = ("19" if stamp[:2] >= "70" else "20") + stamp

    if len(stamp) != 13:
        return None

    try:
        datetime.strptime(stamp, "%Y%m%d%H%M%z")

    except ValueError:
        return None

    return stamp


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
        for k, v in kwargs.items():
            setattr(self, k, v)
