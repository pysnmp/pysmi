#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""PLY grammar for SMI.

The docstring of each ``p_*`` function is its grammar rule, read by PLY at
import time. They are grammar, not documentation.
"""

import logging
import os
from typing import Any, cast

import ply.yacc as yacc
from ply.yacc import YaccProduction

from pysmi import debug, error
from pysmi.lexer.smi import lexerFactory
from pysmi.parser.base import AbstractParser

logger = logging.getLogger(__name__)

YACC_VERSION = [int(x) for x in yacc.__version__.split(".")]

# SMIv1 lets the upper bound of a range be written as MAX, meaning the largest
# value the type can hold. It is resolved here, while the syntax still says
# which type the constraint was written against; nothing downstream ever sees
# the keyword. MIN has no counterpart: it is a forbidden word in both dialects,
# so an SMIv1 MIB cannot write it.
_TYPE_BOUNDS: dict[str, int] = {
    "INTEGER": 2147483647,
    "Integer32": 2147483647,
    "Counter": 4294967295,
    "Counter32": 4294967295,
    "Gauge": 4294967295,
    "Gauge32": 4294967295,
    "Unsigned32": 4294967295,
    "TimeTicks": 4294967295,
    "Counter64": 18446744073709551615,
}

# A SIZE is a count of octets, so it is bounded by the longest OCTET STRING an
# SNMP message can carry rather than by the type named in front of it.
_SIZE_BOUNDS: int = 65535


def _resolve_max_bound(typeName: Any, subType: Any) -> Any:
    """Replace MAX bounds in *subType* with the value it stands for.

    *typeName* is the syntax the constraint was written against. An unknown name
    is a textual convention, whose base type is not resolved until code
    generation; those fall back to the widest signed integer, which is what an
    SMIv1 MIB means by an unqualified INTEGER.

    Returns:
        *subType* with every MAX bound replaced by a number.
    """
    if not isinstance(subType, tuple) or len(subType) != 2:
        return subType

    tag, ranges = subType
    if tag == "octetStringSubType":
        high = _SIZE_BOUNDS
    elif tag == "integerSubType":
        high = _TYPE_BOUNDS.get(typeName, _TYPE_BOUNDS["INTEGER"])
    else:
        return subType

    if not any(bound == "MAX" for rng in ranges for bound in rng):
        return subType

    return (tag, [tuple(high if b == "MAX" else b for b in rng) for rng in ranges])


# noinspection PyMethodMayBeStatic,PyIncorrectDocstring
class SmiV2Parser(AbstractParser):
    """Parser for the SMIv2 grammar.

    Builds a PLY parser over the SMIv2 lexer. The
    generated parse tables are cached on disk when a temporary directory is
    given, since building them is slow.

    The SMIv1 and relaxed dialects are produced by
    :py:func:`parserFactory`, which mixes the grammar relaxations below into
    this class.
    """

    defaultLexer = lexerFactory()

    def __init__(self, startSym: str = "mibFile", tempdir: str = "") -> None:
        if tempdir:
            tempdir = os.path.join(tempdir, startSym)
            try:
                os.makedirs(tempdir)
            except OSError as exc:
                if exc.errno != 17:
                    raise error.PySmiError(f"Failed to create cache directory {tempdir}: {exc}") from exc

        self.lexer = self.defaultLexer(tempdir=tempdir)

        # tokens are required for parser
        self.tokens = self.lexer.tokens

        if YACC_VERSION < [3, 0]:
            self.parser = yacc.yacc(
                module=self, start=startSym, write_tables=bool(tempdir), debug=False, outputdir=tempdir
            )
        else:
            errorlog = logger if logger.isEnabledFor(logging.DEBUG) else yacc.NullLogger()

            grammarLogger = logging.getLogger(debug.GRAMMAR_LOGGER)
            debuglog = grammarLogger if grammarLogger.isEnabledFor(logging.DEBUG) else None

            self.parser = yacc.yacc(
                module=self,
                start=startSym,
                write_tables=bool(tempdir),
                debug=False,
                outputdir=tempdir,
                debuglog=debuglog,
                errorlog=errorlog,
            )

    def reset(self) -> None:
        """Ready the parser for another module."""
        # Ply requires lexer reinitialization for (at least) resetting lineno
        self.lexer.reset()

    def parse(self, data: str, **kwargs: Any) -> list[Any]:
        """Parse ASN.1 MIB text into one parse tree per module.

        Args:
            data (str): ASN.1 MIB text

        Returns:
            One parse tree for each module in the text.

        Raises:
            PySmiLexerError: the text could not be tokenised.
            PySmiParserError: the tokens do not fit the grammar.
        """
        logger.debug(
            'source MIB size is %d characters, first 50 characters are "%s..."',
            len(data),
            data[:50],
            extra={"size": len(data)},
        )

        ast = self.parser.parse(data, lexer=self.lexer.lexer)

        self.reset()

        if ast and ast[0] == "mibFile" and ast[1]:  # mibfile is not empty
            return cast("list[Any]", ast[1])
        else:
            return []

    #
    # SMIv2 grammar follows
    #

    def p_mibFile(self, p: YaccProduction) -> None:
        """mibFile : modules
        | empty"""
        p[0] = ("mibFile", p[1])

    def p_modules(self, p: YaccProduction) -> None:
        """modules : modules module
        | module"""
        n = len(p)
        if n == 3:
            p[0] = p[1] + [p[2]]
        elif n == 2:
            p[0] = [p[1]]

    def p_module(self, p: YaccProduction) -> None:
        """module : moduleName moduleOid DEFINITIONS COLON_COLON_EQUAL BEGIN exportsClause linkagePart declarationPart END"""
        p[0] = (
            p[1],  # name
            p[2],  # oid
            p[7],  # linkage (imports)
            p[8],
        )  # declaration

    def p_moduleOid(self, p: YaccProduction) -> None:
        """moduleOid : '{' objectIdentifier '}'
        | empty"""
        n = len(p)
        if n == 4:
            p[0] = p[2]

    def p_linkagePart(self, p: YaccProduction) -> None:
        """linkagePart : linkageClause
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_linkageClause(self, p: YaccProduction) -> None:
        """linkageClause : IMPORTS importPart ';'"""
        p[0] = p[2]

    def p_exportsClause(self, p: YaccProduction) -> None:
        """exportsClause : EXPORTS
        | empty"""

    def p_importPart(self, p: YaccProduction) -> None:
        """importPart : imports
        | empty"""
        # libsmi: TODO: ``IMPORTS ;'' allowed? refer ASN.1!
        if p[1]:
            importDict: dict[Any, Any] = {}
            for imp in p[1]:  # don't do just dict() because moduleNames may be repeated
                fromModule, symbols = imp
                if fromModule in importDict:
                    importDict[fromModule] += symbols
                else:
                    importDict[fromModule] = symbols

            p[0] = importDict

    def p_imports(self, p: YaccProduction) -> None:
        """imports : imports import
        | import"""
        n = len(p)
        if n == 3:
            p[0] = p[1] + [p[2]]
        elif n == 2:
            p[0] = [p[1]]

    def p_import(self, p: YaccProduction) -> None:
        """import : importIdentifiers FROM moduleName"""
        # libsmi: TODO: multiple clauses with same moduleName allowed?
        # I guess so. refer ASN.1!
        p[0] = (
            p[3],  # moduleName
            p[1],
        )  # ids

    def p_importIdentifiers(self, p: YaccProduction) -> None:
        """importIdentifiers : importIdentifiers ',' importIdentifier
        | importIdentifier"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    # Note that some named types must not be imported, REF:RFC1902,590
    def p_importIdentifier(self, p: YaccProduction) -> None:
        """importIdentifier : LOWERCASE_IDENTIFIER
        | UPPERCASE_IDENTIFIER
        | importedKeyword"""
        p[0] = p[1]

    def p_importedKeyword(self, p: YaccProduction) -> None:
        """importedKeyword : importedSMIKeyword
        | BITS
        | INTEGER32
        | IPADDRESS
        | MANDATORY_GROUPS
        | MODULE_COMPLIANCE
        | MODULE_IDENTITY
        | OBJECT_GROUP
        | OBJECT_IDENTITY
        | OBJECT_TYPE
        | OPAQUE
        | TEXTUAL_CONVENTION
        | TIMETICKS
        | UNSIGNED32"""
        p[0] = p[1]

    def p_importedSMIKeyword(self, p: YaccProduction) -> None:
        """importedSMIKeyword : AGENT_CAPABILITIES
        | COUNTER32
        | COUNTER64
        | GAUGE32
        | NOTIFICATION_GROUP
        | NOTIFICATION_TYPE
        | TRAP_TYPE"""
        p[0] = p[1]

    def p_moduleName(self, p: YaccProduction) -> None:
        """moduleName : UPPERCASE_IDENTIFIER"""
        p[0] = p[1]

    def p_declarationPart(self, p: YaccProduction) -> None:
        """declarationPart : declarations
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_declarations(self, p: YaccProduction) -> None:
        """declarations : declarations declaration
        | declaration"""
        n = len(p)
        if n == 3:
            p[0] = p[1] + [p[2]]
        elif n == 2:
            p[0] = [p[1]]

    def p_declaration(self, p: YaccProduction) -> None:
        """declaration : typeDeclaration
        | valueDeclaration
        | objectIdentityClause
        | objectTypeClause
        | trapTypeClause
        | notificationTypeClause
        | moduleIdentityClause
        | moduleComplianceClause
        | objectGroupClause
        | notificationGroupClause
        | agentCapabilitiesClause
        | macroClause"""
        if p[1]:
            p[0] = p[1]

    def p_macroClause(self, p: YaccProduction) -> None:
        """macroClause : macroName MACRO END"""

    def p_macroName(self, p: YaccProduction) -> None:
        """macroName : MODULE_IDENTITY
        | OBJECT_TYPE
        | TRAP_TYPE
        | NOTIFICATION_TYPE
        | OBJECT_IDENTITY
        | TEXTUAL_CONVENTION
        | OBJECT_GROUP
        | NOTIFICATION_GROUP
        | MODULE_COMPLIANCE
        | AGENT_CAPABILITIES"""

    def p_choiceClause(self, p: YaccProduction) -> None:
        """choiceClause : CHOICE"""

    # libsmi: The only ASN.1 value declarations are for OIDs, REF:RFC1902,491.
    def p_fuzzy_lowercase_identifier(self, p: YaccProduction) -> None:
        """fuzzy_lowercase_identifier : LOWERCASE_IDENTIFIER
        | UPPERCASE_IDENTIFIER"""
        p[0] = p[1]

    def p_valueDeclaration(self, p: YaccProduction) -> None:
        """valueDeclaration : fuzzy_lowercase_identifier OBJECT IDENTIFIER COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "valueDeclaration",
            p[1],  # id
            p[6],
        )  # objectIdentifier

    def p_typeDeclaration(self, p: YaccProduction) -> None:
        """typeDeclaration : typeName COLON_COLON_EQUAL typeDeclarationRHS"""
        p[0] = (
            "typeDeclaration",
            p[1],  # name
            p[3],
        )  # declarationRHS

    def p_typeName(self, p: YaccProduction) -> None:
        """typeName : UPPERCASE_IDENTIFIER
        | typeSMI"""
        p[0] = p[1]

    def p_typeSMI(self, p: YaccProduction) -> None:
        """typeSMI : typeSMIandSPPI
        | typeSMIonly"""
        p[0] = p[1]

    def p_typeSMIandSPPI(self, p: YaccProduction) -> None:
        """typeSMIandSPPI : IPADDRESS
        | TIMETICKS
        | OPAQUE
        | INTEGER32
        | UNSIGNED32"""
        p[0] = p[1]

    def p_typeSMIonly(self, p: YaccProduction) -> None:
        """typeSMIonly : COUNTER32
        | GAUGE32
        | COUNTER64"""
        p[0] = p[1]

    def p_typeDeclarationRHS(self, p: YaccProduction) -> None:
        """typeDeclarationRHS : Syntax
        | TEXTUAL_CONVENTION DisplayPart STATUS Status DESCRIPTION Text ReferPart SYNTAX Syntax
        | choiceClause"""
        if p[1]:
            if p[1] == "TEXTUAL-CONVENTION":
                p[0] = (
                    "typeDeclarationRHS",
                    p[2],  # display
                    p[4],  # status
                    (p[5], p[6]),  # description
                    p[7],  # reference
                    p[9],
                )  # syntax
            else:
                p[0] = ("typeDeclarationRHS", p[1])
                # ignore the choiceClause

    def p_conceptualTable(self, p: YaccProduction) -> None:
        """conceptualTable : SEQUENCE OF row"""
        p[0] = ("conceptualTable", p[3])

    def p_row(self, p: YaccProduction) -> None:
        """row : UPPERCASE_IDENTIFIER"""
        # libsmi: TODO: this must be an entryType
        p[0] = ("row", p[1])

    def p_entryType(self, p: YaccProduction) -> None:
        """entryType : SEQUENCE '{' sequenceItems '}'"""
        p[0] = (p[1], p[3])

    def p_sequenceItems(self, p: YaccProduction) -> None:
        """sequenceItems : sequenceItems ',' sequenceItem
        | sequenceItem"""
        # libsmi: TODO: might this list be emtpy?
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    def p_sequenceItem(self, p: YaccProduction) -> None:
        """sequenceItem : LOWERCASE_IDENTIFIER sequenceSyntax"""
        p[0] = (p[1], p[2])

    def p_Syntax(self, p: YaccProduction) -> None:
        """Syntax : ObjectSyntax
        | BITS '{' NamedBits '}'"""
        # libsmi: TODO: standalone `BITS' ok? seen in RMON2-MIB
        # libsmi: -> no, it's only allowed in a SEQUENCE {...}
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 5:
            p[0] = (p[1], p[3])

    def p_sequenceSyntax(self, p: YaccProduction) -> None:
        """sequenceSyntax : BITS
        | UPPERCASE_IDENTIFIER anySubType
        | sequenceObjectSyntax"""
        p[0] = p[1]  # no subtype or complex syntax supported

    def p_NamedBits(self, p: YaccProduction) -> None:
        """NamedBits : NamedBits ',' NamedBit
        | NamedBit"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    def p_NamedBit(self, p: YaccProduction) -> None:
        """NamedBit : LOWERCASE_IDENTIFIER '(' NUMBER ')'"""
        p[0] = (p[1], p[3])

    def p_objectIdentityClause(self, p: YaccProduction) -> None:
        """objectIdentityClause : LOWERCASE_IDENTIFIER OBJECT_IDENTITY STATUS Status DESCRIPTION Text ReferPart COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "objectIdentityClause",
            p[1],  # id
            #  p[2], # OBJECT_IDENTITY
            p[4],  # status
            (p[5], p[6]),  # description
            p[7],  # reference
            p[10],
        )  # objectIdentifier

    def p_objectTypeClause(self, p: YaccProduction) -> None:
        """objectTypeClause : LOWERCASE_IDENTIFIER OBJECT_TYPE SYNTAX Syntax UnitsPart MaxOrPIBAccessPart STATUS Status descriptionClause ReferPart IndexPart MibIndex DefValPart COLON_COLON_EQUAL '{' ObjectName '}'"""
        p[0] = (
            "objectTypeClause",
            p[1],  # id
            #  p[2], # OBJECT_TYPE
            p[4],  # syntax
            p[5],  # UnitsPart
            p[6],  # MaxOrPIBAccessPart
            p[8],  # status
            p[9],  # descriptionClause
            p[10],  # reference
            p[11],  # augmentions
            p[12],  # index
            p[13],  # DefValPart
            p[16],
        )  # ObjectName

    def p_descriptionClause(self, p: YaccProduction) -> None:
        """descriptionClause : DESCRIPTION Text
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_trapTypeClause(self, p: YaccProduction) -> None:
        """trapTypeClause : fuzzy_lowercase_identifier TRAP_TYPE ENTERPRISE objectIdentifier VarPart DescrPart ReferPart COLON_COLON_EQUAL NUMBER"""
        # libsmi: TODO: range of number?
        p[0] = (
            "trapTypeClause",
            p[1],  # fuzzy_lowercase_identifier
            #  p[2], # TRAP_TYPE
            p[4],  # objectIdentifier
            p[5],  # VarPart
            p[6],  # description
            p[7],  # reference
            p[9],
        )  # NUMBER

    def p_VarPart(self, p: YaccProduction) -> None:
        """VarPart : VARIABLES '{' VarTypes '}'
        | empty"""
        p[0] = (p[1] and p[3]) or []

    def p_VarTypes(self, p: YaccProduction) -> None:
        """VarTypes : VarTypes ',' VarType
        | VarType"""
        n = len(p)
        if n == 4:
            p[0] = ("VarTypes", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("VarTypes", [p[1]])

    def p_VarType(self, p: YaccProduction) -> None:
        """VarType : ObjectName"""
        p[0] = p[1][1][0]

    def p_DescrPart(self, p: YaccProduction) -> None:
        """DescrPart : DESCRIPTION Text
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_MaxOrPIBAccessPart(self, p: YaccProduction) -> None:
        """MaxOrPIBAccessPart : MaxAccessPart
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_MaxAccessPart(self, p: YaccProduction) -> None:
        """MaxAccessPart : MAX_ACCESS Access
        | ACCESS Access"""
        p[0] = ("MaxAccessPart", p[2])

    def p_notificationTypeClause(self, p: YaccProduction) -> None:
        """notificationTypeClause : LOWERCASE_IDENTIFIER NOTIFICATION_TYPE NotificationObjectsPart STATUS Status DESCRIPTION Text ReferPart COLON_COLON_EQUAL '{' NotificationName '}'"""
        p[0] = (
            "notificationTypeClause",
            p[1],  # id
            #  p[2], # NOTIFICATION_TYPE
            p[3],  # NotificationObjectsPart
            p[5],  # status
            (p[6], p[7]),  # description
            p[8],  # reference
            p[11],
        )  # NotificationName aka objectIdentifier

    def p_moduleIdentityClause(self, p: YaccProduction) -> None:
        """moduleIdentityClause : LOWERCASE_IDENTIFIER MODULE_IDENTITY SubjectCategoriesPart LAST_UPDATED ExtUTCTime ORGANIZATION Text CONTACT_INFO Text DESCRIPTION Text RevisionPart COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "moduleIdentityClause",
            p[1],  # id
            #  p[2], # MODULE_IDENTITY
            # XXX  p[3], # SubjectCategoriesPart
            (p[4], p[5]),  # last updated
            (p[6], p[7]),  # organization
            (p[8], p[9]),  # contact info
            (p[10], p[11]),  # description
            p[12],  # RevisionPart
            p[15],
        )  # objectIdentifier

    # Subject categories: RFC3159

    def p_SubjectCategoriesPart(self, p: YaccProduction) -> None:
        """SubjectCategoriesPart : SUBJECT_CATEGORIES '{' SubjectCategories '}'
        | empty"""
        # if p[1]:
        #  p[0] = (p[1], p[3])

    def p_SubjectCategories(self, p: YaccProduction) -> None:
        """SubjectCategories : CategoryIDs"""
        # p[0] = p[1]

    def p_CategoryIDs(self, p: YaccProduction) -> None:
        """CategoryIDs : CategoryIDs ',' CategoryID
        | CategoryID"""
        # n = len(p)
        # if n == 4:
        #  p[0] = ('CategoryIDs', p[1][1] + [p[3]])
        # elif n == 2:
        #  p[0] = ('CategoryIDs', [p[1]])

    def p_CategoryID(self, p: YaccProduction) -> None:
        """CategoryID : LOWERCASE_IDENTIFIER '(' NUMBER ')'
        | LOWERCASE_IDENTIFIER"""
        # n = len(p)
        # if n == 2:
        #  p[0] = ('CategoryID', p[1])
        # elif n == 5:
        #  p[0] = ('CategoryID', p[3])

    # ...subject categories

    def p_ObjectSyntax(self, p: YaccProduction) -> None:
        """ObjectSyntax : SimpleSyntax
        | conceptualTable
        | row
        | entryType
        | ApplicationSyntax
        | typeTag SimpleSyntax"""
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 3:
            p[0] = p[2]

    def p_typeTag(self, p: YaccProduction) -> None:
        """typeTag : '[' APPLICATION NUMBER ']' IMPLICIT
        | '[' UNIVERSAL NUMBER ']' IMPLICIT"""

    def p_sequenceObjectSyntax(self, p: YaccProduction) -> None:
        """sequenceObjectSyntax : sequenceSimpleSyntax
        | sequenceApplicationSyntax"""
        # libsmi: TO DO: add to this rule conceptualTable, row, entryType
        p[0] = p[1]

    def p_valueofObjectSyntax(self, p: YaccProduction) -> None:
        """valueofObjectSyntax : valueofSimpleSyntax"""
        p[0] = p[1]

    def p_SimpleSyntax(self, p: YaccProduction) -> None:
        """SimpleSyntax : INTEGER
        | INTEGER integerSubType
        | INTEGER enumSpec
        | INTEGER32
        | INTEGER32 integerSubType
        | UPPERCASE_IDENTIFIER enumSpec
        | UPPERCASE_IDENTIFIER integerSubType
        | OCTET STRING
        | OCTET STRING octetStringSubType
        | UPPERCASE_IDENTIFIER octetStringSubType
        | OBJECT IDENTIFIER anySubType"""
        n = len(p)
        if n == 2:
            p[0] = ("SimpleSyntax", p[1])

        elif n == 3:
            if p[1] == "OCTET":
                p[0] = ("SimpleSyntax", p[1] + " " + p[2])
            else:
                p[0] = ("SimpleSyntax", p[1], _resolve_max_bound(p[1], p[2]))

        elif n == 4:
            p[0] = ("SimpleSyntax", p[1] + " " + p[2], _resolve_max_bound(p[1] + " " + p[2], p[3]))

    def p_valueofSimpleSyntax(self, p: YaccProduction) -> None:
        """valueofSimpleSyntax : NUMBER
        | NEGATIVENUMBER
        | NUMBER64
        | NEGATIVENUMBER64
        | HEX_STRING
        | BIN_STRING
        | LOWERCASE_IDENTIFIER
        | QUOTED_STRING
        | '{' objectIdentifier_defval '}'"""
        # libsmi for objectIdentifier_defval:
        # This is only for some MIBs with invalid numerical
        # OID notation for DEFVALs. We DO NOT parse them
        # correctly. We just don't want to produce a
        # parser error.
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 4:  # XXX
            pass

    def p_sequenceSimpleSyntax(self, p: YaccProduction) -> None:
        """sequenceSimpleSyntax : INTEGER anySubType
        | INTEGER32 anySubType
        | OCTET STRING anySubType
        | OBJECT IDENTIFIER anySubType"""
        n = len(p)
        if n == 3:
            p[0] = p[1]  # XXX not supporting subtypes here
        elif n == 4:
            p[0] = p[1] + " " + p[2]  # XXX not supporting subtypes here

    def p_ApplicationSyntax(self, p: YaccProduction) -> None:
        """ApplicationSyntax : IPADDRESS anySubType
        | COUNTER32
        | COUNTER32 integerSubType
        | GAUGE32
        | GAUGE32 integerSubType
        | UNSIGNED32
        | UNSIGNED32 integerSubType
        | TIMETICKS anySubType
        | OPAQUE
        | OPAQUE octetStringSubType
        | COUNTER64
        | COUNTER64 integerSubType"""
        # COUNTER32 and COUNTER64 was with anySubType in libsmi
        n = len(p)
        if n == 2:
            p[0] = ("ApplicationSyntax", p[1])
        elif n == 3:
            p[0] = ("ApplicationSyntax", p[1], _resolve_max_bound(p[1], p[2]))

    def p_sequenceApplicationSyntax(self, p: YaccProduction) -> None:
        """sequenceApplicationSyntax : IPADDRESS anySubType
        | COUNTER32 anySubType
        | GAUGE32 anySubType
        | UNSIGNED32 anySubType
        | TIMETICKS anySubType
        | OPAQUE
        | COUNTER64 anySubType"""
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 3:
            p[0] = p[1]  # XXX not supporting subtypes here

    def p_anySubType(self, p: YaccProduction) -> None:
        """anySubType : integerSubType
        | octetStringSubType
        | enumSpec
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_integerSubType(self, p: YaccProduction) -> None:
        """integerSubType : '(' ranges ')'"""
        p[0] = ("integerSubType", p[2])

    def p_octetStringSubType(self, p: YaccProduction) -> None:
        """octetStringSubType : '(' SIZE '(' ranges ')' ')'"""
        p[0] = ("octetStringSubType", p[4])

    def p_ranges(self, p: YaccProduction) -> None:
        """ranges : ranges '|' range
        | range"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    def p_range(self, p: YaccProduction) -> None:
        """range : value DOT_DOT value
        | value"""
        n = len(p)
        if n == 2:
            p[0] = (p[1],)
        elif n == 4:
            p[0] = (p[1], p[3])

    def p_value(self, p: YaccProduction) -> None:
        """value : NEGATIVENUMBER
        | NUMBER
        | NEGATIVENUMBER64
        | NUMBER64
        | HEX_STRING
        | BIN_STRING"""
        p[0] = p[1]

    def p_enumSpec(self, p: YaccProduction) -> None:
        """enumSpec : '{' enumItems '}'"""
        p[0] = ("enumSpec", p[2])

    def p_enumItems(self, p: YaccProduction) -> None:
        """enumItems : enumItems ',' enumItem
        | enumItem"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    def p_enumItem(self, p: YaccProduction) -> None:
        """enumItem : LOWERCASE_IDENTIFIER '(' enumNumber ')'"""
        p[0] = (p[1], p[3])

    def p_enumNumber(self, p: YaccProduction) -> None:
        """enumNumber : NUMBER
        | NEGATIVENUMBER"""
        # XXX              | LOWERCASE_IDENTIFIER"""
        p[0] = p[1]

    def p_Status(self, p: YaccProduction) -> None:
        """Status : LOWERCASE_IDENTIFIER"""
        p[0] = ("Status", p[1])

    def p_DisplayPart(self, p: YaccProduction) -> None:
        """DisplayPart : DISPLAY_HINT Text
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_UnitsPart(self, p: YaccProduction) -> None:
        """UnitsPart : UNITS Text
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_Access(self, p: YaccProduction) -> None:
        """Access : LOWERCASE_IDENTIFIER"""
        p[0] = p[1]

    def p_IndexPart(self, p: YaccProduction) -> None:
        """IndexPart : AUGMENTS '{' Entry '}'
        | empty"""
        if p[1]:
            p[0] = p[3]

    def p_MibIndex(self, p: YaccProduction) -> None:
        """MibIndex : INDEX '{' IndexTypes '}'
        | empty"""
        if p[1]:
            p[0] = (p[1], p[3])

    def p_IndexTypes(self, p: YaccProduction) -> None:
        """IndexTypes : IndexTypes ',' IndexType
        | IndexType"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]

    def p_IndexType(self, p: YaccProduction) -> None:
        """IndexType : IMPLIED Index
        | Index"""
        n = len(p)
        if n == 2:
            p[0] = (0, p[1])
        elif n == 3:
            p[0] = (1, p[2])  # IMPLIED

    def p_Index(self, p: YaccProduction) -> None:
        """Index : ObjectName"""
        # libsmi: TODO: use the SYNTAX value of the correspondent
        #               OBJECT-TYPE invocation
        p[0] = p[1][1][0]  # XXX just name???

    def p_Entry(self, p: YaccProduction) -> None:
        """Entry : ObjectName"""
        p[0] = p[1][1][0]

    def p_DefValPart(self, p: YaccProduction) -> None:
        """DefValPart : DEFVAL '{' Value '}'
        | empty"""
        # A zero is a value like any other, so test for one having been parsed
        # rather than for its truth. Productions that deliberately swallow a
        # default they cannot represent leave None here and still drop out.
        if p[1] and p[3] is not None:
            p[0] = (p[1], p[3])

    def p_Value(self, p: YaccProduction) -> None:
        """Value : valueofObjectSyntax
        | '{' BitsValue '}'"""
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 4:
            p[0] = p[2]

    def p_BitsValue(self, p: YaccProduction) -> None:
        """BitsValue : BitNames
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_BitNames(self, p: YaccProduction) -> None:
        """BitNames : BitNames ',' LOWERCASE_IDENTIFIER
        | LOWERCASE_IDENTIFIER"""
        n = len(p)
        if n == 4:
            p[0] = ("BitNames", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("BitNames", [p[1]])

    def p_ObjectName(self, p: YaccProduction) -> None:
        """ObjectName : objectIdentifier"""
        p[0] = p[1]

    def p_NotificationName(self, p: YaccProduction) -> None:
        """NotificationName : objectIdentifier"""
        p[0] = p[1]

    def p_ReferPart(self, p: YaccProduction) -> None:
        """ReferPart : REFERENCE Text
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_RevisionPart(self, p: YaccProduction) -> None:
        """RevisionPart : Revisions
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_Revisions(self, p: YaccProduction) -> None:
        """Revisions : Revisions Revision
        | Revision"""
        n = len(p)
        if n == 3:
            p[0] = ("Revisions", p[1][1] + [p[2]])
        elif n == 2:
            p[0] = ("Revisions", [p[1]])

    def p_Revision(self, p: YaccProduction) -> None:
        """Revision : REVISION ExtUTCTime DESCRIPTION Text"""
        p[0] = (
            p[2],  # revision time
            (p[3], p[4]),
        )  # description

    def p_NotificationObjectsPart(self, p: YaccProduction) -> None:
        """NotificationObjectsPart : OBJECTS '{' Objects '}'
        | empty"""
        p[0] = (p[1] and p[3]) or []

    def p_ObjectGroupObjectsPart(self, p: YaccProduction) -> None:
        """ObjectGroupObjectsPart : OBJECTS '{' Objects '}'"""
        p[0] = p[3]

    def p_Objects(self, p: YaccProduction) -> None:
        """Objects : Objects ',' Object
        | Object"""
        n = len(p)
        if n == 4:
            p[0] = ("Objects", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("Objects", [p[1]])

    def p_Object(self, p: YaccProduction) -> None:
        """Object : ObjectName"""
        p[0] = p[1][1][0]

    def p_NotificationsPart(self, p: YaccProduction) -> None:
        """NotificationsPart : NOTIFICATIONS '{' Notifications '}'"""
        p[0] = p[3]

    def p_Notifications(self, p: YaccProduction) -> None:
        """Notifications : Notifications ',' Notification
        | Notification"""
        n = len(p)
        if n == 4:
            p[0] = ("Notifications", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("Notifications", [p[1]])

    def p_Notification(self, p: YaccProduction) -> None:
        """Notification : NotificationName"""
        p[0] = p[1][1][0]

    def p_Text(self, p: YaccProduction) -> None:
        """Text : QUOTED_STRING"""
        p[0] = p[1][1:-1]  # getting rid of quotes

    def p_ExtUTCTime(self, p: YaccProduction) -> None:
        """ExtUTCTime : QUOTED_STRING"""
        p[0] = p[1][1:-1]  # getting rid of quotes

    def p_objectIdentifier(self, p: YaccProduction) -> None:
        """objectIdentifier : subidentifiers"""
        p[0] = ("objectIdentifier", p[1])

    def p_subidentifiers(self, p: YaccProduction) -> None:
        """subidentifiers : subidentifiers subidentifier
        | subidentifier"""
        n = len(p)
        if n == 3:
            p[0] = p[1] + [p[2]]
        elif n == 2:
            p[0] = [p[1]]

    def p_subidentifier(self, p: YaccProduction) -> None:
        """subidentifier : fuzzy_lowercase_identifier
        | NUMBER
        | LOWERCASE_IDENTIFIER '(' NUMBER ')'"""
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 5:
            # NOTE: we are not creating new symbol p[1] because formally
            # it is not defined in *this* MIB
            p[0] = (p[1], p[3])

    def p_objectIdentifier_defval(self, p: YaccProduction) -> None:
        """objectIdentifier_defval : subidentifiers_defval"""
        p[0] = ("objectIdentifier_defval", p[1])

    def p_subidentifiers_defval(self, p: YaccProduction) -> None:
        """subidentifiers_defval : subidentifiers_defval subidentifier_defval
        | subidentifier_defval"""
        n = len(p)
        if n == 3:
            p[0] = ("subidentifiers_defval", p[1][1] + [p[2]])
        elif n == 2:
            p[0] = ("subidentifiers_defval", [p[1]])

    def p_subidentifier_defval(self, p: YaccProduction) -> None:
        """subidentifier_defval : LOWERCASE_IDENTIFIER '(' NUMBER ')'
        | NUMBER"""
        n = len(p)
        if n == 2:
            p[0] = ("subidentifier_defval", p[1])
        elif n == 5:
            p[0] = ("subidentifier_defval", p[1], p[3])

    def p_objectGroupClause(self, p: YaccProduction) -> None:
        """objectGroupClause : LOWERCASE_IDENTIFIER OBJECT_GROUP ObjectGroupObjectsPart STATUS Status DESCRIPTION Text ReferPart COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "objectGroupClause",
            p[1],  # id
            p[3],  # objects
            p[5],  # status
            (p[6], p[7]),  # description
            p[8],  # reference
            p[11],
        )  # objectIdentifier

    def p_notificationGroupClause(self, p: YaccProduction) -> None:
        """notificationGroupClause : LOWERCASE_IDENTIFIER NOTIFICATION_GROUP NotificationsPart STATUS Status DESCRIPTION Text ReferPart COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "notificationGroupClause",
            p[1],  # id
            p[3],  # notifications
            p[5],  # status
            (p[6], p[7]),  # description
            p[8],  # reference
            p[11],
        )  # objectIdentifier

    def p_moduleComplianceClause(self, p: YaccProduction) -> None:
        """moduleComplianceClause : LOWERCASE_IDENTIFIER MODULE_COMPLIANCE STATUS Status DESCRIPTION Text ReferPart ComplianceModulePart COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "moduleComplianceClause",
            p[1],  # id
            #  p[2], # MODULE_COMPLIANCE
            p[4],  # status
            (p[5], p[6]),  # description
            p[7],  # reference
            p[8],  # ComplianceModules
            p[11],
        )  # objectIdentifier

    def p_ComplianceModulePart(self, p: YaccProduction) -> None:
        """ComplianceModulePart : ComplianceModules"""
        p[0] = p[1]

    def p_ComplianceModules(self, p: YaccProduction) -> None:
        """ComplianceModules : ComplianceModules ComplianceModule
        | ComplianceModule"""
        n = len(p)
        if n == 3:
            p[0] = ("ComplianceModules", p[1][1] + [p[2]])
        elif n == 2:
            p[0] = ("ComplianceModules", [p[1]])

    def p_ComplianceModule(self, p: YaccProduction) -> None:
        """ComplianceModule : MODULE ComplianceModuleName MandatoryPart CompliancePart"""
        objects = (p[3] and p[3][1]) or []
        objects += (p[4] and p[4][1]) or []
        p[0] = (
            p[2],  # ModuleName
            objects,
        )  # MandatoryPart + CompliancePart

    def p_ComplianceModuleName(self, p: YaccProduction) -> None:
        """ComplianceModuleName : UPPERCASE_IDENTIFIER
        | empty"""
        # XXX                   | UPPERCASE_IDENTIFIER objectIdentifier
        p[0] = p[1]

    def p_MandatoryPart(self, p: YaccProduction) -> None:
        """MandatoryPart : MANDATORY_GROUPS '{' MandatoryGroups '}'
        | empty"""
        if p[1]:
            p[0] = p[3]

    def p_MandatoryGroups(self, p: YaccProduction) -> None:
        """MandatoryGroups : MandatoryGroups ',' MandatoryGroup
        | MandatoryGroup"""
        n = len(p)
        if n == 4:
            p[0] = ("MandatoryGroups", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("MandatoryGroups", [p[1]])

    def p_MandatoryGroup(self, p: YaccProduction) -> None:
        """MandatoryGroup : objectIdentifier"""
        p[0] = p[1][1][0]  # objectIdentifier? Maybe name?

    def p_CompliancePart(self, p: YaccProduction) -> None:
        """CompliancePart : Compliances
        | empty"""
        if p[1]:
            p[0] = p[1]

    def p_Compliances(self, p: YaccProduction) -> None:
        """Compliances : Compliances Compliance
        | Compliance"""
        n = len(p)
        if n == 3:
            p[0] = (p[1] and p[2] and ("Compliances", p[1][1] + [p[2]])) or p[1]
        elif n == 2:
            p[0] = (p[1] and ("Compliances", [p[1]])) or None

    def p_Compliance(self, p: YaccProduction) -> None:
        """Compliance : ComplianceGroup
        | ComplianceObject"""
        if p[1]:
            p[0] = p[1]

    def p_ComplianceGroup(self, p: YaccProduction) -> None:
        """ComplianceGroup : GROUP objectIdentifier DESCRIPTION Text"""
        p[0] = p[2][1][0]  # objectIdentifier
        #        p[1], # GROUP
        #        (p[3], p[4])) # description

    def p_ComplianceObject(self, p: YaccProduction) -> None:
        """ComplianceObject : OBJECT ObjectName SyntaxPart WriteSyntaxPart AccessPart DESCRIPTION Text"""
        # p[0] = (p[1], # object
        #        p[2], # name
        #        p[3], # syntax
        #        p[4], # write syntax
        #        p[5], # access
        #        (p[6], p[7])) # description

    def p_SyntaxPart(self, p: YaccProduction) -> None:
        """SyntaxPart : SYNTAX Syntax
        | empty"""
        if p[1]:
            p[0] = p[2]

    def p_WriteSyntaxPart(self, p: YaccProduction) -> None:
        """WriteSyntaxPart : WRITE_SYNTAX WriteSyntax
        | empty"""
        if p[1]:
            p[0] = p[2]

    def p_WriteSyntax(self, p: YaccProduction) -> None:
        """WriteSyntax : Syntax"""
        p[0] = ("WriteSyntax", p[1])

    def p_AccessPart(self, p: YaccProduction) -> None:
        """AccessPart : MIN_ACCESS Access
        | empty"""
        if p[1]:
            p[0] = (p[1], p[2])

    def p_agentCapabilitiesClause(self, p: YaccProduction) -> None:
        """agentCapabilitiesClause : LOWERCASE_IDENTIFIER AGENT_CAPABILITIES PRODUCT_RELEASE Text STATUS Status DESCRIPTION Text ReferPart ModulePart_Capabilities COLON_COLON_EQUAL '{' objectIdentifier '}'"""
        p[0] = (
            "agentCapabilitiesClause",
            p[1],  # id
            #   p[2], # AGENT_CAPABILITIES
            (p[3], p[4]),  # product release
            p[6],  # status
            (p[7], p[8]),  # description
            p[9],  # reference
            #   p[10], # module capabilities
            p[13],
        )  # objectIdentifier

    def p_ModulePart_Capabilities(self, p: YaccProduction) -> None:
        """ModulePart_Capabilities : Modules_Capabilities
        | empty"""
        # if p[1]:
        #  p[0] = p[1]

    def p_Modules_Capabilities(self, p: YaccProduction) -> None:
        """Modules_Capabilities : Modules_Capabilities Module_Capabilities
        | Module_Capabilities"""
        # n = len(p)
        # if n == 3:
        #  p[0] = ('Modules_Capabilities', p[1][1] + [p[2]])
        # elif n == 2:
        #  p[0] = ('Modules_Capabilities', [p[1]])

    def p_Module_Capabilities(self, p: YaccProduction) -> None:
        """Module_Capabilities : SUPPORTS ModuleName_Capabilities INCLUDES '{' CapabilitiesGroups '}' VariationPart"""
        # p[0] = ('Module_Capabilities', (p[1], p[2]), # supports
        #                               (p[3], p[5]), # includes
        #                               p[7]) # variations

    def p_CapabilitiesGroups(self, p: YaccProduction) -> None:
        """CapabilitiesGroups : CapabilitiesGroups ',' CapabilitiesGroup
        | CapabilitiesGroup"""
        # n = len(p)
        # if n == 4:
        #  p[0] = ('CapabilitiesGroups', p[1][1] + [p[3]])
        # elif n == 2:
        #  p[0] = ('CapabilitiesGroups', [p[1]])

    def p_CapabilitiesGroup(self, p: YaccProduction) -> None:
        """CapabilitiesGroup : objectIdentifier"""
        # p[0] = ('CapabilitiesGroup', p[1])

    def p_ModuleName_Capabilities(self, p: YaccProduction) -> None:
        """ModuleName_Capabilities : UPPERCASE_IDENTIFIER objectIdentifier
        | UPPERCASE_IDENTIFIER"""
        # n = len(p)
        # if n == 2:
        #  p[0] = ('ModuleName_Capabilities', p[1])
        # elif n == 3:
        #  p[0] = ('ModuleName_Capabilities', p[1], p[2])

    def p_VariationPart(self, p: YaccProduction) -> None:
        """VariationPart : Variations
        | empty"""
        # if p[1]:
        #  p[0] = p[1]

    def p_Variations(self, p: YaccProduction) -> None:
        """Variations : Variations Variation
        | Variation"""
        # n = len(p)
        # if n == 3:
        #  p[0] = ('Variations', p[1][1] + [p[2]])
        # elif n == 2:
        #  p[0] = ('Variations', [p[1]])        pass

    def p_Variation(self, p: YaccProduction) -> None:
        """Variation : VARIATION ObjectName SyntaxPart WriteSyntaxPart VariationAccessPart CreationPart DefValPart DESCRIPTION Text"""
        # p[0] = (p[1], # variation
        #        p[2], # name
        #        p[3], # syntax
        #        p[4], # write syntax
        #        p[5], # access
        #        p[6], # creation
        #        p[7], # defval
        #        (p[8], p[9])) # description

    def p_VariationAccessPart(self, p: YaccProduction) -> None:
        """VariationAccessPart : ACCESS VariationAccess
        | empty"""
        # if p[1]:
        #  p[0] = (p[1], p[2])

    def p_VariationAccess(self, p: YaccProduction) -> None:
        """VariationAccess : LOWERCASE_IDENTIFIER"""
        # p[0] = p[1]

    def p_CreationPart(self, p: YaccProduction) -> None:
        """CreationPart : CREATION_REQUIRES '{' Cells '}'
        | empty"""
        if p[1]:
            p[0] = (p[1], p[3])

    def p_Cells(self, p: YaccProduction) -> None:
        """Cells : Cells ',' Cell
        | Cell"""
        n = len(p)
        if n == 4:
            p[0] = ("Cells", p[1][1] + [p[3]])
        elif n == 2:
            p[0] = ("Cells", [p[1]])

    def p_Cell(self, p: YaccProduction) -> None:
        """Cell : ObjectName"""
        p[0] = ("Cell", p[1])

    def p_empty(self, p: YaccProduction) -> None:
        """empty :"""

    # Error rule for syntax errors
    def p_error(self, p: YaccProduction) -> None:
        if p:
            raise error.PySmiParserError(f"Bad grammar near token type {p.type}, value {p.value}", lineno=p.lineno)


#
# Parser grammar relaxation follows.
#
# The classes that follow serve a purpose of encapsulating assorted functions
# into a namespace. The namespace type is not universally supported across all
# Python versions we want to run on, thus the hack with `staticmethod` decorator
# and `self` first parameter.
#

#
# SMIv1 grammar
#


# noinspection PyIncorrectDocstring
class SupportSmiV1Keywords:
    """Accept the SMIv1 keywords SMIv2 dropped.

    Chiefly ``NETWORKADDRESS``, along with the SMIv1 spellings of the types
    that survived into SMIv2 under other names.
    """

    # NETWORKADDRESS added
    @staticmethod
    def p_importedKeyword(self: "SmiV2Parser", p: YaccProduction) -> None:
        """importedKeyword : importedSMIKeyword
        | BITS
        | INTEGER32
        | IPADDRESS
        | NETWORKADDRESS
        | MANDATORY_GROUPS
        | MODULE_COMPLIANCE
        | MODULE_IDENTITY
        | OBJECT_GROUP
        | OBJECT_IDENTITY
        | OBJECT_TYPE
        | OPAQUE
        | TEXTUAL_CONVENTION
        | TIMETICKS
        | UNSIGNED32"""
        p[0] = p[1]

    # MAX is a range bound in SMIv1, and a forbidden word in SMIv2.
    @staticmethod
    def p_value(self: "SmiV2Parser", p: YaccProduction) -> None:
        """value : NEGATIVENUMBER
        | NUMBER
        | NEGATIVENUMBER64
        | NUMBER64
        | HEX_STRING
        | BIN_STRING
        | MAX"""
        p[0] = p[1]

    # NETWORKADDRESS added
    @staticmethod
    def p_typeSMIandSPPI(self: "SmiV2Parser", p: YaccProduction) -> None:
        """typeSMIandSPPI : IPADDRESS
        | NETWORKADDRESS
        | TIMETICKS
        | OPAQUE
        | INTEGER32
        | UNSIGNED32"""
        p[0] = p[1]

    # NETWORKADDRESS added
    @staticmethod
    def p_ApplicationSyntax(self: "SmiV2Parser", p: YaccProduction) -> None:
        """ApplicationSyntax : IPADDRESS anySubType
        | NETWORKADDRESS anySubType
        | COUNTER32
        | COUNTER32 integerSubType
        | GAUGE32
        | GAUGE32 integerSubType
        | UNSIGNED32
        | UNSIGNED32 integerSubType
        | TIMETICKS anySubType
        | OPAQUE
        | OPAQUE octetStringSubType
        | COUNTER64
        | COUNTER64 integerSubType"""
        n = len(p)
        if n == 2:
            p[0] = ("ApplicationSyntax", p[1])
        elif n == 3:
            p[0] = ("ApplicationSyntax", p[1], _resolve_max_bound(p[1], p[2]))

    # NETWORKADDRESS added for SEQUENCE syntax
    @staticmethod
    def p_sequenceApplicationSyntax(self: "SmiV2Parser", p: YaccProduction) -> None:
        """sequenceApplicationSyntax : IPADDRESS anySubType
        | NETWORKADDRESS anySubType
        | COUNTER32 anySubType
        | GAUGE32 anySubType
        | UNSIGNED32 anySubType
        | TIMETICKS anySubType
        | OPAQUE
        | COUNTER64 anySubType"""
        n = len(p)
        if n == 2:
            p[0] = p[1]
        elif n == 3:
            p[0] = p[1]  # XXX not supporting subtypes here


# noinspection PyIncorrectDocstring
class SupportIndex:
    """Accept a base type in an ``INDEX`` clause.

    SMIv1 lets a table be indexed by a type rather than by an object, so the
    parser has to admit one where SMIv2 expects an object name.
    """

    # SMIv1 IndexTypes added
    @staticmethod
    def p_Index(self: "SmiV2Parser", p: YaccProduction) -> None:
        """Index : ObjectName
        | typeSMIv1"""

        # libsmi: TODO: use the SYNTAX value of the correspondent
        #               OBJECT-TYPE invocation
        p[0] = (isinstance(p[1], tuple) and p[1][1][0]) or p[1]

    # for Index rule
    @staticmethod
    def p_typeSMIv1(self: "SmiV2Parser", p: YaccProduction) -> None:
        """typeSMIv1 : INTEGER
        | OCTET STRING
        | IPADDRESS
        | NETWORKADDRESS"""
        n = len(p)
        indextype = (n == 3 and p[1] + " " + p[2]) or p[1]
        p[0] = indextype


#
# Some changes in grammar to handle common mistakes in MIBs
#


# noinspection PyIncorrectDocstring
class CommaInImport:
    """Tolerate a trailing comma in an ``IMPORTS`` list."""

    # comma at the end of import list
    @staticmethod
    def p_importIdentifiers(self: "SmiV2Parser", p: YaccProduction) -> None:
        """importIdentifiers : importIdentifiers ',' importIdentifier
        | importIdentifier
        | importIdentifiers ','"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]
        elif n == 3:  # excessive comma case
            p[0] = p[1]


# noinspection PyIncorrectDocstring
class CommaInSequence:
    """Tolerate a trailing comma in a ``SEQUENCE`` list."""

    # comma at the end of sequence list
    @staticmethod
    def p_sequenceItems(self: "SmiV2Parser", p: YaccProduction) -> None:
        """sequenceItems : sequenceItems ',' sequenceItem
        | sequenceItem
        | sequenceItems ','"""
        # libsmi: TODO: might this list be emtpy?
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]
        elif n == 3:  # excessive comma case
            p[0] = p[1]


# noinspection PyIncorrectDocstring
class CommaAndSpaces:
    """Tolerate commas and spaces used interchangeably as separators."""

    # common typos handled (mix of commas and spaces)
    @staticmethod
    def p_enumItems(self: "SmiV2Parser", p: YaccProduction) -> None:
        """enumItems : enumItems ',' enumItem
        | enumItem
        | enumItems enumItem
        | enumItems ','"""
        n = len(p)
        if n == 4:
            p[0] = p[1] + [p[3]]
        elif n == 2:
            p[0] = [p[1]]
        elif n == 3:  # typo case
            if p[2] == ",":
                p[0] = p[1]
            else:
                p[0] = p[1] + [p[2]]


# noinspection PyIncorrectDocstring
class UppercaseIdentifier:
    """Tolerate an upper-case identifier where SMI requires lower case."""

    # common mistake - using UPPERCASE_IDENTIFIER
    @staticmethod
    def p_enumItem(self: "SmiV2Parser", p: YaccProduction) -> None:
        """enumItem : LOWERCASE_IDENTIFIER '(' enumNumber ')'
        | UPPERCASE_IDENTIFIER '(' enumNumber ')'"""
        p[0] = (p[1], p[3])


# noinspection PyIncorrectDocstring
class LowcaseIdentifier:
    """Tolerate a lower-case identifier where SMI requires upper case."""

    # common mistake - LOWERCASE_IDENTIFIER in symbol's name
    @staticmethod
    def p_notificationTypeClause(self: "SmiV2Parser", p: YaccProduction) -> None:
        """notificationTypeClause : fuzzy_lowercase_identifier NOTIFICATION_TYPE NotificationObjectsPart STATUS Status DESCRIPTION Text ReferPart COLON_COLON_EQUAL '{' NotificationName '}'"""  # some MIBs have uppercase and/or lowercase id
        p[0] = (
            "notificationTypeClause",
            p[1],  # id
            #  p[2], # NOTIFICATION_TYPE
            p[3],  # NotificationObjectsPart
            p[5],  # status
            (p[6], p[7]),  # description
            p[8],  # Reference
            p[11],
        )  # NotificationName aka objectIdentifier


# noinspection PyIncorrectDocstring,PyIncorrectDocstring
class CurlyBracesInEnterprises:
    """Tolerate curly braces around the ``ENTERPRISE`` symbol of a TRAP-TYPE."""

    # common mistake - curly brackets around enterprise symbol
    @staticmethod
    def p_trapTypeClause(self: "SmiV2Parser", p: YaccProduction) -> None:
        """trapTypeClause : fuzzy_lowercase_identifier TRAP_TYPE EnterprisePart VarPart DescrPart ReferPart COLON_COLON_EQUAL NUMBER"""
        # libsmi: TODO: range of number?
        p[0] = (
            "trapTypeClause",
            p[1],  # fuzzy_lowercase_identifier
            #  p[2], # TRAP_TYPE
            p[3],  # EnterprisePart (objectIdentifier)
            p[4],  # VarPart
            p[5],  # description
            p[6],  # reference
            p[8],
        )  # NUMBER

    @staticmethod
    def p_EnterprisePart(self: "SmiV2Parser", p: YaccProduction) -> None:
        """EnterprisePart : ENTERPRISE objectIdentifier
        | ENTERPRISE '{' objectIdentifier '}'"""
        n = len(p)
        if n == 3:
            p[0] = p[2]
        elif n == 5:  # common mistake case
            p[0] = p[3]


# noinspection PyIncorrectDocstring
class NoCells:
    """Tolerate a ``SEQUENCE`` with no entries."""

    # common mistake - no Cells
    @staticmethod
    def p_CreationPart(self: "SmiV2Parser", p: YaccProduction) -> None:
        """CreationPart : CREATION_REQUIRES '{' Cells '}'
        | CREATION_REQUIRES '{' '}'
        | empty"""
        n = len(p)
        if n == 5:
            p[0] = (p[1], p[3])


relaxedGrammar = {
    "supportSmiV1Keywords": [
        SupportSmiV1Keywords.p_importedKeyword,
        SupportSmiV1Keywords.p_value,
        SupportSmiV1Keywords.p_typeSMIandSPPI,
        SupportSmiV1Keywords.p_ApplicationSyntax,
        SupportSmiV1Keywords.p_sequenceApplicationSyntax,
    ],
    "supportIndex": [SupportIndex.p_Index, SupportIndex.p_typeSMIv1],
    "commaAtTheEndOfImport": [CommaInImport.p_importIdentifiers],
    "commaAtTheEndOfSequence": [CommaInSequence.p_sequenceItems],
    "mixOfCommasAndSpaces": [CommaAndSpaces.p_enumItems],
    "uppercaseIdentifier": [UppercaseIdentifier.p_enumItem],
    "lowcaseIdentifier": [LowcaseIdentifier.p_notificationTypeClause],
    "curlyBracesAroundEnterpriseInTrap": [
        CurlyBracesInEnterprises.p_trapTypeClause,
        CurlyBracesInEnterprises.p_EnterprisePart,
    ],
    "noCells": [NoCells.p_CreationPart],
}


def parserFactory(**grammarOptions: bool) -> type[SmiV2Parser]:
    """Factory function producing custom specializations of base *SmiV2Parser*
    class.

    Keyword Args:
        grammarOptions: a list of (bool) typed optional keyword parameters
                        enabling particular set of SMIv2 grammar relaxations.

    Returns:
        Specialized copy of *SmiV2Parser* class.

    Notes:
        The following SMIv2 grammar relaxation parameters are defined:

        * supportSmiV1Keywords - parses SMIv1 grammar
        * supportIndex - tolerates ASN.1 types in INDEX clause
        * commaAtTheEndOfImport - tolerates stray comma at the end of IMPORT section
        * commaAtTheEndOfSequence - tolerates stray comma at the end of sequence of elements in MIB
        * mixOfCommasAndSpaces - tolerate a mix of comma and spaces in MIB enumerations
        * uppercaseIdentifier - tolerate uppercased MIB identifiers
        * lowcaseIdentifier - tolerate lowercase MIB identifiers
        * curlyBracesAroundEnterpriseInTrap - tolerate curly braces around enterprise ID in TRAP MACRO
        * noCells - tolerate missing cells (XXX)

    Examples:

    >>> from pysmi.parser import smi
    >>> SmiV1Parser = smi.parserFactory(supportSmiV1Keywords=True, supportIndex=True)

    """
    classAttr: dict[str, Any] = {}

    for option in grammarOptions:
        if grammarOptions[option]:
            if option not in relaxedGrammar:
                raise error.PySmiError(f"Unknown parser relaxation option: {option}")

            for func in relaxedGrammar[option]:
                classAttr[func.__name__] = func

    classAttr["defaultLexer"] = lexerFactory(**grammarOptions)

    return type("SmiParser", (SmiV2Parser,), classAttr)
