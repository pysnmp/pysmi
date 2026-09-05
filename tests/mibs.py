#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Stand-ins for the standard modules the tests import types from.

pysmi never compiles SNMPv2-SMI, SNMPv2-TC or SNMPv2-MIB in normal use -- pysnmp ships them
as hand-written Python. The codegens still have to resolve an imported type
back to its base to render a DEFVAL or a sub-typed textual convention, so a
test that imports one needs it in the symbol table.

These carry the type assignments RFC 2578 and RFC 2579 define, plus the few
registration nodes of the RFC 2578 tree a test needs to hang an OID off.
"""

SNMPV2_SMI = """
SNMPv2-SMI DEFINITIONS ::= BEGIN

Integer32 ::= INTEGER (-2147483648..2147483647)

IpAddress ::= [APPLICATION 0] IMPLICIT OCTET STRING (SIZE (4))

Counter32 ::= [APPLICATION 1] IMPLICIT INTEGER (0..4294967295)

Gauge32 ::= [APPLICATION 2] IMPLICIT INTEGER (0..4294967295)

Unsigned32 ::= [APPLICATION 2] IMPLICIT INTEGER (0..4294967295)

TimeTicks ::= [APPLICATION 3] IMPLICIT INTEGER (0..4294967295)

Opaque ::= [APPLICATION 4] IMPLICIT OCTET STRING

Counter64 ::= [APPLICATION 6] IMPLICIT INTEGER (0..18446744073709551615)

internet    OBJECT IDENTIFIER ::= { iso 3 6 1 }
mgmt        OBJECT IDENTIFIER ::= { internet 2 }
mib-2       OBJECT IDENTIFIER ::= { mgmt 1 }
private     OBJECT IDENTIFIER ::= { internet 4 }
enterprises OBJECT IDENTIFIER ::= { private 1 }
snmpV2      OBJECT IDENTIFIER ::= { internet 6 }
snmpModules OBJECT IDENTIFIER ::= { snmpV2 3 }

END
"""

SNMPV2_TC = """
SNMPv2-TC DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, TimeTicks
        FROM SNMPv2-SMI;

DisplayString ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "Printable ASCII."
    SYNTAX       OCTET STRING (SIZE (0..255))

PhysAddress ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "1x:"
    STATUS       current
    DESCRIPTION  "A media address."
    SYNTAX       OCTET STRING

END
"""

SNMPV2_MIB = """
SNMPv2-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, snmpModules
        FROM SNMPv2-SMI;

snmpMIB     OBJECT IDENTIFIER ::= { snmpModules 1 }
snmpMIBObjects OBJECT IDENTIFIER ::= { snmpMIB 1 }
snmpTrap    OBJECT IDENTIFIER ::= { snmpMIBObjects 4 }

snmpTrapOID OBJECT-TYPE
    SYNTAX      OBJECT IDENTIFIER
    MAX-ACCESS  accessible-for-notify
    STATUS      current
    DESCRIPTION "The authoritative identification of the notification."
    ::= { snmpTrap 1 }

END
"""
