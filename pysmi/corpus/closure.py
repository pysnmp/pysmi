#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The files a module needs, as a fact the build wrote down.

``core.db``'s ``import`` table holds the direct edges -- this module imports
that symbol from that module. The question a consumer actually arrives with is
the closure: *which files do I need in order to load this module?*

.. code-block:: text

    IF-MIB                    -> 6 files
      IANAifType-MIB  IF-MIB  SNMPv2-CONF  SNMPv2-MIB  SNMPv2-SMI  SNMPv2-TC

    CISCO-ENTITY-ALARM-MIB    -> 9 files
      CISCO-ENTITY-ALARM-MIB  CISCO-SMI  ENTITY-MIB  IANA-ENTITY-MIB
      SNMP-FRAMEWORK-MIB  SNMPv2-CONF  SNMPv2-SMI  SNMPv2-TC  UUID-TC-MIB

The build already resolves every one of those edges in order to compile.
Having each consumer re-walk a table to recover a fact the compiler
established is the pattern this exists to avoid -- and there are three of
them: a page answering "the files you need", anyone packaging a subset for an
air-gapped install or an image carrying only what one product needs, and
pysnmp deciding what to preload.

Two things this settles rather than leaving to the caller:

* **A module is in its own closure.** That makes the artifact directly usable
  as a file list, which is what most callers want. ``IF-MIB`` needs six files
  and one of them is ``IF-MIB``.
* **A dependency the corpus does not hold is recorded, not dropped.** A caller
  has to be able to tell "this module needs nothing else" from "something it
  needs is not here", and a closure that silently omits the second is the
  worse answer of the two. See :py:attr:`Closure.missing`.

The names are module names, which are the names of the files in the published
ASN.1 tree -- that naming is a contract, see :ref:`asn1-naming` -- so a caller
holding a closure holds the file list and can build the URLs itself.
"""

import json
import logging
from collections.abc import Iterable, Iterator
from typing import Any, Final, NamedTuple

logger = logging.getLogger(__name__)

#: The artifact's own version, stamped into what is written. Bumped when the
#: shape changes, so a consumer reading an older file can say so.
SCHEMA_VERSION: Final = 1

#: The key a jsondoc's ``imports`` map uses for something that is not a module.
_NOT_A_MODULE: Final = "class"


class Closure(NamedTuple):
    """Everything one module needs in order to load."""

    #: The modules to load, sorted, the module itself among them. These are
    #: the file names in the published ASN.1 tree.
    files: tuple[str, ...]

    #: Modules named somewhere in the closure that the corpus does not hold,
    #: sorted. Empty for a closure that is complete. A module is listed here
    #: however deep it was reached from, because a hole anywhere below a
    #: module is a hole for that module: it still cannot be loaded.
    missing: tuple[str, ...]


def imported(document: "dict[str, Any]") -> Iterator[str]:
    """The modules one jsondoc's IMPORTS clause names.

    Args:
        document: the jsondoc.

    Yields:
        Each module named, in the order the document holds them. The
        ``class`` key is not one: it says what kind of thing the clause is,
        not where a symbol came from.
    """
    imports = document.get("imports")

    if not isinstance(imports, dict):
        return

    for source in imports:
        if source != _NOT_A_MODULE and isinstance(source, str):
            yield source


def closures(
    documents: "Iterable[tuple[str, dict[str, Any], Any, Any]]",
) -> dict[str, Closure]:
    """Work out what every module in a corpus needs.

    Args:
        documents: ``(module, jsondoc, tier, rfc)`` per module, as
            :py:func:`pysmi.corpus.index.read_documents` yields them. Only the
            first two are read; the signature matches so that a caller already
            holding the corpus can hand it straight over.

    Returns:
        The closure per module, keyed by module name.
    """
    edges = {
        module: tuple(dict.fromkeys(imported(document)))
        for module, document, *_ in documents
    }

    return {module: _closure(module, edges) for module in sorted(edges)}


def _closure(start: str, edges: dict[str, tuple[str, ...]]) -> Closure:
    """Walk one module's imports to the end of them.

    Breadth-first from *start* rather than a memoised recursion, because MIB
    imports may be cyclic and a closure under a cycle is a fixpoint rather
    than something a single post-order pass computes. A corpus holds a few
    thousand modules whose closures are a few files each, so walking each one
    from scratch costs nothing worth the trouble of being clever about it.
    """
    files: set[str] = set()
    missing: set[str] = set()
    pending = [start]

    while pending:
        module = pending.pop()

        if module in files or module in missing:
            continue

        if module not in edges:
            # Not in the corpus. Recorded and not walked into, there being
            # nothing to walk: what it imports is not knowable from here.
            missing.add(module)
            continue

        files.add(module)
        pending.extend(edges[module])

    return Closure(tuple(sorted(files)), tuple(sorted(missing)))


def as_document(found: dict[str, Closure]) -> dict[str, Any]:
    """The artifact, as plain data.

    Args:
        found: the closures, as :py:func:`closures` returns them.

    Returns:
        A ``meta`` block and a ``closure`` map of module name to its file list
        and what is missing from it.
    """
    return {
        "meta": {
            "schema": SCHEMA_VERSION,
            "modules": len(found),
            "incomplete": sum(1 for x in found.values() if x.missing),
        },
        "closure": {
            module: {"files": list(x.files), "missing": list(x.missing)}
            for module, x in sorted(found.items())
        },
    }


def render_closure(found: dict[str, Closure]) -> str:
    """The artifact as it is written, ending in a newline.

    Compact, like the type specifications :py:mod:`pysmi.corpus.db` stores:
    this is a generated artifact and nobody reads it by eye. See
    pysnmp/pysmi#283.

    Args:
        found: the closures, as :py:func:`closures` returns them.

    Returns:
        The JSON. Written by the driver, which owns where artifacts go.
    """
    return json.dumps(as_document(found), separators=(",", ":")) + "\n"


def counts(found: dict[str, Closure]) -> dict[str, int]:
    """How many closures there are and how many are incomplete, for the report.

    The second number is the one to look at: it counts modules this corpus
    publishes that nothing here can load.
    """
    incomplete = sum(1 for x in found.values() if x.missing)

    logger.info(
        "import closures: %d modules, %d with a dependency the corpus does not hold",
        len(found),
        incomplete,
        extra={"modules": len(found), "incomplete": incomplete},
    )

    return {"modules": len(found), "incomplete": incomplete}
