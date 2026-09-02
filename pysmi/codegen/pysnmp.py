#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Rendering MIB modules as PySNMP Python modules."""

import logging
import re
from keyword import iskeyword
from time import strftime, strptime
from typing import Any, cast

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.codegen.base import (
    AbstractCodeGen,
    IndexClause,
    NamedNumbersClause,
    SequenceClause,
    SymbolsClause,
    TextClause,
    dorepr,
)
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)


@deprecated_camel_case
class PySnmpCodeGen(AbstractCodeGen):
    """Builds PySNMP-specific Python code representing MIB module supplied
    in form of an Abstract Syntax Tree on input.

    Instance of this class is supposed to be passed to *MibCompiler*,
    the rest is internal to *MibCompiler*.
    """

    defaultMibPackages = ("pysnmp.smi.mibs", "pysnmp_mibs")

    symsTable = {
        "MODULE-IDENTITY": ("ModuleIdentity",),
        "OBJECT-TYPE": ("MibScalar", "MibTable", "MibTableRow", "MibTableColumn"),
        "NOTIFICATION-TYPE": ("NotificationType",),
        "TEXTUAL-CONVENTION": ("TextualConvention",),
        "MODULE-COMPLIANCE": ("ModuleCompliance",),
        "OBJECT-GROUP": ("ObjectGroup",),
        "NOTIFICATION-GROUP": ("NotificationGroup",),
        "AGENT-CAPABILITIES": ("AgentCapabilities",),
        "OBJECT-IDENTITY": ("ObjectIdentity",),
        "TRAP-TYPE": ("NotificationType",),  # smidump always uses NotificationType
        "BITS": ("Bits",),
    }

    constImports = {
        "ASN1": ("Integer", "OctetString", "ObjectIdentifier"),
        "ASN1-ENUMERATION": ("NamedValues",),
        "ASN1-REFINEMENT": (
            "ConstraintsUnion",
            "ConstraintsIntersection",
            "SingleValueConstraint",
            "ValueRangeConstraint",
            "ValueSizeConstraint",
        ),
        "SNMPv2-SMI": (
            "iso",
            "Bits",  # XXX
            "Integer32",  # XXX
            "TimeTicks",  # bug in some IETF MIBs
            "Counter32",  # bug in some IETF MIBs (e.g. DSA-MIB)
            "Counter64",  # bug in some MIBs (e.g.A3COM-HUAWEI-LswINF-MIB)
            "NOTIFICATION-TYPE",  # bug in some MIBs (e.g. A3COM-HUAWEI-DHCPSNOOP-MIB)
            "Gauge32",  # bug in some IETF MIBs (e.g. DSA-MIB)
            "MODULE-IDENTITY",
            "OBJECT-TYPE",
            "OBJECT-IDENTITY",
            "Unsigned32",
            "IpAddress",  # XXX
            "MibIdentifier",
        ),  # OBJECT IDENTIFIER
        "SNMPv2-TC": (
            "DisplayString",
            "TEXTUAL-CONVENTION",
        ),  # XXX
        "SNMPv2-CONF": (
            "MODULE-COMPLIANCE",
            "NOTIFICATION-GROUP",
        ),  # XXX
    }

    # never compile these, they either:
    # - define MACROs (implementation supplies them)
    # - or carry conflicting OIDs (so that all IMPORT's of them will be rewritten)
    # - or have manual fixes
    # - or import base ASN.1 types from implementation-specific MIBs
    fakeMibs = ("ASN1", "ASN1-ENUMERATION", "ASN1-REFINEMENT")
    baseMibs = (
        "PYSNMP-USM-MIB",
        "SNMP-FRAMEWORK-MIB",
        "SNMP-TARGET-MIB",
        "TRANSPORT-ADDRESS-MIB",
        "INET-ADDRESS-MIB",
        *AbstractCodeGen.baseMibs,
    )
    """MIB modules that are never compiled.

    These carry ASN.1 MACRO definitions or base types that pysnmp implements
    itself, so a :py:class:`~pysmi.searcher.stub.StubSearcher` built from this
    tuple reports them as up to date and the compiler leaves them alone.
    """

    baseTypes = ["Integer", "Integer32", "Bits", "ObjectIdentifier", "OctetString"]

    typeClasses = {
        "COUNTER32": "Counter32",
        "COUNTER64": "Counter64",
        "GAUGE32": "Gauge32",
        "INTEGER": "Integer32",  # XXX
        "INTEGER32": "Integer32",
        "IPADDRESS": "IpAddress",
        "NETWORKADDRESS": "IpAddress",
        "OBJECT IDENTIFIER": "ObjectIdentifier",
        "OCTET STRING": "OctetString",
        "OPAQUE": "Opaque",
        "TIMETICKS": "TimeTicks",
        "UNSIGNED32": "Unsigned32",
        "Counter": "Counter32",
        "Gauge": "Gauge32",
        "NetworkAddress": "IpAddress",  # RFC1065-SMI, RFC1155-SMI -> SNMPv2-SMI
        "nullSpecific": "zeroDotZero",  # RFC1158-MIB -> SNMPv2-SMI
        "ipRoutingTable": "ipRouteTable",  # RFC1158-MIB -> RFC1213-MIB
        "snmpEnableAuthTraps": "snmpEnableAuthenTraps",  # RFC1158-MIB -> SNMPv2-MIB
    }

    smiv1IdxTypes = ["INTEGER", "OCTET STRING", "IPADDRESS", "NETWORKADDRESS"]

    ifTextStr = "if mibBuilder.loadTexts: "
    indent = " " * 4
    fakeidx = 1000  # starting index for fake symbols

    # Template for version-guarded status assignment (duplicated across many
    # codegen methods; extracted to satisfy SonarQube S1192).
    _STATUS_VERSION_TEMPLATE = """\
if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):
    %(name)s = %(name)s%(status)s
"""

    # Template for the setObjects loop block used when the number of objects
    # exceeds 255 (duplicated across several codegen methods).
    _SET_OBJECTS_LOOP_TEMPLATE = """
for _%(name)s_obj in [%(objects)s]:
    if getattr(mibBuilder, 'version', 0) < (4, 4, 2):
        # WARNING: leading objects get lost here! Upgrade your pysnmp version!
        %(name)s = %(name)s.setObjects(*_%(name)s_obj)
    else:
        %(name)s = %(name)s.setObjects(*_%(name)s_obj, **dict(append=True))\
"""

    # Variant of the setObjects loop template that ends with a newline rather
    # than a line-continuation backslash (used by gen_compliances).
    _SET_OBJECTS_LOOP_TEMPLATE_NL = """
for _%(name)s_obj in [%(objects)s]:
    if getattr(mibBuilder, 'version', 0) < (4, 4, 2):
        # WARNING: leading objects get lost here! Upgrade your pysnmp version!
        %(name)s = %(name)s.setObjects(*_%(name)s_obj)
    else:
        %(name)s = %(name)s.setObjects(*_%(name)s_obj, **dict(append=True))

"""

    # Common string fragments used in subtype constraint generation.
    _SET_OBJECTS_CALL = ".setObjects("
    _SUBTYPE_SPEC_CALL = ".subtype(subtypeSpec="
    _SUBTYPE_SPEC_CLASSMODE = "subtypeSpec = %s.subtypeSpec + "
    _CONSTRAINTS_UNION = "ConstraintsUnion("

    def __init__(self) -> None:
        self._snmpTypes = set(self.typeClasses.values())
        self._snmpTypes.add("Bits")
        self._rows: set[str] = set()
        self._cols: dict[str, str] = {}  # k, v = name, datatype
        self._exports: set[str] = set()
        self._seenSyms: set[str] = set()
        self._importMap: dict[str, str] = {}
        self._out: dict[str, Any] = {}  # k, v = name, generated code
        self._moduleIdentityOid: str | None = None
        self._moduleRevision: str | None = None
        self.moduleName: list[str] = ["DUMMY"]
        self.genRules: dict[str, Any] = {"text": True}
        self.symbolTable: dict[str, Any] = {}

    def sym_trans(self, symbol: str) -> tuple[Any, ...]:
        """Map an SMI construct name onto the PySNMP classes it needs.

        Args:
            symbol: name as it appears in the MIB, such as ``OBJECT-TYPE``

        Returns:
            The classes that construct is rendered with, or the name unchanged
            when it is not an SMI construct.
        """
        if symbol in self.symsTable:
            return self.symsTable[symbol]

        return (symbol,)

    @staticmethod
    def trans_opers(symbol: str) -> Any:
        """Turn a MIB symbol into a usable Python identifier.

        Hyphens become underscores, and a name that collides with a Python
        keyword is prefixed with ``pysmi_``.

        Args:
            symbol: symbol name as written in the MIB

        Returns:
            The Python-safe form of the name.
        """
        if iskeyword(symbol):
            symbol = "pysmi_" + symbol

        return symbol.replace("-", "_")

    def prep_data(self, pdata: Any, classmode: bool = False) -> list[Any]:
        """Convert a parse subtree into the values a clause handler expects.

        Each element that is a tagged tuple is dispatched through
        ``handlersTable`` and replaced by whatever that handler returns.
        Children are converted before their parent, so by the time a clause
        handler runs, its ``data`` holds rendered source fragments rather than
        raw parse nodes.

        Args:
            pdata: parse subtree
            classmode: the subtree sits inside a type declaration

        Returns:
            One converted value per element of the subtree.
        """
        data = []

        for el in pdata:
            if not isinstance(el, tuple):
                data.append(el)

            elif len(el) == 1:
                data.append(el[0])

            else:
                data.append(
                    self.handlersTable[el[0]](self, self.prep_data(el[1:], classmode=classmode), classmode=classmode)
                )

        return data

    def gen_imports(self, imports: dict[str, Any]) -> tuple[Any, ...]:
        """Render the module's import statements.

        SMIv1 imports are rewritten to their SMIv2 equivalents, and the classes
        every generated module needs are merged in, before one
        ``mibBuilder.importSymbols()`` call is emitted per module imported.

        Args:
            imports: imported symbols, keyed by the module they come from

        Returns:
            The import statements, and the names of the modules imported,
            sorted.
        """
        outStr = ""

        # conversion to SNMPv2
        toDel = []
        for module in list(imports):
            if module in self.convertImportv2:
                for symbol in imports[module]:
                    if symbol in self.convertImportv2[module]:
                        toDel.append((module, symbol))

                        for newImport in self.convertImportv2[module][symbol]:
                            newModule, newSymbol = newImport

                            if newModule in imports:
                                imports[newModule].append(newSymbol)
                            else:
                                imports[newModule] = [newSymbol]

        # removing converted symbols
        for d in toDel:
            imports[d[0]].remove(d[1])

        # merging mib and constant imports
        for module in self.constImports:
            if module in imports:
                imports[module] += self.constImports[module]
            else:
                imports[module] = self.constImports[module]

        for module in sorted(imports):
            symbols: tuple[Any, ...] = ()

            for symbol in sorted(set(imports[module])):
                symbols += self.sym_trans(symbol)

            if symbols:
                self._seenSyms.update([self.trans_opers(s) for s in symbols])
                self._importMap.update([(self.trans_opers(s), module) for s in symbols])

                outStr += ", ".join([self.trans_opers(s) for s in symbols])
                if len(symbols) < 2:
                    outStr += ","
                quotedSymbols = '", "'.join((module, *symbols))
                outStr += f' = mibBuilder.importSymbols("{quotedSymbols}")\n'

        return outStr, tuple(sorted(imports))

    def gen_exports(
        self,
    ) -> str:
        """Render the ``mibBuilder.exportSymbols()`` call for this module.

        The call is split across several statements when the module defines
        more symbols than may be passed as keyword arguments at once.

        Returns:
            The export statements, or an empty string when nothing is exported.
        """
        exports = sorted(self._exports)
        if not exports:
            return ""

        numFuncCalls = len(exports) // 254 + 1

        outStr = ""

        for idx in range(numFuncCalls):
            outStr += 'mibBuilder.exportSymbols("' + self.moduleName[0] + '", '
            outStr += ", ".join(exports[254 * idx : 254 * (idx + 1)]) + ")\n"

        return outStr

    # noinspection PyMethodMayBeStatic
    def gen_label(self, symbol: str, classmode: bool = False) -> str:
        """Render the original MIB name for a symbol that had to be renamed.

        Only names that :py:meth:`trans_opers` would alter need this; anything
        else already reads the same in Python as in the MIB.

        Args:
            symbol: symbol name as written in the MIB
            classmode: render as a class attribute rather than a setter call

        Returns:
            The label assignment or setter call, empty when the name survived
            translation unchanged.
        """
        if "-" in symbol or iskeyword(symbol):
            return (classmode and 'label = "' + symbol + '"\n') or '.setLabel("' + symbol + '")'

        return ""

    def add_to_exports(self, symbol: str, moduleIdentity: bool = False) -> None:
        """Mark a symbol to be exported from the generated module.

        Args:
            symbol: Python-safe symbol name
            moduleIdentity: also export it as the module's identity
        """
        if moduleIdentity:
            self._exports.add(f"PYSNMP_MODULE_ID={symbol}")

        self._exports.add(f"{symbol}={symbol}")
        self._seenSyms.add(symbol)

    # noinspection PyUnusedLocal
    def reg_sym(self, symbol: str, outStr: str, oidStr: str = "", moduleIdentity: bool = False) -> None:
        """Record the source rendered for a symbol and mark it for export.

        Args:
            symbol: Python-safe symbol name
            outStr: source rendered for it
            oidStr: its OID, used when the symbol is the module identity
            moduleIdentity: the symbol is this module's MODULE-IDENTITY

        Raises:
            PySmiSemanticError: the module defines this symbol twice, or
                declares a second module identity.
        """
        if symbol in self._seenSyms and symbol not in self._importMap:
            raise error.PySmiSemanticError(f"Duplicate symbol found: {symbol}")

        self.add_to_exports(symbol, moduleIdentity)
        self._out[symbol] = outStr

        if moduleIdentity:
            if self._moduleIdentityOid:
                raise error.PySmiSemanticError("Duplicate module identity")
            # TODO: turning literal tuple into a string - hackerish
            self._moduleIdentityOid = ".".join(oidStr.split(", "))[1:-1]

    def gen_numeric_oid(self, oid: tuple[Any, ...]) -> tuple[Any, ...]:
        """Resolve an OID to numbers, following names into other modules.

        Every name in the OID is looked up in the symbol table and replaced by
        the OID it stands for, recursively, until only numbers are left.

        Args:
            oid: sub-identifiers, each a number or a name paired with its module

        Returns:
            The fully numeric OID.

        Raises:
            PySmiSemanticError: a name refers to a module or symbol that is not
                in the symbol table.
        """
        numericOid: tuple[Any, ...] = ()

        for part in oid:
            if isinstance(part, tuple):
                parent, module = part

                if parent == "iso":
                    numericOid += (1,)
                    continue

                if module not in self.symbolTable:
                    # XXX do getname for possible future borrowed mibs
                    raise error.PySmiSemanticError(f'no module "{module}" in symbolTable')

                if parent not in self.symbolTable[module]:
                    raise error.PySmiSemanticError(f'no symbol "{parent}" in module "{module}"')

                numericOid += self.gen_numeric_oid(self.symbolTable[module][parent]["oid"])

            else:
                numericOid += (part,)

        return numericOid

    def get_base_type(self, symName: str, module: str) -> tuple[Any, ...]:
        """Resolve a type to the base type it is ultimately derived from.

        Derived types are followed up the chain, gathering the restrictions
        imposed along the way, so that a value can be rendered as the base type
        it will really be stored as.

        Args:
            symName: type name
            module: module that defines it

        Returns:
            The base type and the accumulated subtype restrictions.

        Raises:
            PySmiSemanticError: the module or symbol is not in the symbol
                table, or the symbol has no syntax.
        """
        if module not in self.symbolTable:
            raise error.PySmiSemanticError(f'no module "{module}" in symbolTable')

        if symName not in self.symbolTable[module]:
            raise error.PySmiSemanticError(f'no symbol "{symName}" in module "{module}"')

        symType, symSubtype = self.symbolTable[module][symName].get("syntax", (("", ""), ""))

        if not symType[0]:
            raise error.PySmiSemanticError(f'unknown type for symbol "{symName}"')

        if symType[0] in self.baseTypes:
            return symType, symSubtype

        else:
            baseSymType, baseSymSubtype = self.get_base_type(*symType)

            if isinstance(baseSymSubtype, list):
                if isinstance(symSubtype, list):
                    symSubtype += baseSymSubtype
                else:
                    symSubtype = baseSymSubtype

            return baseSymType, symSubtype

    # Clause generation functions

    # noinspection PyUnusedLocal
    def gen_agent_capabilities(self, data: Any, classmode: bool = False) -> Any:
        """Render an AGENT-CAPABILITIES clause as an ``AgentCapabilities`` object.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, productRelease, status, description, reference, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid
        outStr = name + " = AgentCapabilities(" + oidStr + ")" + label + "\n"

        if productRelease:
            outStr += """\
if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):
    {name} = {name}{productRelease}
""".format(**dict(name=name, productRelease=productRelease))

        if status:
            outStr += self._STATUS_VERSION_TEMPLATE % dict(name=name, status=status)

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_module_identity(self, data: Any, classmode: bool = False) -> str:
        """Render a MODULE-IDENTITY clause as a ``ModuleIdentity`` object.

        The revision descriptions are guarded, because older PySNMP versions
        have no method to set them.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, lastUpdated, organization, contactInfo, description, revisionsAndDescrs, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid

        outStr: str = name + " = ModuleIdentity(" + oidStr + ")" + label + "\n"

        if revisionsAndDescrs:
            last_revision, revisions, descriptions = revisionsAndDescrs

            self._moduleRevision = last_revision

            if revisions:
                outStr += name + revisions + "\n"

            if self.genRules["text"] and descriptions:
                outStr += """
if getattr(mibBuilder, 'version', (0, 0, 0)) > (4, 4, 0):
    {ifTextStr}{name}{descriptions}
""".format(**dict(ifTextStr=self.ifTextStr, name=name, descriptions=descriptions))

        if lastUpdated:
            outStr += self.ifTextStr + name + lastUpdated + "\n"

        if organization:
            outStr += self.ifTextStr + name + organization + "\n"

        if self.genRules["text"] and contactInfo:
            outStr += self.ifTextStr + name + contactInfo + "\n"

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        self.reg_sym(name, outStr, oidStr, moduleIdentity=True)

        return outStr

    # noinspection PyUnusedLocal
    def gen_module_compliance(self, data: Any, classmode: bool = False) -> str:
        """Render a MODULE-COMPLIANCE clause as a ``ModuleCompliance`` object.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, status, description, reference, compliances, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid
        outStr: str = name + " = ModuleCompliance(" + oidStr + ")" + label
        outStr += compliances + "\n"

        if status:
            outStr += self._STATUS_VERSION_TEMPLATE % dict(name=name, status=status)

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_notification_group(self, data: Any, classmode: bool = False) -> str:
        """Render a NOTIFICATION-GROUP clause as a ``NotificationGroup`` object.

        The objects are set in batches when the group names more of them than
        may be passed as arguments at once.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, objects, status, description, reference, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid

        outStr: str = name + " = NotificationGroup(" + oidStr + ")" + label

        if objects:
            objects = [
                '("' + self._importMap.get(obj, self.moduleName[0]) + '", "' + self.trans_opers(obj) + '")'
                for obj in objects
            ]

            numFuncCalls = len(objects) // 255 + 1

            if numFuncCalls > 1:
                objStrParts = []

                for idx in range(numFuncCalls):
                    objStrParts.append("[" + ", ".join(objects[255 * idx : 255 * (idx + 1)]) + "]")

                outStr += self._SET_OBJECTS_LOOP_TEMPLATE % dict(name=name, objects=", ".join(objStrParts))

            else:
                outStr += self._SET_OBJECTS_CALL + ", ".join(objects) + ")"

        outStr += "\n"

        if status:
            outStr += self._STATUS_VERSION_TEMPLATE % dict(name=name, status=status)

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_notification_type(self, data: Any, classmode: bool = False) -> str:
        """Render a NOTIFICATION-TYPE clause as a ``NotificationType`` object.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, objects, status, description, reference, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid

        outStr: str = name + " = NotificationType(" + oidStr + ")" + label

        if objects:
            objects = [
                '("' + self._importMap.get(obj, self.moduleName[0]) + '", "' + self.trans_opers(obj) + '")'
                for obj in objects
            ]

            numFuncCalls = len(objects) // 255 + 1

            if numFuncCalls > 1:
                objStrParts = []

                for idx in range(numFuncCalls):
                    objStrParts.append("[" + ", ".join(objects[255 * idx : 255 * (idx + 1)]) + "]")

                outStr += self._SET_OBJECTS_LOOP_TEMPLATE % dict(name=name, objects=", ".join(objStrParts))

            else:
                outStr += self._SET_OBJECTS_CALL + ", ".join(objects) + ")"

        outStr += "\n"

        if status:
            outStr += self.ifTextStr + name + status + "\n"

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_object_group(self, data: Any, classmode: bool = False) -> str:
        """Render an OBJECT-GROUP clause as an ``ObjectGroup`` object.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, objects, status, description, reference, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid

        outStr: str = name + " = ObjectGroup(" + oidStr + ")" + label

        if objects:
            objects = [
                '("' + self._importMap.get(obj, self.moduleName[0]) + '", "' + self.trans_opers(obj) + '")'
                for obj in objects
            ]

            numFuncCalls = len(objects) // 255 + 1

            if numFuncCalls > 1:
                objStrParts = []

                for idx in range(numFuncCalls):
                    objStrParts.append("[" + ", ".join(objects[255 * idx : 255 * (idx + 1)]) + "]")

                outStr += """
for _{name}_obj in [{objects}]:
    if getattr(mibBuilder, 'version', 0) < (4, 4, 2):
        # WARNING: leading objects get lost here!
        {name} = {name}.setObjects(*_{name}_obj)
    else:
        {name} = {name}.setObjects(*_{name}_obj, **dict(append=True))\
""".format(**dict(name=name, objects=", ".join(objStrParts)))

            else:
                outStr += self._SET_OBJECTS_CALL + ", ".join(objects) + ")"

        outStr += "\n"

        if status:
            outStr += self._STATUS_VERSION_TEMPLATE % dict(name=name, status=status)

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_object_identity(self, data: Any, classmode: bool = False) -> Any:
        """Render an OBJECT-IDENTITY clause as an ``ObjectIdentity`` object.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, status, description, reference, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid
        outStr = name + " = ObjectIdentity(" + oidStr + ")" + label + "\n"

        if status:
            outStr += self.ifTextStr + name + status + "\n"

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_object_type(self, data: Any, classmode: bool = False) -> str:
        """Render an OBJECT-TYPE clause as the object it describes.

        Which class is used depends on what the object turned out to be: a
        column if the symbol table recorded it as one, a table or row if its
        syntax says so, and a scalar otherwise. AUGMENTS is rendered as a
        registration against the row being augmented, whose index names are
        then adopted. An SMIv1 index naming a bare type also emits the
        synthetic column that :py:meth:`gen_table_index` prepared.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, syntax, units, maxaccess, status, description, reference, augmention, index, defval, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid

        indexStr, fakeStrlist, fakeSyms = index or ("", "", [])
        subtype = (syntax[0] == "Bits" and "Bits()" + syntax[1]) or syntax[1]  # Bits hack #1

        classtype = self.typeClasses.get(syntax[0], syntax[0])
        classtype = self.trans_opers(classtype)
        classtype = (syntax[0] == "Bits" and "MibScalar") or classtype  # Bits hack #2
        classtype = (name in self.symbolTable[self.moduleName[0]]["_symtable_cols"] and "MibTableColumn") or classtype

        defval = self.gen_def_val(defval, objname=name)

        outStr: str = name + " = " + classtype + "(" + oidStr + ", " + subtype + (defval or "") + ")" + label
        outStr += units or ""
        outStr += maxaccess or ""
        outStr += indexStr or ""
        outStr += "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        if augmention:
            augmention = self.trans_opers(augmention)
            outStr += (
                augmention
                + '.registerAugmentions(("'
                + self._importMap.get(name, self.moduleName[0])
                + '", "'
                + name
                + '"))\n'
            )
            outStr += name + ".setIndexNames(*" + augmention + ".getIndexNames())\n"

        if status:
            outStr += self.ifTextStr + name + status + "\n"

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        self.reg_sym(name, outStr, parentOid)

        if fakeSyms:  # fake symbols for INDEX to support SMIv1
            for idx, fakeSym in enumerate(fakeSyms):
                fakeOutStr = fakeStrlist[idx] % oidStr
                self.reg_sym(fakeSym, fakeOutStr, oidStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_trap_type(self, data: Any, classmode: bool = False) -> Any:
        """Render a TRAP-TYPE clause as a ``NotificationType`` object.

        SMIv1 traps have no OID of their own; theirs is built from the
        enterprise OID, a zero, and the trap number, which is how SMIv2 names
        the same notification.

        Args:
            data: rendered clause values
            classmode: unused; the clause never appears in a type declaration

        Returns:
            Source for the object and its texts.
        """
        name, enterprise, objects, description, reference, value = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        enterpriseStr, _parentOid = enterprise

        outStr = name + " = NotificationType(" + enterpriseStr + " + (0," + str(value) + "))" + label

        if objects:
            objects = [
                '("' + self._importMap.get(obj, self.moduleName[0]) + '", "' + self.trans_opers(obj) + '")'
                for obj in objects
            ]

            numFuncCalls = len(objects) // 255 + 1

            if numFuncCalls > 1:
                objStrParts = []

                for idx in range(numFuncCalls):
                    objStrParts.append("[" + ", ".join(objects[255 * idx : 255 * (idx + 1)]) + "]")

                outStr += self._SET_OBJECTS_LOOP_TEMPLATE % dict(name=name, objects=", ".join(objStrParts))

            else:
                outStr += self._SET_OBJECTS_CALL + ", ".join(objects) + ")"

        outStr += "\n"

        if self.genRules["text"] and description:
            outStr += self.ifTextStr + name + description + "\n"

        if self.genRules["text"] and reference:
            outStr += self.ifTextStr + name + reference + "\n"

        self.reg_sym(name, outStr, enterpriseStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_type_declaration(self, data: Any, classmode: bool = False) -> str:
        """Render a type declaration as a Python class.

        A declaration with no parent type is a SEQUENCE, which PySNMP does not
        represent, and is skipped.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            Source for the class.
        """
        outStr = ""

        name, declaration = data

        if declaration:
            parentType, attrs = declaration
            if parentType:  # skipping SEQUENCE case
                name = self.trans_opers(name)
                outStr = "class " + name + "(" + parentType + "):\n" + attrs + "\n"
                self.reg_sym(name, outStr)

        return outStr

    # noinspection PyUnusedLocal
    def gen_value_declaration(self, data: Any, classmode: bool = False) -> str:
        """Render a plain OID assignment as a ``MibIdentifier``.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            Source for the object.
        """
        name, oid = data

        label = self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, _parentOid = oid
        outStr: str = name + " = MibIdentifier(" + oidStr + ")" + label + "\n"

        self.reg_sym(name, outStr, oidStr)

        return outStr

    # Subparts generation functions

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def ft_names(self, data: Any, classmode: bool = False) -> Any:
        """Return a symbol's name paired with the module it comes from.

        Args:
            symbol: symbol name

        Returns:
            The defining module and the symbol.
        """
        names = data[0]
        return names

    def gen_bit_names(self, data: SymbolsClause, classmode: bool = False) -> Any:
        """Return the names listed in a BITS or enumeration clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The names, in the order they were written.
        """
        names = data[0]
        return names

    def gen_bits(self, data: NamedNumbersClause, classmode: bool = False) -> tuple[str, str]:
        """Render a BITS clause as named values.

        The values are built in batches when there are more of them than may be
        passed as arguments at once.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a clone call

        Returns:
            The ``Bits`` type and the source that names its values.
        """
        bits = data[0]

        namedval = ['("' + bit[0] + '", ' + str(bit[1]) + ")" for bit in bits]

        numFuncCalls = len(namedval) // 255 + 1

        funcCalls = ""
        for idx in range(numFuncCalls):
            funcCalls += "NamedValues(" + ", ".join(namedval[255 * idx : 255 * (idx + 1)]) + ") + "

        funcCalls = funcCalls[:-3]

        outStr = (
            classmode and self.indent + "namedValues = " + funcCalls + "\n"
        ) or ".clone(namedValues=" + funcCalls + ")"

        return "Bits", outStr

    # noinspection PyUnusedLocal
    def gen_compliances(self, data: Any, classmode: bool = False) -> str:
        """Render the objects a MODULE-COMPLIANCE clause requires.

        The objects are set in a loop when the clause names more of them than
        may be passed as arguments at once.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            Source setting the required objects, empty when none are named.
        """
        if not data[0]:
            return ""

        objects = []

        for complianceModule in data[0]:
            name = complianceModule[0] or self.moduleName[0]
            objects += ['("' + name + '", "' + self.trans_opers(compl) + '")' for compl in complianceModule[1]]

        outStr = ""

        numFuncCalls = len(objects) // 255 + 1

        if numFuncCalls > 1:
            objStrParts = []

            for idx in range(numFuncCalls):
                objStrParts.append("[" + ", ".join(objects[255 * idx : 255 * (idx + 1)]) + "]")

            outStr += self._SET_OBJECTS_LOOP_TEMPLATE_NL % dict(name=name, objects=", ".join(objStrParts))

        else:
            outStr += self._SET_OBJECTS_CALL + ", ".join(objects) + ")\n"

        return outStr

    # noinspection PyUnusedLocal
    def gen_conceptual_table(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Note the row a table contains and return the table's class.

        The row name is remembered so that :py:meth:`gen_row` can recognise it
        later as a row rather than an ordinary type.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The ``MibTable`` class and no subtype.
        """
        row = data[0]
        if row[1] and row[1][-2:] == "()":
            row = row[1][:-2]
            self._rows.add(row)

        return "MibTable", ""

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_contact_info(self, data: TextClause, classmode: bool = False) -> str:
        """Render a CONTACT-INFO clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            A ``setContactInfo()`` call.
        """
        text = self.textFilter("contact-info", data[0])
        return ".setContactInfo(" + dorepr(text) + ")"

    # noinspection PyUnusedLocal
    def gen_display_hint(self, data: TextClause, classmode: bool = False) -> str:
        """Render a DISPLAY-HINT as a class attribute.

        Args:
            data: rendered clause values
            classmode: unused; a display hint only appears in a type declaration

        Returns:
            The attribute assignment.
        """
        return self.indent + "displayHint = " + dorepr(data[0]) + "\n"

    # noinspection PyUnusedLocal
    def gen_def_val(self, data: Any, classmode: bool = False, objname: str | None = None) -> "bool | list[Any] | str":
        """Render a DEFVAL as a value of the object's own type.

        The default is interpreted according to the base type the object
        resolves to, which is also how several common MIB errors are absorbed:
        a hexadecimal or binary default written for an integer is converted to
        one, and an empty string given for a non-string type is dropped rather
        than rendered.

        Args:
            data: rendered clause values
            classmode: unused
            objname: object the default belongs to; without it the value is
                returned unrendered

        Returns:
            A ``clone()`` call carrying the default, or False when the default
            was unusable and should be left unset.

        Raises:
            PySmiSemanticError: the default names an unknown symbol or bit, or
                the object's type cannot carry a default.
        """
        if not data:
            return ""

        if not objname:
            return cast("bool | list[Any] | str", data)

        defval = data[0]
        defvalType = self.get_base_type(objname, self.moduleName[0])

        if isinstance(defval, int):  # number
            val = str(defval)

        elif self.is_hex(defval):  # hex
            if defvalType[0][0] in ("Integer32", "Integer"):  # common bug in MIBs
                val = str(int(defval[1:-2], 16))
            else:
                val = 'hexValue="' + defval[1:-2] + '"'

        elif self.is_binary(defval):  # binary
            binval = defval[1:-2]
            if defvalType[0][0] in ("Integer32", "Integer"):  # common bug in MIBs
                val = str(int(binval or "0", 2))
            else:
                hexval = (binval and hex(int(binval, 2))[2:]) or ""
                val = 'hexValue="' + hexval + '"'

        elif defval[0] == defval[-1] and defval[0] == '"':  # quoted string
            if defval[1:-1] == "" and defvalType[0][0] != "OctetString":  # common bug
                # a warning should be here
                return False  # we will set no default value

            val = dorepr(defval[1:-1])

        else:  # symbol (oid as defval) or name for enumeration member
            if defvalType[0][0] == "ObjectIdentifier" and (
                defval in self.symbolTable[self.moduleName[0]] or defval in self._importMap
            ):  # oid
                module = self._importMap.get(defval, self.moduleName[0])

                try:
                    val = str(self.gen_numeric_oid(self.symbolTable[module][defval]["oid"]))
                except (KeyError, error.PySmiSemanticError) as exc:
                    # or no module if it will be borrowed later
                    raise error.PySmiSemanticError(f'no symbol "{defval}" in module "{module}"') from exc

            # enumeration
            elif defvalType[0][0] in ("Integer32", "Integer") and isinstance(defvalType[1], list):
                if isinstance(defval, list):  # buggy MIB: DEFVAL { { ... } }
                    defval = [dv for dv in defval if dv in dict(defvalType[1])]
                    val = (defval and dorepr(defval[0])) or ""
                elif defval in dict(defvalType[1]):  # good MIB: DEFVAL { ... }
                    val = dorepr(defval)
                else:
                    val = ""

            elif defvalType[0][0] == "Bits":
                defvalBits = []
                bits = dict(defvalType[1])

                for bit in defval:
                    bitValue = bits.get(bit)
                    if bitValue is not None:
                        defvalBits.append((bit, bitValue))
                    else:
                        raise error.PySmiSemanticError(f'no such bit as "{bit}" for symbol "{objname}"')

                return self.gen_bits([defvalBits])[1]

            else:
                raise error.PySmiSemanticError(
                    f'unknown type "{defvalType}" for defval "{defval}" of symbol "{objname}"'
                )

        return ".clone(" + val + ")"

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_description(self, data: TextClause, classmode: bool = False) -> str:
        """Render a DESCRIPTION clause.

        A handler is called in one of two modes. In class mode it is rendering
        the body of a type declaration, so it returns an indented assignment. In
        instance mode it is decorating an object that has already been built, so
        it returns a setter call to be chained onto it.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a setter call

        Returns:
            The attribute assignment or setter call.
        """
        text = self.textFilter("description", data[0])
        return (classmode and self.indent + "description = " + dorepr(text) + "\n") or ".setDescription(" + dorepr(
            text
        ) + ")"

    # noinspection PyMethodMayBeStatic
    def gen_reference(self, data: TextClause, classmode: bool = False) -> str:
        """Render a REFERENCE clause.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a setter call

        Returns:
            The attribute assignment or setter call.
        """
        text = self.textFilter("reference", data[0])
        return (classmode and self.indent + "reference = " + dorepr(text) + "\n") or ".setReference(" + dorepr(
            text
        ) + ")"

    # noinspection PyMethodMayBeStatic
    def gen_status(self, data: TextClause, classmode: bool = False) -> str:
        """Render a STATUS clause.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a setter call

        Returns:
            The attribute assignment or setter call.
        """
        text = data[0]
        return (classmode and self.indent + "status = " + dorepr(text) + "\n") or ".setStatus(" + dorepr(text) + ")"

    # noinspection PyMethodMayBeStatic
    def gen_product_release(self, data: TextClause, classmode: bool = False) -> Any:
        """Render a PRODUCT-RELEASE clause.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a setter call

        Returns:
            The attribute assignment or setter call.
        """
        text = data[0]
        return (
            classmode and self.indent + "productRelease = " + dorepr(text) + "\n"
        ) or ".setProductRelease(" + dorepr(text) + ")"

    def gen_enum_spec(self, data: NamedNumbersClause, classmode: bool = False) -> str:
        """Render an enumeration as a value constraint and named values.

        The permitted values are constrained in batches, joined into a union,
        when there are more of them than may be passed as arguments at once.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a subtype call

        Returns:
            Source constraining the value and naming the members.
        """
        items = data[0]
        singleval = [str(item[1]) for item in items]
        outStr = (classmode and self.indent + self._SUBTYPE_SPEC_CLASSMODE) or self._SUBTYPE_SPEC_CALL
        numFuncCalls = len(singleval) / 255 + 1
        singleCall = numFuncCalls == 1
        funcCalls = ""

        outStr += (not singleCall and self._CONSTRAINTS_UNION) or ""

        for idx in range(int(numFuncCalls)):
            if funcCalls:
                funcCalls += ", "
            funcCalls += "SingleValueConstraint(" + ", ".join(singleval[255 * idx : 255 * (idx + 1)]) + ")"

        outStr += funcCalls
        outStr += (not singleCall and ((classmode and ")\n") or "))")) or ((not classmode and ")") or "\n")
        outStr += self.gen_bits(data, classmode=classmode)[1]

        return outStr

    # noinspection PyUnusedLocal
    def gen_table_index(self, data: IndexClause, classmode: bool = False) -> tuple[Any, ...]:
        """Render an INDEX clause as the row's index names.

        SMIv1 allows an index to name a bare type instead of a column. Such an
        index has no column to point at, so a synthetic one is rendered here for
        :py:meth:`gen_object_type` to emit alongside the row.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The ``setIndexNames()`` call, the source of each synthetic column,
            and their names.
        """

        def genFakeSyms(fakeidx: int, idxType: str) -> tuple[Any, ...]:
            """Render a synthetic column for an SMIv1 index.

            Args:
                fakeidx: sub-identifier to give the column
                idxType: type the index named in place of a column

            Returns:
                Source for the column, with its parent OID left to be filled in,
                and the name it was given.
            """
            fakeSymName = f"pysmiFakeCol{fakeidx}"

            objType = self.typeClasses.get(idxType, idxType)
            objType = self.trans_opers(objType)

            return (
                fakeSymName
                + " = MibTableColumn(%s + ("
                + str(fakeidx)
                + ", ), "
                + objType
                + "())\n",  # stub for parentOid
                fakeSymName,
            )

        indexes = data[0]
        idxStrlist, fakeSyms, fakeStrlist = [], [], []
        for idx in indexes:
            idxName = idx[1]
            if idxName in self.smiv1IdxTypes:  # SMIv1 support
                idxType = idxName

                fakeSymStr, idxName = genFakeSyms(self.fakeidx, idxType)
                fakeStrlist.append(fakeSymStr)
                fakeSyms.append(idxName)
                self.fakeidx += 1

            idxStrlist.append(
                "(" + str(idx[0]) + ', "' + self._importMap.get(idxName, self.moduleName[0]) + '", "' + idxName + '")'
            )

        return ".setIndexNames(" + ", ".join(idxStrlist) + ")", fakeStrlist, fakeSyms

    def gen_integer_sub_type(self, data: Any, classmode: bool = False) -> str:
        """Render an integer range restriction.

        Several ranges are joined into a union.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a subtype call

        Returns:
            Source constraining the value.
        """
        singleRange = len(data[0]) == 1

        outStr = (classmode and self.indent + self._SUBTYPE_SPEC_CLASSMODE) or self._SUBTYPE_SPEC_CALL
        outStr += (not singleRange and self._CONSTRAINTS_UNION) or ""

        for rng in data[0]:
            vmin, vmax = (len(rng) == 1 and (rng[0], rng[0])) or rng
            vmin, vmax = str(self.str2int(vmin)), str(self.str2int(vmax))
            outStr += "ValueRangeConstraint(" + vmin + ", " + vmax + ")" + ((not singleRange and ", ") or "")

        outStr += (not singleRange and ((classmode and ")") or "))")) or ((not classmode and ")") or "\n")

        return outStr

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_max_access(self, data: TextClause, classmode: bool = False) -> str:
        """Render a MAX-ACCESS clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            A ``setMaxAccess()`` call, empty for a not-accessible object, which
            is already the default.
        """
        access = data[0].replace("-", "")
        return (access != "notaccessible" and '.setMaxAccess("' + access + '")') or ""

    def gen_octet_string_sub_type(self, data: Any, classmode: bool = False) -> str:
        """Render an octet string size restriction.

        Several sizes are joined into a union, and a size that permits only one
        length is also rendered as a fixed length.

        Args:
            data: rendered clause values
            classmode: render as a class attribute rather than a subtype call

        Returns:
            Source constraining the size.
        """
        singleRange = len(data[0]) == 1

        outStr = (classmode and self.indent + self._SUBTYPE_SPEC_CLASSMODE) or self._SUBTYPE_SPEC_CALL
        outStr += (not singleRange and self._CONSTRAINTS_UNION) or ""

        for rng in data[0]:
            vmin, vmax = (len(rng) == 1 and (rng[0], rng[0])) or rng
            vmin, vmax = str(self.str2int(vmin)), str(self.str2int(vmax))
            outStr += "ValueSizeConstraint(" + vmin + ", " + vmax + ")" + ((not singleRange and ", ") or "")

        outStr += (not singleRange and ((classmode and ")") or "))")) or ((not classmode and ")") or "\n")

        if data[0]:
            # noinspection PyUnboundLocalVariable
            outStr += (
                singleRange
                and vmin == vmax
                and ((classmode and self.indent + "fixedLength = " + vmin + "\n") or ".setFixedLength(" + vmin + ")")
            ) or ""

        return outStr

    # noinspection PyUnusedLocal
    def gen_oid(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Resolve an OID and render it as numbers.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The numeric OID as source, and the name it hangs off.

        Raises:
            PySmiSemanticError: a sub-identifier is neither a name nor a number.
        """
        out: tuple[Any, ...] = ()
        parent = ""
        for el in data[0]:
            if isinstance(el, str):
                parent = self.trans_opers(el)
                out += ((parent, self._importMap.get(parent, self.moduleName[0])),)

            elif isinstance(el, int):
                out += (el,)

            elif isinstance(el, tuple):
                out += (el[1],)  # XXX Do we need to create a new object el[0]?

            else:
                raise error.PySmiSemanticError(f"unknown datatype for OID: {el}")

        return str(self.gen_numeric_oid(out)), parent

    # noinspection PyUnusedLocal
    def gen_objects(self, data: SymbolsClause, classmode: bool = False) -> list[Any]:
        """Return the names in an OBJECTS or NOTIFICATIONS list.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The Python-safe names, empty when the list is.
        """
        if data[0]:
            return [self.trans_opers(obj) for obj in data[0]]  # XXX self.trans_opers or not??
        return []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_time(self, data: Any, classmode: bool = False) -> list[Any]:
        """Render MIB timestamps as readable dates.

        Two-digit SMIv1 years are read as nineteen-hundreds. A timestamp that
        cannot be parsed at all is replaced with the epoch rather than rejected,
        because malformed dates are common and never affect the semantics of a
        module.

        Args:
            data: timestamps as written in the MIB

        Returns:
            One formatted date per timestamp.
        """
        times = []
        for timeStr in data:
            if len(timeStr) == 11:
                timeStr = "19" + timeStr
            # XXX raise in strict mode
            # elif lenTimeStr != 13:
            #  raise error.PySmiSemanticError("Invalid date %s" % t)
            try:
                times.append(strftime("%Y-%m-%d %H:%M", strptime(timeStr, "%Y%m%d%H%MZ")))

            except ValueError:
                # XXX raise in strict mode
                # raise error.PySmiSemanticError("Invalid date %s: %s" % (t, sys.exc_info()[1]))
                timeStr = "197001010000Z"  # dummy date for dates with typos
                times.append(strftime("%Y-%m-%d %H:%M", strptime(timeStr, "%Y%m%d%H%MZ")))

        return times

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_last_updated(self, data: TextClause, classmode: bool = False) -> str:
        """Render a LAST-UPDATED clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            A ``setLastUpdated()`` call.
        """
        text = data[0]
        return ".setLastUpdated(" + dorepr(text) + ")"

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_organization(self, data: TextClause, classmode: bool = False) -> str:
        """Render an ORGANIZATION clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            A ``setOrganization()`` call.
        """
        text = self.textFilter("organization", data[0])
        return ".setOrganization(" + dorepr(text) + ")"

    # noinspection PyUnusedLocal
    def gen_revisions(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Render a module's revision history.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The most recent revision date, the call setting all revision dates,
            and the call setting their descriptions.
        """
        times = self.gen_time([x[0] for x in data[0]])
        times = [dorepr(x) for x in times]

        revisions = f".setRevisions(({', '.join(times)},))"

        revisionDescriptions = ", ".join([dorepr(self.textFilter("description", x[1][1])) for x in data[0]])
        descriptions = f".setRevisionsDescriptions(({revisionDescriptions},))"

        lastRevision = data[0][0][0]

        return lastRevision, revisions, descriptions

    def gen_row(self, data: TextClause, classmode: bool = False) -> tuple[Any, ...]:
        """Render the class of a table row.

        A name the symbol table recorded as a table's row is a row; anything
        else is an ordinary type and is rendered as one.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The ``MibTableRow`` class with no subtype, or whatever
            :py:meth:`gen_simple_syntax` makes of the name.
        """
        row = data[0]
        row = self.trans_opers(row)
        return (
            row in self.symbolTable[self.moduleName[0]]["_symtable_rows"] and ("MibTableRow", "")
        ) or self.gen_simple_syntax(data, classmode=classmode)

    # noinspection PyUnusedLocal
    def gen_sequence(self, data: SequenceClause, classmode: bool = False) -> tuple[Any, ...]:
        """Record the columns of a SEQUENCE.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            Empty class and subtype; PySNMP does not represent a SEQUENCE.
        """
        cols = data[0]
        self._cols.update(cols)
        return "", ""

    def gen_simple_syntax(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Render a type reference as the object or class it becomes.

        In class mode the type is returned for the declaration to derive from.
        Otherwise it is instantiated, and the object is a scalar, which
        :py:meth:`gen_object_type` may still narrow to a column.

        Args:
            data: rendered clause values
            classmode: render for a type declaration rather than an object

        Returns:
            The type or class, and the source that builds it.
        """
        objType = data[0]
        objType = self.typeClasses.get(objType, objType)
        objType = self.trans_opers(objType)

        subtype = (len(data) == 2 and data[1]) or ""

        if classmode:
            subtype = ("%s" in subtype and subtype % objType) or subtype  # XXX hack?
            return objType, subtype

        outStr = objType + "()" + subtype

        return "MibScalar", outStr

    # noinspection PyUnusedLocal
    def gen_type_declaration_rhs(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Render the body of a type declaration.

        A textual convention carries display hint, status and text alongside its
        syntax, and derives from ``TextualConvention`` as well as the type it
        refines. A declaration whose body would be empty gets a ``pass``.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            The type derived from and the body of the class.
        """
        if len(data) == 1:
            parentType, attrs = data[0]  # just syntax

        else:
            # Textual convention
            display, status, description, reference, syntax = data
            parentType, attrs = syntax

            if parentType in self._snmpTypes:
                parentType = "TextualConvention, " + parentType

            if display:
                attrs = display + attrs

            if status:
                attrs = status + attrs

            if self.genRules["text"] and description:
                attrs = description + attrs

            if reference:
                attrs = reference + attrs

        attrs = attrs or self.indent + "pass\n"

        return parentType, attrs

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_units(self, data: TextClause, classmode: bool = False) -> str:
        """Render a UNITS clause.

        Args:
            data: rendered clause values
            classmode: unused

        Returns:
            A ``setUnits()`` call.
        """
        text = data[0]
        return ".setUnits(" + dorepr(self.textFilter("units", text)) + ")"

    handlersTable = {
        "agentCapabilitiesClause": gen_agent_capabilities,
        "moduleIdentityClause": gen_module_identity,
        "moduleComplianceClause": gen_module_compliance,
        "notificationGroupClause": gen_notification_group,
        "notificationTypeClause": gen_notification_type,
        "objectGroupClause": gen_object_group,
        "objectIdentityClause": gen_object_identity,
        "objectTypeClause": gen_object_type,
        "trapTypeClause": gen_trap_type,
        "typeDeclaration": gen_type_declaration,
        "valueDeclaration": gen_value_declaration,
        "ApplicationSyntax": gen_simple_syntax,
        "BitNames": gen_bit_names,
        "BITS": gen_bits,
        "ComplianceModules": gen_compliances,
        "conceptualTable": gen_conceptual_table,
        "CONTACT-INFO": gen_contact_info,
        "DISPLAY-HINT": gen_display_hint,
        "DEFVAL": gen_def_val,
        "DESCRIPTION": gen_description,
        "REFERENCE": gen_reference,
        "Status": gen_status,
        "PRODUCT-RELEASE": gen_product_release,
        "enumSpec": gen_enum_spec,
        "INDEX": gen_table_index,
        "integerSubType": gen_integer_sub_type,
        "MaxAccessPart": gen_max_access,
        "Notifications": gen_objects,
        "octetStringSubType": gen_octet_string_sub_type,
        "objectIdentifier": gen_oid,
        "Objects": gen_objects,
        "LAST-UPDATED": gen_last_updated,
        "ORGANIZATION": gen_organization,
        "Revisions": gen_revisions,
        "row": gen_row,
        "SEQUENCE": gen_sequence,
        "SimpleSyntax": gen_simple_syntax,
        "typeDeclarationRHS": gen_type_declaration_rhs,
        "UNITS": gen_units,
        "VarTypes": gen_objects,
        # 'a': lambda x: genXXX(x, 'CONSTRAINT')
    }

    def gen_code(self, ast: Any, symbolTable: dict[str, Any], **kwargs: Any) -> tuple[MibInfo, str]:
        """Render one parsed MIB module as PySNMP Python source.

        Symbols are emitted in the order the symbol table recorded them, so
        that a symbol is always defined before anything that refers to it.

        Args:
            ast: parse tree of a single module
            symbolTable: symbols of this module and everything it imports

        Keyword Args:
            genTexts: carry human-readable texts into the output
            textFilter: callable applied to each text before it is rendered;
                by default runs of whitespace are collapsed
            comments: lines to record in a header comment

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its Python
            source.

        Raises:
            PySmiCodegenError: a symbol in the symbol table was never rendered.
            PySmiSemanticError: the module is not internally consistent.
        """
        self.genRules["text"] = kwargs.get("genTexts", False)
        self.textFilter = kwargs.get("textFilter") or (lambda symbol, text: re.sub(r"\s+", " ", text))
        self.symbolTable = symbolTable
        self._rows.clear()
        self._cols.clear()
        self._exports.clear()
        self._seenSyms.clear()
        self._importMap.clear()
        self._out.clear()
        self._moduleIdentityOid = None
        self.moduleName[0], moduleOid, imports, declarations = ast

        out, importedModules = self.gen_imports(imports or {})

        for declr in declarations or []:
            if declr:
                clausetype = declr[0]
                classmode = clausetype == "typeDeclaration"
                self.handlersTable[declr[0]](self, self.prep_data(declr[1:], classmode), classmode)

        for sym in self.symbolTable[self.moduleName[0]]["_symtable_order"]:
            if sym not in self._out:
                raise error.PySmiCodegenError(f"No generated code for symbol {sym}")
            out += self._out[sym]

        out += self.gen_exports()

        if "comments" in kwargs:
            out = "".join([f"# {x}\n" for x in kwargs["comments"]]) + "#\n" + out
            out = f"#\n# PySNMP MIB module {self.moduleName[0]} (http://snmplabs.com/pysmi)\n" + out

        logger.debug(
            "canonical MIB name %s (%s), imported MIB(s) %s, Python code size %d bytes",
            self.moduleName[0],
            moduleOid,
            ",".join(importedModules) or "<none>",
            len(out),
            extra={
                "mib": self.moduleName[0],
                "oid": str(moduleOid),
                "imported": list(importedModules),
                "size": len(out),
            },
        )

        return MibInfo(
            oid=moduleOid,
            identity=self._moduleIdentityOid,
            name=self.moduleName[0],
            revision=self._moduleRevision,
            oids=[],
            enterprise=None,
            compliance=[],
            imported=tuple(x for x in importedModules if x not in self.fakeMibs),
        ), out

    def gen_index(self, processed: dict[str, Any], **kwargs: Any) -> str:
        """Render an index mapping OIDs to the modules that define them.

        Args:
            processed: compilation outcome per module, as reported by
                :py:class:`~pysmi.compiler.MibCompiler`

        Keyword Args:
            comments: lines to record in a header comment

        Returns:
            Python source for the index module.
        """
        out = "\nfrom pysnmp.proto.rfc1902 import ObjectName\n\noidToMibMap = {\n"
        count = 0
        for module, status in processed.items():
            value = getattr(status, "oid", None)
            if value:
                out += f'ObjectName("{value}"): "{module}",\n'
                count += 1
        out += "}\n"

        if "comments" in kwargs:
            out = "".join([f"# {x}\n" for x in kwargs["comments"]]) + "#\n" + out
            out = "#\n# PySNMP MIB indices (http://snmplabs.com/pysmi)\n" + out

        logger.debug(
            "OID->MIB index built, %d entries, %d bytes",
            count,
            len(out),
            extra={"entries": count, "size": len(out)},
        )

        return out


# backward compatibility
baseMibs = PySnmpCodeGen.baseMibs
fakeMibs = PySnmpCodeGen.fakeMibs
