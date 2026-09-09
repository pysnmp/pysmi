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

The manifest covers two directories in the repository, only one of which a
wheel carries. ``asn1/`` is the search path described above. ``future/`` holds
modules with the same provenance that nothing in the corpus needs -- see
:py:func:`future` -- and is neither searched nor installed. Both are in the
manifest because provenance and supersession are facts about a module rather
than about the directory it currently sits in, and because the manifest is
then still able to say that a module exists and where its text comes from,
which is the useful answer for one pysmi does not carry.
"""

import importlib.resources
import json
from functools import cache
from typing import Any

#: The manifest, read from package data rather than the source tree, so an
#: installed wheel answers the same as a checkout.
_MANIFEST = "bundled_mibs.json"


#: The manifest key marking an entry as held in ``future/``. Absent on an
#: entry in the search path, so the default is to be bundled and a promotion
#: is the removal of a key rather than the setting of one.
_FUTURE = "future"


@cache
def manifest() -> dict[str, dict[str, Any]]:
    """Every module the manifest covers, mapped to its manifest entry.

    Both directories: use :py:func:`bundled` or :py:func:`future` to tell
    which one a name is in.
    """
    text = (importlib.resources.files(__name__) / _MANIFEST).read_text()
    modules: dict[str, dict[str, Any]] = json.loads(text)["modules"]

    return modules


@cache
def bundled() -> frozenset[str]:
    """The modules in ``asn1/`` -- the ones an install carries and searches.

    This is what :py:func:`manifest` means for every question about the
    installed package: which modules are here, which the compiler adjudicates
    between sources for, which ``pysmi/mibs/pysnmp/`` holds a compiled form of.
    """
    return frozenset(
        name for name, entry in manifest().items() if entry.get("tier") != _FUTURE
    )


@cache
def future() -> frozenset[str]:
    """The modules the manifest describes but the package does not carry.

    Held in ``pysmi/mibs/future/`` in the repository: same provenance as a
    bundled module, but nothing in the corpus pysmi is built against imports
    one, so they are neither searched, nor compiled into the wheel, nor
    re-fetched by ``--check``. Any use is reason to promote one -- see
    ``pysmi/mibs/future/README.md``.

    The names ship even though the text does not, so a caller that finds one
    of these in an IMPORTS clause can be told the module is known and where
    its text comes from, rather than only that pysmi has no copy. Do not read
    a name here as a file the package can be asked for; it is not one.
    """
    return frozenset(
        name for name, entry in manifest().items() if entry.get("tier") == _FUTURE
    )


def successors(module: str) -> dict[str, str]:
    """The modules that replaced ``module``, keyed by the RFC that did it.

    Empty for a module still current, and for one pysmi does not bundle.

    **This is a statement about the module, not about any OID it defines.** A
    consumer ranking candidates for an OID must not read it as "demote this
    module here". Six of the sixteen recorded relations do not survive that
    reading: nine name a successor that redefines every OID the superseded
    module did, six name one that shares no OID with it at all -- the successor
    republished the material on a new arc, and the superseded module remains the
    only definition of the old one -- and one names a successor pysmi does not
    bundle, so nothing can be said about its coverage here. Demoting
    ``VRRP-MIB`` for ``1.3.6.1.2.1.68`` hands that arc to whatever else claims
    it, because ``VRRPV3-MIB`` does not.

    The split is clean -- a successor covers all of the predecessor's OIDs or
    none of them, never some -- and ``tests/test_mibs_manifest.py`` holds it
    that way, so a per-OID consumer has a safe rule available: demote only when
    the named successor is in the corpus *and* claims the same OID.

    :py:func:`successor_for` is the per-OID form. Where a module was split
    rather than replaced, its manifest entry carries ``successors_by_oid`` and
    that function answers from the longest matching prefix.

    One recorded successor, ``RFC1398-MIB``, is not bundled. A caller that
    resolves the name against the corpus must tolerate a miss.
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
