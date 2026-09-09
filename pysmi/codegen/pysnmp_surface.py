#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""The pysnmp runtime API that a generated module calls.

pysnmp owns its loader contract and pysmi does not; the layering in
:doc:`/mibs-as-data` is explicit about it. What this module states is narrower
and is pysmi's own: which members of that contract
:py:class:`~pysmi.codegen.pysnmp.PySnmpCodeGen` writes into the source it
emits.

Until this was written the answer lived only in the generator's string
templates, and nothing read it back. The classes were at least named --
``symsTable`` maps each macro to the class it is emitted as, and
``constImports`` names the symbols every module imports whether it uses them or
not. The calls made on those classes were named nowhere, so their coverage was
whatever the specification tests happened to need: 19 of the 20 were asserted
somewhere, and ``setFixedLength`` was emitted for every fixed-size ``OCTET
STRING`` in the bundle without one test naming it.

Two things read this module, and between them they separate a defect that is
pysmi's from one that is not:

* ``tests/test_pysnmp_surface.py`` renders a corpus, reads every call back out
  of the emitted source and asserts the set matches this one exactly. A call
  added to the generator without an entry here fails, and an entry nothing
  emits fails too, so the declaration cannot drift from the generator in either
  direction. It imports no pysnmp, so it gates.
* The consumer smoke test resolves every name here against the installed
  pysnmp. Only that can see an upstream removal, and it names the member that
  went missing rather than failing somewhere inside a generated module. It does
  not gate, because an upstream removal is not a pysmi defect.

See pysnmp/pysmi#127 for why the second one cannot gate, and pysnmp/pysnmp#133
for the removal that motivated having the first.
"""

__all__ = [
    "BUILDER_MEMBERS",
    "NODE_METHODS",
    "VALUE_METHODS",
    "method_names",
]

#: Members of ``MibBuilder`` a generated module touches. ``importSymbols`` and
#: ``exportSymbols`` bracket every module; ``loadTexts`` is the attribute each
#: narrative setter is guarded by, and is read rather than called.
BUILDER_MEMBERS: dict[str, str] = {
    "importSymbols": "Binds the symbols a module imports, base classes included.",
    "exportSymbols": "Publishes what the module defines, at the end of the module.",
    "loadTexts": "Guards the narrative setters, which are skipped without it.",
}

#: Calls made on the MIB node classes, against the classes they are emitted on.
#: The receivers are the values of ``PySnmpCodeGen.symsTable``, which is what
#: makes this a statement about the generator rather than a second copy of it.
NODE_METHODS: dict[str, tuple[str, ...]] = {
    "setStatus": (
        "AgentCapabilities",
        "MibScalar",
        "MibTable",
        "MibTableColumn",
        "MibTableRow",
        "ModuleCompliance",
        "NotificationGroup",
        "NotificationType",
        "ObjectGroup",
        "ObjectIdentity",
    ),
    "setDescription": (
        "AgentCapabilities",
        "MibScalar",
        "MibTable",
        "MibTableColumn",
        "MibTableRow",
        "ModuleCompliance",
        "ModuleIdentity",
        "NotificationGroup",
        "NotificationType",
        "ObjectGroup",
        "ObjectIdentity",
    ),
    "setReference": (
        "AgentCapabilities",
        "MibScalar",
        "ModuleCompliance",
        "NotificationGroup",
        "NotificationType",
        "ObjectGroup",
        "ObjectIdentity",
    ),
    "setLabel": ("MibScalar",),
    "setMaxAccess": ("MibScalar", "MibTable", "MibTableColumn", "MibTableRow"),
    "setUnits": ("MibScalar",),
    "setIndexNames": ("MibTableRow",),
    "getIndexNames": ("MibTableRow",),
    "registerAugmentions": ("MibTableRow",),
    "setObjects": (
        "ModuleCompliance",
        "NotificationGroup",
        "NotificationType",
        "ObjectGroup",
    ),
    "setProductRelease": ("AgentCapabilities",),
    "setLastUpdated": ("ModuleIdentity",),
    "setOrganization": ("ModuleIdentity",),
    "setContactInfo": ("ModuleIdentity",),
    "setRevisions": ("ModuleIdentity",),
    "setRevisionsDescriptions": ("ModuleIdentity",),
}

#: Calls made on a value rather than on a node. Which class carries the value
#: is the MIB's choice, so these name base types rather than node classes, and
#: the types named are the ones the call has to work on rather than the whole
#: set it is ever emitted against: ``clone`` carries a DEFVAL and ``subtype``
#: applies a constraint, both on any syntax, while ``setFixedLength`` is
#: emitted only where a SIZE names a single length and so only for a string.
VALUE_METHODS: dict[str, tuple[str, ...]] = {
    "clone": ("Integer32", "OctetString"),
    "subtype": ("Integer32", "OctetString"),
    "setFixedLength": ("OctetString",),
}


def method_names() -> frozenset[str]:
    """Every method a generated module calls, node and value alike."""
    return frozenset(NODE_METHODS) | frozenset(VALUE_METHODS)
