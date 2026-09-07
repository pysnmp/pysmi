"""JSON Schemas for the documents :py:class:`~pysmi.codegen.jsondoc.JsonCodeGen`
emits.

The schemas ship as package data so a consumer can *validate* a document rather
than trust it, and can do so without depending on pysmi's source tree. They are
the machine-readable half of the specification in
``docs/source/jsondoc-schema.rst``; where the two disagree, the prose describes
intent and the schema describes what is emitted, and the disagreement is a bug.

Versioning follows :py:attr:`~pysmi.codegen.jsondoc.JsonCodeGen.SCHEMA_VERSIONS`.
A document records the version it was emitted against in ``meta.schema``, so a
consumer reads that and asks for the matching schema rather than inferring the
shape from the document in front of it.
"""

import importlib.resources
import json
from functools import cache
from typing import Any, Literal

#: The document kinds that have a schema. ``"document"`` is what
#: :py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_code` emits for one module;
#: ``"index"`` is what :py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_index`
#: emits for a set of them.
Kind = Literal["document", "index"]

_FILENAMES: dict[Kind, str] = {
    "document": "jsondoc-v{version}.schema.json",
    "index": "jsonindex-v{version}.schema.json",
}


@cache
def schema(kind: Kind = "document", version: int = 1) -> dict[str, Any]:
    """The JSON Schema for *kind* at schema *version*.

    Args:
        kind: ``"document"`` for a single module, ``"index"`` for an OID index.
        version: the schema version, matching a document's ``meta.schema``.

    Returns:
        The decoded schema. Cached, so callers share one object -- treat it as
        read-only.

    Raises:
        ValueError: no schema ships for that kind and version.
    """
    try:
        filename = _FILENAMES[kind].format(version=version)
    except KeyError:
        kinds = ", ".join(sorted(_FILENAMES))
        raise ValueError(
            f"unknown schema kind {kind!r}; expected one of {kinds}"
        ) from None

    resource = importlib.resources.files(__name__) / filename

    if not resource.is_file():
        raise ValueError(f"no {kind} schema ships for version {version}")

    document: dict[str, Any] = json.loads(resource.read_text())

    return document
