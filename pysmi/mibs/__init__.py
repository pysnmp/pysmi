"""Base MIB ASN.1 sources bundled with pysmi, for the modules every
real-world MIB ultimately depends on.

These are searched alongside the caller's own sources rather than only when
the caller has none: for a module bundled here, the newest MODULE-IDENTITY
revision wins, and the bundled copy takes it when the caller's copy is older,
undated, or absent. See :py:meth:`pysmi.compiler.MibCompiler.compile`.

``bundled_mibs.json`` beside this file records where each bundled module's
text comes from, and -- for the ones a later RFC replaced -- which module
took over. It ships inside the package rather than beside the maintainer
script that writes it, because the supersession it records is the answer to a
question consumers ask at runtime: an agent walking an old device answers with
OIDs whose module was obsoleted twenty years ago, and the caller wants the
module that defines them now.
"""

import importlib.resources
import json
from functools import cache
from typing import Any

#: The manifest, read from package data rather than the source tree, so an
#: installed wheel answers the same as a checkout.
_MANIFEST = "bundled_mibs.json"


@cache
def manifest() -> dict[str, dict[str, Any]]:
    """Every bundled module, mapped to its manifest entry."""
    text = (importlib.resources.files(__name__) / _MANIFEST).read_text()
    modules: dict[str, dict[str, Any]] = json.loads(text)["modules"]

    return modules


def successors(module: str) -> dict[str, str]:
    """The modules that replaced ``module``, keyed by the RFC that did it.

    Empty for a module still current, and for one pysmi does not bundle.
    """
    entry = manifest().get(module, {})
    reviewed: dict[str, str] = entry.get("successors_reviewed", {})

    return dict(reviewed)


def successor_for(module: str, oid: str | None = None) -> str | None:
    """The module that now defines ``oid``, where ``module`` used to.

    A module replaced whole has one successor and answers with it for any OID.
    RFC1213-MIB and its predecessor were not replaced whole: the RFC that
    obsoleted them split their subtrees across IF-MIB, IP-MIB, TCP-MIB,
    UDP-MIB and SNMPv2-MIB, so those entries carry a per-subtree map and the
    longest matching prefix answers. ``None`` where nothing took the subtree
    over -- ``egp`` and ``transmission`` have no successor to name.
    """
    entry = manifest().get(module)
    if entry is None:
        return None

    by_oid: dict[str, str] = entry.get("successors_by_oid", {})
    if by_oid:
        if oid is None:
            return None

        match = max(
            (prefix for prefix in by_oid if _covers(prefix, oid)),
            key=len,
            default=None,
        )

        return by_oid[match] if match is not None else None

    reviewed = entry.get("successors_reviewed", {})

    return next(iter(reviewed.values())) if len(reviewed) == 1 else None


def _covers(prefix: str, oid: str) -> bool:
    """Whether ``prefix`` names ``oid`` or a subtree containing it.

    Compared arc by arc rather than as text, so that 1.3.6.1.2.1.2 does not
    claim 1.3.6.1.2.1.22.
    """
    arcs = oid.split(".")
    want = prefix.split(".")

    return len(want) <= len(arcs) and arcs[: len(want)] == want
