#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""IANA's ``smi-numbers`` registry: what the arcs under ``1.3.6.1`` are called.

:py:mod:`pysmi.corpus.index` ranks modules to decide which one owns an arc.
The rule is total and works for arcs a module actually registers. For the arcs
*above* those it has nothing good to choose from, so it picks whichever module
happened to mention the arc on its way to somewhere else. Measured against
pysnmp/mibs' index, ``1.3.6.1.6.3`` -- ``snmpModules`` -- is attributed to
``RAPID-CITY``, a Nortel enterprise MIB, and ``1.3`` and ``1.3.6`` to
``OCCAM-ETHERLIKE-MIB``. No ranking over MIB text can fix that, because the
fact is not in the MIB text.

It is published, though. This reads it, and
:py:mod:`pysmi.corpus.arcs` projects a corpus onto it.

Taken as an input, never fetched, never bundled, for the same reasons as
:py:mod:`pysmi.registry.pen`.

How an arc gets its name
------------------------

The file nests registries, and names arcs in three different places. They
disagree, so the order matters:

1. **A registry's own name for its own arc** -- the last component of the
   dotted name in its ``description``, as in
   ``iso.org.dod.internet.snmpv2.snmpModules (1.3.6.1.6.3)``. IANA naming that
   node directly, so it wins.
2. **A ``record`` in the parent registry** -- ``<value>2</value>``,
   ``<name>interfaces</name>``. What names an arc that has no registry of its
   own.
3. **A path component of some deeper registry's description.** What names
   ``1 iso``, ``1.3 org``, ``1.3.6 dod`` and ``1.3.6.1 internet``, which
   nothing else in the file names at all.

The order is not academic. ``1.3.6.1.6.3`` has a record calling it
``smnpModules``, which is a typo in IANA's own data; rule 1 gives
``snmpModules`` from the registry that arc actually is. And ``1.3.6.1.2.1.2``
has no registry of its own, so rule 2 gives ``interfaces`` rather than the
``interface`` a deeper description spells on its way past.

What it does not cover
----------------------

The arcs outside ``1.3.6.1``: ``0``, ``1.0``, ``1.2``, ``1.2.840``,
``1.3.111``, ``1.0.8802`` and what hangs under them. There is no feed for
those -- ITU-T's OID registry does not answer, and IEEE publishes landing
pages rather than data -- so :py:mod:`pysmi.registry.tree` carries them as a
cited table instead, visibly distinct from anything sourced from a registry.
"""

import re
from typing import Final, NamedTuple
from xml.etree import ElementTree

from pysmi import error

#: The XML namespace IANA publishes its assignments in.
NAMESPACE: Final = "{http://www.iana.org/assignments}"

#: Where the registry is published, and where a correction belongs.
AUTHORITY: Final = "https://www.iana.org/assignments/smi-numbers"

#: A registry ``description`` ends in the arc it covers, parenthesised and
#: sometimes with a trailing dot: ``iso.org.dod.internet.mgmt (1.3.6.1.2.)``.
_PREFIX: Final = re.compile(r"\(((?:\d+\.)*\d+)\.?\)")

#: How an arc came by its name, weakest first, so that a later source
#: replaces an earlier one.
_PATH: Final = 0
_RECORD: Final = 1
_OWN: Final = 2


class ArcName(NamedTuple):
    """What an arc is called, and who says so."""

    #: The arc, dotted decimal.
    arc: str

    #: What it is called.
    name: str

    #: The authority that says so, as a URL. A reader weighing one name
    #: against another needs to know which of them came from a registry.
    authority: str = AUTHORITY


def parse_smi_numbers(text: str) -> dict[str, ArcName]:
    """Read IANA's ``smi-numbers`` registry.

    Args:
        text: the XML file's contents, as IANA publishes it.

    Returns:
        The name per arc, for every arc the file names.

    Raises:
        PySmiError: the file is not the XML this reads.
    """
    try:
        # The stdlib parser over a file the operator of the build chose and
        # committed, which is not the threat model S314 is about: this is not
        # network content, and a corpus build reads nothing it was not pointed
        # at. Adding defusedxml for it would be a dependency for everyone.
        root = ElementTree.fromstring(text)  # noqa: S314

    except ElementTree.ParseError as exc:
        raise error.PySmiError(f"not an smi-numbers registry: {exc}") from exc

    # Strength per arc alongside the name, so a stronger source replaces a
    # weaker one whatever order the file happens to be walked in.
    found: dict[str, tuple[int, str]] = {}

    _walk(root, found)

    return {arc: ArcName(arc, name) for arc, (_strength, name) in sorted(found.items())}


def _walk(node: ElementTree.Element, found: dict[str, tuple[int, str]]) -> None:
    """Read one registry and the registries under it."""
    prefix = ""
    description = node.find(NAMESPACE + "description")

    if description is not None and description.text:
        flat = " ".join(description.text.split())
        matched = _PREFIX.search(flat)

        if matched:
            prefix = matched[1]
            labels = flat.split("(")[0].strip().split(".")
            arcs = prefix.split(".")

            # Only where the dotted name and the OID line up arc for arc. A
            # description that does not is prose rather than a path, and
            # zipping the two anyway would name arcs after the wrong thing.
            if len(labels) == len(arcs):
                _record(found, prefix, labels[-1], _OWN)

                for depth in range(len(arcs) - 1):
                    _record(found, ".".join(arcs[: depth + 1]), labels[depth], _PATH)

    if prefix:
        for entry in node.findall(NAMESPACE + "record"):
            value = entry.find(NAMESPACE + "value")
            name = entry.find(NAMESPACE + "name")

            if value is None or name is None or not value.text or not name.text:
                continue

            # A range -- "5-16" -- registers no single arc, so there is
            # nothing here to name.
            if value.text.strip().isdigit():
                _record(
                    found,
                    f"{prefix}.{value.text.strip()}",
                    name.text.strip(),
                    _RECORD,
                )

    for sub in node.findall(NAMESPACE + "registry"):
        _walk(sub, found)


def _record(
    found: dict[str, tuple[int, str]], arc: str, name: str, strength: int
) -> None:
    """Name an arc, unless something better already named it."""
    if not name:
        return

    standing = found.get(arc)

    if standing is None or standing[0] < strength:
        found[arc] = (strength, name)
