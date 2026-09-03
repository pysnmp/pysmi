#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Stand-ins for the standard modules the tests import types from.

pysmi never compiles SNMPv2-SMI or SNMPv2-TC in normal use -- pysnmp ships them
as hand-written Python. The codegens still have to resolve an imported type
back to its base to render a DEFVAL or a sub-typed textual convention, so a
test that imports one needs it in the symbol table.

These carry the type assignments RFC 2578 and RFC 2579 define, and nothing else.
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
