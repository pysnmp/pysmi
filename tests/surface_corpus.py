#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""MIB sources that between them reach every call pysmi emits.

:py:mod:`tests.test_pysnmp_surface` asserts that rendering these reaches the
whole of :py:mod:`pysmi.codegen.pysnmp_surface` and nothing outside it. A call
the generator can emit that no module here provokes fails that test as an
undeclared one would, so this corpus is held complete by the same assertion
that holds the declaration complete.
"""

#: Every construct that carries a narrative or structural setter: a module
#: identity with a revision, a scalar with units and a default, a fixed-length
#: string, a table with an index, a notification, and one of each conformance
#: macro. REFERENCE is on every clause that may carry it.
CONSTRUCTS_MIB = """
SURFACE-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, MODULE-IDENTITY, OBJECT-IDENTITY, NOTIFICATION-TYPE,
    Integer32, Counter32, Counter64, Gauge32, TimeTicks, Unsigned32,
    IpAddress, MibIdentifier
        FROM SNMPv2-SMI
    TEXTUAL-CONVENTION, DisplayString
        FROM SNMPv2-TC
    OBJECT-GROUP, NOTIFICATION-GROUP, MODULE-COMPLIANCE, AGENT-CAPABILITIES
        FROM SNMPv2-CONF;

surfaceModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "Module."
    REVISION     "202401010000Z"
    DESCRIPTION  "Revised."
    ::= { 1 3 0 }

surfaceBranch OBJECT IDENTIFIER ::= { surfaceModule 20 }

SurfaceTC ::= TEXTUAL-CONVENTION
    DISPLAY-HINT "255a"
    STATUS       current
    DESCRIPTION  "A textual convention."
    REFERENCE    "RFC 2579"
    SYNTAX       OCTET STRING (SIZE (0..255))

surfaceIdentity OBJECT-IDENTITY
    STATUS      current
    DESCRIPTION "An object identity."
    REFERENCE   "RFC 2578 Section 6"
    ::= { surfaceModule 9 }

surfaceScalar OBJECT-TYPE
    SYNTAX      Integer32 (0..7)
    UNITS       "widgets"
    MAX-ACCESS  read-write
    STATUS      current
    DESCRIPTION "A scalar with units and a default."
    REFERENCE   "RFC 2578 Section 7"
    DEFVAL      { 3 }
    ::= { surfaceModule 2 }

surfaceFixed OBJECT-TYPE
    SYNTAX      OCTET STRING (SIZE (6))
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A fixed-length string, which is emitted with setFixedLength."
    ::= { surfaceModule 4 }

surfaceCounter OBJECT-TYPE
    SYNTAX      Counter64
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A 64-bit counter."
    ::= { surfaceModule 5 }

surfaceTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF SurfaceEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A table."
    ::= { surfaceModule 1 }

surfaceEntry OBJECT-TYPE
    SYNTAX      SurfaceEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "A row."
    INDEX       { surfaceIndex }
    ::= { surfaceTable 1 }

SurfaceEntry ::= SEQUENCE { surfaceIndex Integer32, surfaceValue DisplayString }

surfaceIndex OBJECT-TYPE
    SYNTAX      Integer32 (1..100)
    MAX-ACCESS  read-create
    STATUS      current
    DESCRIPTION "The index."
    ::= { surfaceEntry 1 }

surfaceValue OBJECT-TYPE
    SYNTAX      DisplayString
    MAX-ACCESS  read-create
    STATUS      deprecated
    DESCRIPTION "A column."
    ::= { surfaceEntry 2 }

surfaceNotification NOTIFICATION-TYPE
    OBJECTS     { surfaceScalar }
    STATUS      current
    DESCRIPTION "A notification."
    REFERENCE   "RFC 2578 Section 8"
    ::= { surfaceModule 3 }

surfaceGroup OBJECT-GROUP
    OBJECTS     { surfaceScalar }
    STATUS      current
    DESCRIPTION "An object group."
    REFERENCE   "RFC 2580 Section 3"
    ::= { surfaceModule 6 }

surfaceNotifyGroup NOTIFICATION-GROUP
    NOTIFICATIONS { surfaceNotification }
    STATUS      current
    DESCRIPTION "A notification group."
    REFERENCE   "RFC 2580 Section 4"
    ::= { surfaceModule 7 }

surfaceCompliance MODULE-COMPLIANCE
    STATUS      current
    DESCRIPTION "A compliance statement."
    REFERENCE   "RFC 2580 Section 5"
    MODULE
        MANDATORY-GROUPS { surfaceGroup }
    ::= { surfaceModule 8 }

surfaceCapabilities AGENT-CAPABILITIES
    PRODUCT-RELEASE "Release 1."
    STATUS          current
    DESCRIPTION     "Agent capabilities."
    REFERENCE       "RFC 2580 Section 6"
    SUPPORTS        SURFACE-MIB
        INCLUDES    { surfaceGroup }
    ::= { surfaceModule 10 }

END
"""

#: A row that AUGMENTS another, which is the only thing that emits
#: ``registerAugmentions`` and ``getIndexNames``.
AUGMENTS_MIB = """
SURFACE-AUGMENTS-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, MODULE-IDENTITY, Integer32
        FROM SNMPv2-SMI;

augmentsModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "Augmenting module."
    ::= { 1 3 1 }

baseTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF BaseEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The base table."
    ::= { augmentsModule 1 }

baseEntry OBJECT-TYPE
    SYNTAX      BaseEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The base row."
    INDEX       { baseIndex }
    ::= { baseTable 1 }

BaseEntry ::= SEQUENCE { baseIndex Integer32 }

baseIndex OBJECT-TYPE
    SYNTAX      Integer32 (1..10)
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "The base index."
    ::= { baseEntry 1 }

extTable OBJECT-TYPE
    SYNTAX      SEQUENCE OF ExtEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The augmenting table."
    ::= { augmentsModule 2 }

extEntry OBJECT-TYPE
    SYNTAX      ExtEntry
    MAX-ACCESS  not-accessible
    STATUS      current
    DESCRIPTION "The augmenting row."
    AUGMENTS    { baseEntry }
    ::= { extTable 1 }

ExtEntry ::= SEQUENCE { extValue Integer32 }

extValue OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "An augmenting column."
    ::= { extEntry 1 }

END
"""

#: A symbol whose name is a Python keyword, which is the only thing that emits
#: ``setLabel``. See pysnmp/pysmi#116.
KEYWORD_MIB = """
SURFACE-KEYWORD-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, MODULE-IDENTITY, Integer32
        FROM SNMPv2-SMI;

keywordModule MODULE-IDENTITY
    LAST-UPDATED "202401010000Z"
    ORGANIZATION "Org."
    CONTACT-INFO "Contact."
    DESCRIPTION  "Keyword module."
    ::= { 1 3 2 }

global OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "A symbol named for a Python keyword."
    ::= { keywordModule 1 }

END
"""


#: An OBJECT-GROUP naming more objects than ``setObjects`` accepts at once, so
#: the batched form with ``append=True`` is emitted. See pysnmp/pysnmp#197.
def batched_objects_mib(count=260):
    """A MIB whose OBJECT-GROUP names *count* objects."""
    objects = "\n".join(
        f"""batchObject{i} OBJECT-TYPE
    SYNTAX      Integer32
    MAX-ACCESS  read-only
    STATUS      current
    DESCRIPTION "Object {i}."
    ::= {{ 1 3 3 1 {i} }}"""
        for i in range(count)
    )
    names = ", ".join(f"batchObject{i}" for i in range(count))
    return f"""
SURFACE-BATCH-MIB DEFINITIONS ::= BEGIN
IMPORTS
    OBJECT-TYPE, Integer32
        FROM SNMPv2-SMI
    OBJECT-GROUP
        FROM SNMPv2-CONF;

{objects}

batchGroup OBJECT-GROUP
    OBJECTS     {{ {names} }}
    STATUS      current
    DESCRIPTION "Every object."
    ::= {{ 1 3 3 2 }}

END
"""


#: Every source above, under the name it is rendered as.
CORPUS = {
    "SURFACE-MIB": CONSTRUCTS_MIB,
    "SURFACE-AUGMENTS-MIB": AUGMENTS_MIB,
    "SURFACE-KEYWORD-MIB": KEYWORD_MIB,
    "SURFACE-BATCH-MIB": batched_objects_mib(),
}
