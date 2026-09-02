#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the code generators, and helpers common to them."""

from typing import Any, ClassVar, Final, TypeAlias

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.mibinfo import MibInfo

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
TextClause: TypeAlias = list[str]

#: A clause carrying a list of symbol names, e.g. OBJECTS or the names of a
#: BITS type. The names are ``data[0]``.
SymbolsClause: TypeAlias = list[list[str]]

#: A clause carrying named numbers, e.g. BITS or an INTEGER enumeration. Each
#: pair is ``(name, number)`` and the pairs are ``data[0]``.
NamedNumbersClause: TypeAlias = list[list[tuple[str, int]]]

#: An INDEX clause. Each entry is ``(implied, name)``, where ``implied`` is 1
#: for the IMPLIED column and 0 otherwise. The entries are ``data[0]``.
IndexClause: TypeAlias = list[list[tuple[int, str]]]

#: A SEQUENCE clause. Each entry is ``(name, type)`` and the entries are
#: ``data[0]``.
SequenceClause: TypeAlias = list[list[tuple[str, str]]]


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
    def is_binary(s: Any) -> Any:
        """Tell whether *s* is an SMI binary string such as ``\'1010\'b``."""
        return isinstance(s, str) and s[0] == "'" and s[-2:] in ("'b", "'B")

    @staticmethod
    def is_hex(s: Any) -> Any:
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
