#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the code generators, and helpers common to them."""

import logging
from collections.abc import Sequence
from time import strftime, strptime
from typing import Any, ClassVar, Final, TypeAlias, TypeGuard

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)

_RFC1155_RFC1065_KEY: Final = "RFC1155-SMI/RFC1065-SMI"

# Shapes of the parse tree values handed to the clause handlers.
#
# A handler receives the already-converted children of one clause, never a raw
# parse node: prep_data walks depth first, so by the time a handler runs its
# children have been through their own handlers. The aliases below name the
# shapes that carry no further nesting, so they can be written down exactly.
# Clauses whose shape varies with the clause body stay `Any` for now; see
# https://github.com/pysnmp/pysmi/issues/47.

#: A clause carrying one piece of text, e.g. DESCRIPTION or STATUS. The text
#: is ``data[0]``.
TextClause: TypeAlias = Sequence[str]

#: A clause carrying a list of symbol names, e.g. OBJECTS or the names of a
#: BITS type. The names are ``data[0]``.
SymbolsClause: TypeAlias = Sequence[list[str]]

#: A clause carrying named numbers, e.g. BITS or an INTEGER enumeration. Each
#: pair is ``(name, number)`` and the pairs are ``data[0]``.
NamedNumbersClause: TypeAlias = Sequence[list[tuple[str, int]]]

#: An INDEX clause. Each entry is ``(implied, name)``, where ``implied`` is 1
#: for the IMPLIED column and 0 otherwise. The entries are ``data[0]``.
IndexClause: TypeAlias = Sequence[list[tuple[int, str]]]

#: A SEQUENCE clause. Each entry is ``(name, type)`` and the entries are
#: ``data[0]``.
SequenceClause: TypeAlias = Sequence[list[tuple[str, str]]]

#: An OBJECT IDENTIFIER value. ``data[0]`` is the sequence of sub-identifiers.
#: Each is a name still to be resolved, an arc written as a number, or the
#: ``name(number)`` form, which the grammar keeps as ``(name, number)`` without
#: defining the name in this module.
OidClause: TypeAlias = Sequence[list[str | int | tuple[str, int]]]

#: A DEFVAL clause. ``data[0]`` is the default: an int for an integer, a list
#: of bit names for BITS, and a string for everything else -- an enumeration
#: label, an OID, or a quoted hex or binary literal. The pysnmp and JSON
#: generators reach the handler from gen_object_type whether or not the object
#: declares a default, so those two accept ``DefValClause | None``.
DefValClause: TypeAlias = Sequence[str] | Sequence[int] | Sequence[list[str]]

#: A REVISION clause. Each entry is ``(timestamp, (kind, text))``, and the
#: entries are ``data[0]``.
RevisionsClause: TypeAlias = Sequence[list[tuple[str, tuple[str, str]]]]

#: A GROUP or OBJECT sub-clause of a MODULE-COMPLIANCE, tagged by which it is.
#: A GROUP carries ``(tag, name, description)``. An OBJECT carries
#: ``(tag, name, syntax, writeSyntax, minAccess, description)``, where the
#: three refinements are ``None`` when the sub-clause leaves them out and are
#: unconverted parse subtrees otherwise.
ComplianceRefinement: TypeAlias = tuple[Any, ...]

#: The MODULE clauses of a MODULE-COMPLIANCE. Each entry is
#: ``(module, groups, (mandatoryGroups, refinements))``; ``module`` is ``None``
#: where the clause leaves the module name out, meaning the one being defined.
#: ``groups`` holds the names from MANDATORY-GROUPS and GROUP, which is what a
#: compliance requires. The third element carries the detail those names lose:
#: which of them were mandatory, and the GROUP and OBJECT sub-clauses in full.
ComplianceClause: TypeAlias = Sequence[list[tuple[str | None, list[str], tuple[list[str], list[ComplianceRefinement]]]]]

#: A VARIATION sub-clause of an AGENT-CAPABILITIES SUPPORTS clause, as
#: ``(name, syntax, writeSyntax, access, creationRequires, defVal,
#: description)``. Everything but the name and the description is ``None``
#: when the sub-clause leaves it out; the syntaxes are unconverted parse
#: subtrees, as in a compliance refinement.
CapabilitiesVariation: TypeAlias = tuple[Any, ...]

#: The SUPPORTS clauses of an AGENT-CAPABILITIES. Each entry is
#: ``(module, groups, variations)``: the module named by SUPPORTS, the group
#: names its INCLUDES lists, and the VARIATION sub-clauses that qualify them.
CapabilitiesClause: TypeAlias = Sequence[list[tuple[str, list[str], list[CapabilitiesVariation]]]]

#: The clauses below are the top-level ones: what a handler registered in
#: ``handlersTable`` against a whole macro receives. Every backend gets the
#: same number of fields in the same order -- that much comes from the
#: grammar -- so the arity and the field order can be written down and
#: checked. A field's *type* is whatever that backend's own sub-handler
#: returned for it, and for several of them the three backends legitimately
#: disagree (pysnmp renders a string, JSON builds a document, the symbol
#: table keeps a name), so those stay `Any` rather than claim a precision
#: that is not there. See https://github.com/pysnmp/pysmi/issues/47.

#: ``(name, productRelease, status, description, reference, capabilities, oid)``
AgentCapabilitiesClause: TypeAlias = tuple[str, str, str, str, str | None, Any, tuple[Any, ...]]

#: ``(name, lastUpdated, organization, contactInfo, description, revisions, oid)``
ModuleIdentityClause: TypeAlias = tuple[str, str, str, str, str, Any, tuple[Any, ...]]

#: ``(name, status, description, reference, compliances, oid)``
ModuleComplianceClause: TypeAlias = tuple[str, str, str, str | None, Any, tuple[Any, ...]]

#: ``(name, objects, status, description, reference, oid)``
NotificationGroupClause: TypeAlias = tuple[str, Any, str, str, str | None, tuple[Any, ...]]

#: ``(name, objects, status, description, reference, oid)``
NotificationTypeClause: TypeAlias = tuple[str, Any, str, str, str | None, tuple[Any, ...]]

#: ``(name, objects, status, description, reference, oid)``
ObjectGroupClause: TypeAlias = tuple[str, Any, str, str, str | None, tuple[Any, ...]]

#: ``(name, status, description, reference, oid)``
ObjectIdentityClause: TypeAlias = tuple[str, str, str, str | None, tuple[Any, ...]]

#: ``(name, syntax, units, maxaccess, status, description, reference,
#: augmentation, index, defval, oid)``. SMIv1 leaves DESCRIPTION optional, so
#: the description is ``None`` for an SMIv1 object that omits it.
ObjectTypeClause: TypeAlias = tuple[
    str, tuple[Any, ...], str | None, str, str, str | None, str | None, Any, Any, Any, tuple[Any, ...]
]

#: ``(name, enterprise, variables, description, reference, value)``. RFC 1215
#: leaves DESCRIPTION and REFERENCE optional.
TrapTypeClause: TypeAlias = tuple[str, tuple[Any, ...], Any, str | None, str | None, int]

#: ``(name, declaration)``, where the declaration is the converted right-hand
#: side of the type assignment, or ``None`` for a bare type reference.
TypeDeclarationClause: TypeAlias = tuple[str, Any]

#: ``(name, oid)``
ValueDeclarationClause: TypeAlias = tuple[str, tuple[Any, ...]]


#: A bound in a range or size constraint. The lexer turns a decimal into an
#: int; a hex or binary literal reaches the generator as the literal text.
Bound: TypeAlias = int | str

#: RFC 3418's ``snmp`` group, ``{ mib-2 11 }``. RFC 1215 section 2.1.5 gives a
#: TRAP-TYPE naming this enterprise a different meaning: its value goes in the
#: generic-trap field rather than the enterprise-specific one.
SNMP_ENTERPRISE: tuple[int, ...] = (1, 3, 6, 1, 2, 1, 11)

#: RFC 3418's ``snmpTraps``, under which the six generic traps are numbered
#: from one.
SNMP_TRAPS: tuple[int, ...] = (1, 3, 6, 1, 6, 3, 1, 1, 5)

#: The generic traps RFC 3584 section 3.1 gives a mapping for: coldStart(0)
#: through egpNeighborLoss(5).
GENERIC_TRAPS = range(6)


def trap_type_oid(enterprise: tuple[int, ...], value: int) -> tuple[int, ...]:
    """Give an SMIv1 trap the OID its SMIv2 notification is known by.

    RFC 3584 section 2.1.2 (5) builds that OID from the ENTERPRISE clause, a
    zero, and the trap number -- except where the ENTERPRISE is ``snmp``. Those
    are the six generic traps, and section 3.1 maps them onto ``snmpTraps``,
    numbered from one rather than from zero.

    A trap that names ``snmp`` but numbers itself past those six is described
    by neither RFC; RFC 1215 section 2.1.5 says the convention "is not intended
    to provide a means to define additional standard SNMP traps". Rather than
    reject it or invent an OID under ``snmpTraps`` that names nothing, it keeps
    the enterprise-specific form it would have had.

    Args:
        enterprise: the ENTERPRISE clause as sub-identifiers
        value: the value of the TRAP-TYPE invocation

    Returns:
        The notification's OID as sub-identifiers.
    """
    if tuple(enterprise) == SNMP_ENTERPRISE and value in GENERIC_TRAPS:
        return (*SNMP_TRAPS, value + 1)

    return (*enterprise, 0, value)


#: How a timestamp is rendered once read. Both clauses carrying an ExtUTCTime --
#: LAST-UPDATED and REVISION -- are rendered this way, so a consumer has one
#: format to read rather than one per clause.
EXT_UTC_TIME_FORMAT: Final = "%Y-%m-%d %H:%M"

#: What a timestamp that cannot be read is rendered as.
EPOCH_TIMESTAMP: Final = "1970-01-01 00:00"


def format_ext_utc_time(timeStr: str, module: str = "") -> str:
    """Render one ExtUTCTime value.

    RFC 2578 section 2 defines ``ExtUTCTime ::= OCTET STRING(SIZE(11 | 13))``,
    written ``YYMMDDHHMMZ`` or ``YYYYMMDDHHMMZ``, and restricts the two-digit
    year to 1900-1999. Both forms are read; the short one is expanded.

    A value that cannot be read at all is replaced with the epoch rather than
    rejected, because a wrong date is common in MIBs found in the wild and never
    changes what a module means. The substitution is logged, so a value that was
    invented is distinguishable from one the module really carries. Turn it on
    with ``mibdump --debug codegen`` or by configuring the ``pysmi.codegen``
    logger.

    Args:
        timeStr: the timestamp as written in the MIB
        module: name of the module it was written in, for the log message

    Returns:
        The formatted date, or the epoch if the value could not be read.
    """
    written = timeStr

    if len(timeStr) == 11:
        timeStr = "19" + timeStr

    try:
        return strftime(EXT_UTC_TIME_FORMAT, strptime(timeStr, "%Y%m%d%H%MZ"))

    except ValueError:
        logger.warning(
            "%s: cannot read the timestamp %r, rendering it as %s",
            module or "<unknown module>",
            written,
            EPOCH_TIMESTAMP,
            extra={"mibModule": module, "timestamp": written},
        )
        return EPOCH_TIMESTAMP


#: A range or SIZE constraint. Each entry is ``(low, high)``, or ``(value,)``
#: where a single value is permitted rather than a span. The entries are
#: ``data[0]``. Ranges and sizes share the grammar's ``ranges`` production, so
#: the two constraints carry the same shape.
RangesClause: TypeAlias = Sequence[list[tuple[Bound] | tuple[Bound, Bound]]]


#: Every symbol the SMIv2 base modules export, mapped to the module that
#: exports it.
#:
#: Taken from the module definitions themselves: SNMPv2-SMI in RFC 2578
#: Section 2, SNMPv2-TC in RFC 2579 Section 2, SNMPv2-CONF in RFC 2580
#: Section 2. RFC 2578 Section 3.2 requires a module to name in IMPORTS every
#: symbol it refers to and does not define; many vendor MIBs do not, and this
#: is the table :py:meth:`~pysmi.codegen.symtable.SymtableCodeGen.gen_code`
#: repairs such a module from when asked to.
#:
#: Only these three modules are here. A symbol out of SNMPv2-MIB or any other
#: compiled module is not repairable this way: supplying its import would add
#: a compilation dependency the module never declared.
SMI_BASE_EXPORTS: Final[dict[str, str]] = {
    # RFC 2578 -- macros
    "MODULE-IDENTITY": "SNMPv2-SMI",
    "OBJECT-IDENTITY": "SNMPv2-SMI",
    "OBJECT-TYPE": "SNMPv2-SMI",
    "NOTIFICATION-TYPE": "SNMPv2-SMI",
    # RFC 2578 -- types
    "Integer32": "SNMPv2-SMI",
    "IpAddress": "SNMPv2-SMI",
    "Counter32": "SNMPv2-SMI",
    "Gauge32": "SNMPv2-SMI",
    "Unsigned32": "SNMPv2-SMI",
    "TimeTicks": "SNMPv2-SMI",
    "Opaque": "SNMPv2-SMI",
    "Counter64": "SNMPv2-SMI",
    "ObjectName": "SNMPv2-SMI",
    "NotificationName": "SNMPv2-SMI",
    "ObjectSyntax": "SNMPv2-SMI",
    "SimpleSyntax": "SNMPv2-SMI",
    "ApplicationSyntax": "SNMPv2-SMI",
    # RFC 2578 -- the registration tree
    "org": "SNMPv2-SMI",
    "dod": "SNMPv2-SMI",
    "internet": "SNMPv2-SMI",
    "directory": "SNMPv2-SMI",
    "mgmt": "SNMPv2-SMI",
    "mib-2": "SNMPv2-SMI",
    "transmission": "SNMPv2-SMI",
    "experimental": "SNMPv2-SMI",
    "private": "SNMPv2-SMI",
    "enterprises": "SNMPv2-SMI",
    "security": "SNMPv2-SMI",
    "snmpV2": "SNMPv2-SMI",
    "snmpDomains": "SNMPv2-SMI",
    "snmpProxys": "SNMPv2-SMI",
    "snmpModules": "SNMPv2-SMI",
    "zeroDotZero": "SNMPv2-SMI",
    # RFC 2579
    "TEXTUAL-CONVENTION": "SNMPv2-TC",
    "DisplayString": "SNMPv2-TC",
    "PhysAddress": "SNMPv2-TC",
    "MacAddress": "SNMPv2-TC",
    "TruthValue": "SNMPv2-TC",
    "TestAndIncr": "SNMPv2-TC",
    "AutonomousType": "SNMPv2-TC",
    "InstancePointer": "SNMPv2-TC",
    "VariablePointer": "SNMPv2-TC",
    "RowPointer": "SNMPv2-TC",
    "RowStatus": "SNMPv2-TC",
    "TimeStamp": "SNMPv2-TC",
    "TimeInterval": "SNMPv2-TC",
    "DateAndTime": "SNMPv2-TC",
    "StorageType": "SNMPv2-TC",
    "TDomain": "SNMPv2-TC",
    "TAddress": "SNMPv2-TC",
    # RFC 2580
    "OBJECT-GROUP": "SNMPv2-CONF",
    "NOTIFICATION-GROUP": "SNMPv2-CONF",
    "MODULE-COMPLIANCE": "SNMPv2-CONF",
    "AGENT-CAPABILITIES": "SNMPv2-CONF",
}

#: Key under which the symbol table records what
#: :py:meth:`~pysmi.codegen.symtable.SymtableCodeGen.gen_code` repaired, so
#: that the backend rendering the same module imports the symbols too.
REPAIRED_IMPORTS_KEY: Final = "_symtable_repaired"


def with_repaired_imports(imports: Any, symbolTable: dict[str, Any], moduleName: str) -> dict[str, list[str]]:
    """Copy *imports*, adding back whatever the symbol table had to repair.

    The symbol table is built first and is where a missing IMPORTS entry is
    detected, but the backend that renders the module resolves imports again
    from the same parse tree. Without this the repair would be invisible to it
    and the rendered module would refer to a symbol it never imported.

    Args:
        imports: the module's IMPORTS clause, as parsed; may be ``None``
        symbolTable: symbols of this module and everything it imports
        moduleName: the module being rendered

    Returns:
        A fresh imports mapping, safe to mutate.
    """
    repaired = dict(imports or {})
    for module, symbols in repaired.items():
        repaired[module] = list(symbols)

    for symbol, module in symbolTable.get(moduleName, {}).get(REPAIRED_IMPORTS_KEY, {}).items():
        repaired.setdefault(module, []).append(symbol)

    return repaired


def dorepr(s: Any) -> str:
    """Render a value as a Python literal for embedding in generated code."""
    return repr(s)


def updateDict(d1: dict[Any, Any], d2: Any) -> dict[Any, Any]:
    """Merge *d2* into *d1* and return *d1*.

    Same as :py:meth:`dict.update` but returns the dictionary, so class-level
    tables can be built from a base table in a single expression.
    """
    d1.update(d2)
    return d1


@deprecated_camel_case
class AbstractCodeGen:
    """Base class for code generators.

    A code generator walks the parse tree of one MIB module and renders it in
    some target form -- pysnmp Python source, JSON, or nothing at all. It also
    keeps the tables describing which modules are supplied by the target
    implementation rather than compiled, and how SMI base types map onto it.

    Subclasses implement :py:meth:`gen_code` and :py:meth:`gen_index`.
    """

    # never compile these, they either:
    # - define MACROs (implementation supplies them)
    # - or carry conflicting OIDs (so that all IMPORT's of them will be rewritten)
    # - or have manual fixes
    # - or import base ASN.1 types from implementation-specific MIBs
    baseMibs: ClassVar[tuple[str, ...]] = (
        "RFC1065-SMI",
        "RFC1155-SMI",
        "RFC1158-MIB",
        "RFC-1212",
        "RFC1213-MIB",
        "RFC-1215",
        "SNMPv2-SMI",
        "SNMPv2-TC",
        "SNMPv2-TM",
        "SNMPv2-CONF",
    )

    # Explicit SMIv1 -> SMIv2 mapping for standard MIBs
    commonSyms = {
        _RFC1155_RFC1065_KEY: {
            "internet": [("SNMPv2-SMI", "internet")],
            "directory": [("SNMPv2-SMI", "directory")],
            "mgmt": [("SNMPv2-SMI", "mgmt")],
            "experimental": [("SNMPv2-SMI", "experimental")],
            "private": [("SNMPv2-SMI", "private")],
            "enterprises": [("SNMPv2-SMI", "enterprises")],
            "OBJECT-TYPE": [("SNMPv2-SMI", "OBJECT-TYPE")],
            "ObjectName": [("SNMPv2-SMI", "ObjectName")],
            "ObjectSyntax": [("SNMPv2-SMI", "ObjectSyntax")],
            "SimpleSyntax": [("SNMPv2-SMI", "SimpleSyntax")],
            "ApplicationSyntax": [("SNMPv2-SMI", "ApplicationSyntax")],
            "NetworkAddress": [("SNMPv2-SMI", "IpAddress")],
            "IpAddress": [("SNMPv2-SMI", "IpAddress")],
            "Counter": [("SNMPv2-SMI", "Counter32")],
            "Gauge": [("SNMPv2-SMI", "Gauge32")],
            "TimeTicks": [("SNMPv2-SMI", "TimeTicks")],
            "Opaque": [("SNMPv2-SMI", "Opaque")],
        },
        "RFC1158-MIB/RFC1213-MIB": {
            "mib-2": [("SNMPv2-SMI", "mib-2")],
            "DisplayString": [("SNMPv2-TC", "DisplayString")],
            "system": [("SNMPv2-MIB", "system")],
            "interfaces": [("IF-MIB", "interfaces")],
            "ip": [("IP-MIB", "ip")],
            "icmp": [("IP-MIB", "icmp")],
            "tcp": [("TCP-MIB", "tcp")],
            "udp": [("UDP-MIB", "udp")],
            "transmission": [("SNMPv2-SMI", "transmission")],
            "snmp": [("SNMPv2-MIB", "snmp")],
            "sysDescr": [("SNMPv2-MIB", "sysDescr")],
            "sysObjectID": [("SNMPv2-MIB", "sysObjectID")],
            "sysUpTime": [("SNMPv2-MIB", "sysUpTime")],
            "sysContact": [("SNMPv2-MIB", "sysContact")],
            "sysName": [("SNMPv2-MIB", "sysName")],
            "sysLocation": [("SNMPv2-MIB", "sysLocation")],
            "sysServices": [("SNMPv2-MIB", "sysServices")],
            "ifNumber": [("IF-MIB", "ifNumber")],
            "ifTable": [("IF-MIB", "ifTable")],
            "ifEntry": [("IF-MIB", "ifEntry")],
            "ifIndex": [("IF-MIB", "ifIndex")],
            "ifDescr": [("IF-MIB", "ifDescr")],
            "ifType": [("IF-MIB", "ifType")],
            "ifMtu": [("IF-MIB", "ifMtu")],
            "ifSpeed": [("IF-MIB", "ifSpeed")],
            "ifPhysAddress": [("IF-MIB", "ifPhysAddress")],
            "ifAdminStatus": [("IF-MIB", "ifAdminStatus")],
            "ifOperStatus": [("IF-MIB", "ifOperStatus")],
            "ifLastChange": [("IF-MIB", "ifLastChange")],
            "ifInOctets": [("IF-MIB", "ifInOctets")],
            "ifInUcastPkts": [("IF-MIB", "ifInUcastPkts")],
            "ifInNUcastPkts": [("IF-MIB", "ifInNUcastPkts")],
            "ifInDiscards": [("IF-MIB", "ifInDiscards")],
            "ifInErrors": [("IF-MIB", "ifInErrors")],
            "ifInUnknownProtos": [("IF-MIB", "ifInUnknownProtos")],
            "ifOutOctets": [("IF-MIB", "ifOutOctets")],
            "ifOutUcastPkts": [("IF-MIB", "ifOutUcastPkts")],
            "ifOutNUcastPkts": [("IF-MIB", "ifOutNUcastPkts")],
            "ifOutDiscards": [("IF-MIB", "ifOutDiscards")],
            "ifOutErrors": [("IF-MIB", "ifOutErrors")],
            "ifOutQLen": [("IF-MIB", "ifOutQLen")],
            "ifSpecific": [("IF-MIB", "ifSpecific")],
            "ipForwarding": [("IP-MIB", "ipForwarding")],
            "ipDefaultTTL": [("IP-MIB", "ipDefaultTTL")],
            "ipInReceives": [("IP-MIB", "ipInReceives")],
            "ipInHdrErrors": [("IP-MIB", "ipInHdrErrors")],
            "ipInAddrErrors": [("IP-MIB", "ipInAddrErrors")],
            "ipForwDatagrams": [("IP-MIB", "ipForwDatagrams")],
            "ipInUnknownProtos": [("IP-MIB", "ipInUnknownProtos")],
            "ipInDiscards": [("IP-MIB", "ipInDiscards")],
            "ipInDelivers": [("IP-MIB", "ipInDelivers")],
            "ipOutRequests": [("IP-MIB", "ipOutRequests")],
            "ipOutDiscards": [("IP-MIB", "ipOutDiscards")],
            "ipOutNoRoutes": [("IP-MIB", "ipOutNoRoutes")],
            "ipReasmTimeout": [("IP-MIB", "ipReasmTimeout")],
            "ipReasmReqds": [("IP-MIB", "ipReasmReqds")],
            "ipReasmOKs": [("IP-MIB", "ipReasmOKs")],
            "ipReasmFails": [("IP-MIB", "ipReasmFails")],
            "ipFragOKs": [("IP-MIB", "ipFragOKs")],
            "ipFragFails": [("IP-MIB", "ipFragFails")],
            "ipFragCreates": [("IP-MIB", "ipFragCreates")],
            "ipAddrTable": [("IP-MIB", "ipAddrTable")],
            "ipAddrEntry": [("IP-MIB", "ipAddrEntry")],
            "ipAdEntAddr": [("IP-MIB", "ipAdEntAddr")],
            "ipAdEntIfIndex": [("IP-MIB", "ipAdEntIfIndex")],
            "ipAdEntNetMask": [("IP-MIB", "ipAdEntNetMask")],
            "ipAdEntBcastAddr": [("IP-MIB", "ipAdEntBcastAddr")],
            "ipAdEntReasmMaxSize": [("IP-MIB", "ipAdEntReasmMaxSize")],
            "ipNetToMediaTable": [("IP-MIB", "ipNetToMediaTable")],
            "ipNetToMediaEntry": [("IP-MIB", "ipNetToMediaEntry")],
            "ipNetToMediaIfIndex": [("IP-MIB", "ipNetToMediaIfIndex")],
            "ipNetToMediaPhysAddress": [("IP-MIB", "ipNetToMediaPhysAddress")],
            "ipNetToMediaNetAddress": [("IP-MIB", "ipNetToMediaNetAddress")],
            "ipNetToMediaType": [("IP-MIB", "ipNetToMediaType")],
            "icmpInMsgs": [("IP-MIB", "icmpInMsgs")],
            "icmpInErrors": [("IP-MIB", "icmpInErrors")],
            "icmpInDestUnreachs": [("IP-MIB", "icmpInDestUnreachs")],
            "icmpInTimeExcds": [("IP-MIB", "icmpInTimeExcds")],
            "icmpInParmProbs": [("IP-MIB", "icmpInParmProbs")],
            "icmpInSrcQuenchs": [("IP-MIB", "icmpInSrcQuenchs")],
            "icmpInRedirects": [("IP-MIB", "icmpInRedirects")],
            "icmpInEchos": [("IP-MIB", "icmpInEchos")],
            "icmpInEchoReps": [("IP-MIB", "icmpInEchoReps")],
            "icmpInTimestamps": [("IP-MIB", "icmpInTimestamps")],
            "icmpInTimestampReps": [("IP-MIB", "icmpInTimestampReps")],
            "icmpInAddrMasks": [("IP-MIB", "icmpInAddrMasks")],
            "icmpInAddrMaskReps": [("IP-MIB", "icmpInAddrMaskReps")],
            "icmpOutMsgs": [("IP-MIB", "icmpOutMsgs")],
            "icmpOutErrors": [("IP-MIB", "icmpOutErrors")],
            "icmpOutDestUnreachs": [("IP-MIB", "icmpOutDestUnreachs")],
            "icmpOutTimeExcds": [("IP-MIB", "icmpOutTimeExcds")],
            "icmpOutParmProbs": [("IP-MIB", "icmpOutParmProbs")],
            "icmpOutSrcQuenchs": [("IP-MIB", "icmpOutSrcQuenchs")],
            "icmpOutRedirects": [("IP-MIB", "icmpOutRedirects")],
            "icmpOutEchos": [("IP-MIB", "icmpOutEchos")],
            "icmpOutEchoReps": [("IP-MIB", "icmpOutEchoReps")],
            "icmpOutTimestamps": [("IP-MIB", "icmpOutTimestamps")],
            "icmpOutTimestampReps": [("IP-MIB", "icmpOutTimestampReps")],
            "icmpOutAddrMasks": [("IP-MIB", "icmpOutAddrMasks")],
            "icmpOutAddrMaskReps": [("IP-MIB", "icmpOutAddrMaskReps")],
            "tcpRtoAlgorithm": [("TCP-MIB", "tcpRtoAlgorithm")],
            "tcpRtoMin": [("TCP-MIB", "tcpRtoMin")],
            "tcpRtoMax": [("TCP-MIB", "tcpRtoMax")],
            "tcpMaxConn": [("TCP-MIB", "tcpMaxConn")],
            "tcpActiveOpens": [("TCP-MIB", "tcpActiveOpens")],
            "tcpPassiveOpens": [("TCP-MIB", "tcpPassiveOpens")],
            "tcpAttemptFails": [("TCP-MIB", "tcpAttemptFails")],
            "tcpEstabResets": [("TCP-MIB", "tcpEstabResets")],
            "tcpCurrEstab": [("TCP-MIB", "tcpCurrEstab")],
            "tcpInSegs": [("TCP-MIB", "tcpInSegs")],
            "tcpOutSegs": [("TCP-MIB", "tcpOutSegs")],
            "tcpRetransSegs": [("TCP-MIB", "tcpRetransSegs")],
            "tcpConnTable": [("TCP-MIB", "tcpConnTable")],
            "tcpConnEntry": [("TCP-MIB", "tcpConnEntry")],
            "tcpConnState": [("TCP-MIB", "tcpConnState")],
            "tcpConnLocalAddress": [("TCP-MIB", "tcpConnLocalAddress")],
            "tcpConnLocalPort": [("TCP-MIB", "tcpConnLocalPort")],
            "tcpConnRemAddress": [("TCP-MIB", "tcpConnRemAddress")],
            "tcpConnRemPort": [("TCP-MIB", "tcpConnRemPort")],
            "tcpInErrs": [("TCP-MIB", "tcpInErrs")],
            "tcpOutRsts": [("TCP-MIB", "tcpOutRsts")],
            "udpInDatagrams": [("UDP-MIB", "udpInDatagrams")],
            "udpNoPorts": [("UDP-MIB", "udpNoPorts")],
            "udpInErrors": [("UDP-MIB", "udpInErrors")],
            "udpOutDatagrams": [("UDP-MIB", "udpOutDatagrams")],
            "udpTable": [("UDP-MIB", "udpTable")],
            "udpEntry": [("UDP-MIB", "udpEntry")],
            "udpLocalAddress": [("UDP-MIB", "udpLocalAddress")],
            "udpLocalPort": [("UDP-MIB", "udpLocalPort")],
            "snmpInPkts": [("SNMPv2-MIB", "snmpInPkts")],
            "snmpOutPkts": [("SNMPv2-MIB", "snmpOutPkts")],
            "snmpInBadVersions": [("SNMPv2-MIB", "snmpInBadVersions")],
            "snmpInBadCommunityNames": [("SNMPv2-MIB", "snmpInBadCommunityNames")],
            "snmpInBadCommunityUses": [("SNMPv2-MIB", "snmpInBadCommunityUses")],
            "snmpInASNParseErrs": [("SNMPv2-MIB", "snmpInASNParseErrs")],
            "snmpInTooBigs": [("SNMPv2-MIB", "snmpInTooBigs")],
            "snmpInNoSuchNames": [("SNMPv2-MIB", "snmpInNoSuchNames")],
            "snmpInBadValues": [("SNMPv2-MIB", "snmpInBadValues")],
            "snmpInReadOnlys": [("SNMPv2-MIB", "snmpInReadOnlys")],
            "snmpInGenErrs": [("SNMPv2-MIB", "snmpInGenErrs")],
            "snmpInTotalReqVars": [("SNMPv2-MIB", "snmpInTotalReqVars")],
            "snmpInTotalSetVars": [("SNMPv2-MIB", "snmpInTotalSetVars")],
            "snmpInGetRequests": [("SNMPv2-MIB", "snmpInGetRequests")],
            "snmpInGetNexts": [("SNMPv2-MIB", "snmpInGetNexts")],
            "snmpInSetRequests": [("SNMPv2-MIB", "snmpInSetRequests")],
            "snmpInGetResponses": [("SNMPv2-MIB", "snmpInGetResponses")],
            "snmpInTraps": [("SNMPv2-MIB", "snmpInTraps")],
            "snmpOutTooBigs": [("SNMPv2-MIB", "snmpOutTooBigs")],
            "snmpOutNoSuchNames": [("SNMPv2-MIB", "snmpOutNoSuchNames")],
            "snmpOutBadValues": [("SNMPv2-MIB", "snmpOutBadValues")],
            "snmpOutGenErrs": [("SNMPv2-MIB", "snmpOutGenErrs")],
            "snmpOutGetRequests": [("SNMPv2-MIB", "snmpOutGetRequests")],
            "snmpOutGetNexts": [("SNMPv2-MIB", "snmpOutGetNexts")],
            "snmpOutSetRequests": [("SNMPv2-MIB", "snmpOutSetRequests")],
            "snmpOutGetResponses": [("SNMPv2-MIB", "snmpOutGetResponses")],
            "snmpOutTraps": [("SNMPv2-MIB", "snmpOutTraps")],
            "snmpEnableAuthenTraps": [("SNMPv2-MIB", "snmpEnableAuthenTraps")],
        },
    }

    convertImportv2 = {
        "RFC1065-SMI": commonSyms[_RFC1155_RFC1065_KEY],
        "RFC1155-SMI": commonSyms[_RFC1155_RFC1065_KEY],
        "RFC1158-MIB": updateDict(
            dict(commonSyms[_RFC1155_RFC1065_KEY]),
            (
                ("nullSpecific", [("SNMPv2-SMI", "zeroDotZero")]),
                ("ipRoutingTable", [("RFC1213-MIB", "ipRouteTable")]),
                ("ipRouteEntry", [("RFC1213-MIB", "ipRouteEntry")]),
                ("ipRouteDest", [("RFC1213-MIB", "ipRouteDest")]),
                ("ipRouteIfIndex", [("RFC1213-MIB", "ipRouteIfIndex")]),
                ("ipRouteMetric1", [("RFC1213-MIB", "ipRouteMetric1")]),
                ("ipRouteMetric2", [("RFC1213-MIB", "ipRouteMetric2")]),
                ("ipRouteMetric3", [("RFC1213-MIB", "ipRouteMetric3")]),
                ("ipRouteMetric4", [("RFC1213-MIB", "ipRouteMetric4")]),
                ("ipRouteNextHop", [("RFC1213-MIB", "ipRouteNextHop")]),
                ("ipRouteType", [("RFC1213-MIB", "ipRouteType")]),
                ("ipRouteProto", [("RFC1213-MIB", "ipRouteProto")]),
                ("ipRouteAge", [("RFC1213-MIB", "ipRouteAge")]),
                ("ipRouteMask", [("RFC1213-MIB", "ipRouteMask")]),
                ("egpInMsgs", [("RFC1213-MIB", "egpInMsgs")]),
                ("egpInErrors", [("RFC1213-MIB", "egpInErrors")]),
                ("egpOutMsgs", [("RFC1213-MIB", "egpOutMsgs")]),
                ("egpOutErrors", [("RFC1213-MIB", "egpOutErrors")]),
                ("egpNeighTable", [("RFC1213-MIB", "egpNeighTable")]),
                ("egpNeighEntry", [("RFC1213-MIB", "egpNeighEntry")]),
                ("egpNeighState", [("RFC1213-MIB", "egpNeighState")]),
                ("egpNeighAddr", [("RFC1213-MIB", "egpNeighAddr")]),
                ("egpNeighAs", [("RFC1213-MIB", "egpNeighAs")]),
                ("egpNeighInMsgs", [("RFC1213-MIB", "egpNeighInMsgs")]),
                ("egpNeighInErrs", [("RFC1213-MIB", "egpNeighInErrs")]),
                ("egpNeighOutMsgs", [("RFC1213-MIB", "egpNeighOutMsgs")]),
                ("egpNeighOutErrs", [("RFC1213-MIB", "egpNeighOutErrs")]),
                ("egpNeighInErrMsgs", [("RFC1213-MIB", "egpNeighInErrMsgs")]),
                ("egpNeighOutErrMsgs", [("RFC1213-MIB", "egpNeighOutErrMsgs")]),
                ("egpNeighStateUps", [("RFC1213-MIB", "egpNeighStateUps")]),
                ("egpNeighStateDowns", [("RFC1213-MIB", "egpNeighStateDowns")]),
                ("egpNeighIntervalHello", [("RFC1213-MIB", "egpNeighIntervalHello")]),
                ("egpNeighIntervalPoll", [("RFC1213-MIB", "egpNeighIntervalPoll")]),
                ("egpNeighMode", [("RFC1213-MIB", "egpNeighMode")]),
                ("egpNeighEventTrigger", [("RFC1213-MIB", "egpNeighEventTrigger")]),
                ("egpAs", [("RFC1213-MIB", "egpAs")]),
                ("snmpEnableAuthTraps", [("SNMPv2-MIB", "snmpEnableAuthenTraps")]),
            ),
        ),
        "RFC-1212": {"OBJECT-TYPE": [("SNMPv2-SMI", "OBJECT-TYPE")]},
        # XXX 'IndexSyntax': ???
        "RFC1213-MIB": updateDict(
            dict(commonSyms["RFC1158-MIB/RFC1213-MIB"]), (("PhysAddress", [("SNMPv2-TC", "PhysAddress")]),)
        ),
        "RFC-1215": {"TRAP-TYPE": [("SNMPv2-SMI", "TRAP-TYPE")]},
    }

    def gen_code(self, ast: Any, symbolTable: dict[str, Any], **kwargs: Any) -> tuple[MibInfo, Any]:
        """Render one parsed MIB module.

        Args:
            ast: parse tree of a single module, as produced by a parser
            symbolTable: symbols of this module and everything it imports,
                as built by :py:class:`~pysmi.codegen.symtable.SymtableCodeGen`

        Keyword Args:
            genTexts: carry human-readable texts into the output
            textFilter: callable applied to each text before it is rendered
            comments: lines to record in the generated output

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and the rendered
            module. What the second element holds depends on the generator:
            source text for the real backends, the symbol table itself for
            :py:class:`~pysmi.codegen.symtable.SymtableCodeGen`.

        Raises:
            PySmiCodegenError: the module could not be rendered.
            PySmiSemanticError: the module is not internally consistent.
        """
        raise NotImplementedError()

    def gen_index(self, processed: dict[str, Any], **kwargs: Any) -> str:
        """Render an index over the modules compiled so far.

        The index maps OIDs onto the modules that define them, so a consumer
        can find the right MIB without loading all of them.

        Args:
            processed: MIB module names mapped to their compilation results

        Keyword Args:
            dstTemplate: destination the index will be stored at, used to
                merge with an index already there

        Returns:
            The rendered index, empty when the generator produces none.
        """
        raise NotImplementedError()

    @staticmethod
    def is_binary(s: Any) -> TypeGuard[str]:
        """Tell whether *s* is an SMI binary string such as ``\'1010\'b``."""
        return isinstance(s, str) and s[0] == "'" and s[-2:] in ("'b", "'B")

    @staticmethod
    def is_hex(s: Any) -> TypeGuard[str]:
        """Tell whether *s* is an SMI hex string such as ``\'0a1b\'h``."""
        return isinstance(s, str) and s[0] == "'" and s[-2:] in ("'h", "'H")

    def str2int(self, s: Any) -> Any:
        """Convert an SMI numeric literal to an int.

        Accepts binary and hexadecimal SMI strings as well as plain decimal.

        Raises:
            PySmiSemanticError: the literal has no digits between its quotes.
        """
        if self.is_binary(s):
            if s[1:-2]:
                return int(s[1:-2], 2)
            else:
                raise error.PySmiSemanticError("empty binary string to int conversion")

        elif self.is_hex(s):
            if s[1:-2]:
                return int(s[1:-2], 16)
            else:
                raise error.PySmiSemanticError("empty hex string to int conversion")
        else:
            return int(s)
