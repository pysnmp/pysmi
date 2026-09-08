"""Canonical form of a MIB module's model, and the hash over it.

A MIB module needs an identity that answers "is this the same module content?"
The digest in ``meta.comments`` answers a different question -- "is this the
same file?" -- because it covers raw ASN.1 bytes. Reindenting a MIB, fixing a
typo in a comment, or a CRLF round-trip all change it while changing nothing a
consumer of the model can observe.

Every consequence of using the wrong one is wrong. A customer build comparing
against a reference corpus reports a shadow that does not exist; a slim corpus
filtered from a full one fails to match it; a rebuild churns artifacts that are
semantically identical.

So this module defines a *canonical form* -- one byte sequence per module model,
independent of how the source was formatted and of which pysmi produced it --
and hashes it.

The specification is ``docs/source/jsondoc-schema.rst``, under "Module
identity". Anything here that the specification does not state is an
implementation detail; anything the specification states that this does not do
is a bug in one of them.

See pysnmp/pysmi#180.
"""

import hashlib
import json
from collections.abc import Iterable
from typing import Any

#: Version of the normalization algorithm, not of the schema.
#:
#: It is mixed into the hashed bytes, so a change here changes every hash even
#: when no module changed. That is the point: a consumer comparing hashes across
#: a normalization change must be told rather than silently see everything move.
#: Bumping it is a breaking change for anyone who pinned a hash.
NORMALIZATION_VERSION = 1

#: Domain separation. Prefixing the hashed bytes means a hash of a canonical
#: form can never collide with a hash of the same bytes computed for some other
#: purpose, and pins the algorithm version into the digest itself.
_PREFIX = f"pysmi-normalized-v{NORMALIZATION_VERSION}\n".encode()

#: Fields carrying human-readable prose rather than model structure.
#:
#: These are exactly the fields ``--generate-mib-texts`` controls, minus
#: ``lastupdated``, which that flag also gates but which is a timestamp rather
#: than prose (pysnmp/pysmi#191). ``units`` and ``displayhint`` are *not* here:
#: both are machine-readable and both change how a value is interpreted.
TEXT_FIELDS = frozenset(
    (
        "description",
        "reference",
        "organization",
        "contactinfo",
    )
)

#: Keys excluded from the canonical form at the document's top level.
#:
#: ``meta`` carries the source digest, the producing pysmi version and the
#: caller's comments. None of it is model content, and including it would make
#: the hash change on every pysmi release -- the opposite of what it is for.
_EXCLUDED_TOPLEVEL = frozenset(("meta",))


def _strip(value: Any, drop: Iterable[str]) -> Any:
    """Copy *value*, recursively removing keys named in *drop*.

    Args:
        value: any decoded JSON value.
        drop: field names to remove wherever they occur.

    Returns:
        A copy with those keys absent. Lists keep their order, because order is
        semantic throughout the model -- INDEX elements, revisions, ranges and
        object lists all mean something different reordered.
    """
    dropped = frozenset(drop)

    if isinstance(value, dict):
        return {
            key: _strip(item, dropped)
            for key, item in value.items()
            if key not in dropped
        }

    if isinstance(value, list):
        return [_strip(item, dropped) for item in value]

    return value


def canonical_form(document: dict[str, Any], includeTexts: bool = True) -> bytes:
    """Render *document* as the canonical bytes its hash is taken over.

    Args:
        document: a decoded schema-v1 JSON document, as
            :py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_code` emits it.
        includeTexts: carry the prose fields. False yields the structural form,
            which is what a corpus without descriptions is built from.

    Returns:
        UTF-8 bytes: the algorithm-version prefix, then the model serialized
        with keys sorted and no insignificant whitespace.

    The rules, in full, because a non-pysmi implementation has to agree:

    * ``meta`` is excluded; every other top-level key is kept
    * when *includeTexts* is false, :py:data:`TEXT_FIELDS` are removed wherever
      they occur, at any depth
    * object keys are sorted by Unicode code point
    * arrays keep their order
    * separators are ``","`` and ``":"`` with no spaces
    * non-ASCII characters are emitted as themselves, not escaped
    """
    model = {
        key: value for key, value in document.items() if key not in _EXCLUDED_TOPLEVEL
    }

    if not includeTexts:
        model = _strip(model, TEXT_FIELDS)

    serialized = json.dumps(
        model,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )

    return _PREFIX + serialized.encode("utf-8")


def content_hash(document: dict[str, Any]) -> str:
    """The module's identity, prose included.

    Two documents share this hash exactly when their models are equal. It is
    what a corpus records per module, and what a shadow check compares.

    Args:
        document: a decoded schema-v1 JSON document.

    Returns:
        Lowercase hex SHA-256 of :py:func:`canonical_form`.
    """
    return hashlib.sha256(canonical_form(document, includeTexts=True)).hexdigest()


def structure_hash(document: dict[str, Any]) -> str:
    """The module's identity with prose excluded.

    The corpus splits descriptions into a separate artifact, so a build that
    ships structure alone needs an identity for what it shipped. Two modules
    differing only in their DESCRIPTION text share this hash and differ in
    :py:func:`content_hash`.

    Equal between a document generated with texts and one generated without:
    prose is the only thing text suppression removes. That held only once
    pysnmp/pysmi#190, #191 and #192 landed -- before them a no-texts document
    was structurally lossy, dropping MODULE-COMPLIANCE refinement entries and
    ``lastupdated``, and the two disagreed.

    Args:
        document: a decoded schema-v1 JSON document.

    Returns:
        Lowercase hex SHA-256 of the structural :py:func:`canonical_form`.
    """
    return hashlib.sha256(canonical_form(document, includeTexts=False)).hexdigest()


def module_hashes(document: dict[str, Any]) -> dict[str, Any]:
    """Both hashes and the algorithm version, ready to record.

    Args:
        document: a decoded schema-v1 JSON document.

    Returns:
        A mapping with ``normalization``, ``content`` and ``structure``. The
        version travels with the hashes because a hash without the algorithm
        that produced it cannot be compared to anything.
    """
    return {
        "normalization": NORMALIZATION_VERSION,
        "content": content_hash(document),
        "structure": structure_hash(document),
    }
