#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Rendering MIB modules as JSON documents."""

import json
import logging
import re
from collections import OrderedDict
from typing import Any, cast

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.codegen.base import (
    AbstractCodeGen,
    ComplianceClause,
    ComplianceRefinement,
    DefValClause,
    IndexClause,
    NamedNumbersClause,
    OidClause,
    RangesClause,
    RevisionsClause,
    SequenceClause,
    SymbolsClause,
    TextClause,
    format_ext_utc_time,
    trap_type_oid,
)
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)


@deprecated_camel_case
class JsonCodeGen(AbstractCodeGen):
    """Builds JSON document representing MIB module supplied
    in form of an Abstract Syntax Tree on input.

    Instance of this class is supposed to be passed to *MibCompiler*,
    the rest is internal to *MibCompiler*.
    """

    constImports = {
        "SNMPv2-SMI": (
            "iso",
            "NOTIFICATION-TYPE",  # bug in some MIBs (e.g. A3COM-HUAWEI-DHCPSNOOP-MIB)
            "MODULE-IDENTITY",
            "OBJECT-TYPE",
            "OBJECT-IDENTITY",
        ),
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
    fakeMibs = ("ASN1", "ASN1-ENUMERATION", "ASN1-REFINEMENT", *AbstractCodeGen.baseMibs)

    baseTypes = ["Integer", "Integer32", "Bits", "ObjectIdentifier", "OctetString"]

    typeClasses = {
        "NetworkAddress": "IpAddress",  # RFC1065-SMI, RFC1155-SMI -> SNMPv2-SMI
        "nullSpecific": "zeroDotZero",  # RFC1158-MIB -> SNMPv2-SMI
        "ipRoutingTable": "ipRouteTable",  # RFC1158-MIB -> RFC1213-MIB
        "snmpEnableAuthTraps": "snmpEnableAuthenTraps",  # RFC1158-MIB -> SNMPv2-MIB
    }

    smiv1IdxTypes = ["INTEGER", "OCTET STRING", "IPADDRESS", "NETWORKADDRESS"]

    indent = " " * 4
    fakeidx = 1000  # starting index for fake symbols

    def __init__(self) -> None:
        self._rows: set[str] = set()
        self._cols: dict[str, str] = {}  # k, v = name, datatype
        self._seenSyms: set[str] = set()
        self._importMap: dict[str, str] = {}
        self._out: dict[str, Any] = {}  # k, v = name, generated code
        self._moduleIdentityOid: str | None = None
        self._moduleRevision: str | None = None
        self._enterpriseOid: str | None = None
        self._oids: set[str] = set()
        self._complianceOids: list[str] = []
        self._notificationOids: list[str] = []
        self.moduleName: list[str] = ["DUMMY"]
        self.genRules: dict[str, Any] = {"text": True}
        self.symbolTable: dict[str, Any] = {}

    @staticmethod
    def trans_opers(symbol: str) -> Any:
        """Turn a MIB symbol into a name usable as a JSON key.

        Hyphens become underscores. Unlike the PySNMP backend, Python keywords
        need no special treatment here.

        Args:
            symbol: symbol name as written in the MIB

        Returns:
            The translated name.
        """
        return symbol.replace("-", "_")

    def prep_data(self, pdata: Any) -> list[Any]:
        """Convert a parse subtree into the values a clause handler expects.

        Each element that is a tagged tuple is dispatched through
        ``handlersTable`` and replaced by whatever that handler returns.
        Children are converted before their parent, so by the time a clause
        handler runs, its ``data`` holds finished values rather than raw nodes.

        Args:
            pdata: parse subtree

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
                data.append(self.handlersTable[el[0]](self, self.prep_data(el[1:])))
        return data

    def gen_imports(self, imports: dict[str, Any]) -> tuple[Any, ...]:
        # convertion to SNMPv2
        """Render the module's imports.

        SMIv1 imports are rewritten to their SMIv2 equivalents, and the symbols
        every module needs are merged in, before the imports are listed by the
        module they come from.

        Args:
            imports: imported symbols, keyed by the module they come from

        Returns:
            The imports as a JSON object, and the names of the modules
            imported, sorted.
        """
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

        outDict: OrderedDict[str, Any] = OrderedDict()
        outDict["class"] = "imports"
        for module in sorted(imports):
            symbols = []
            for symbol in sorted(set(imports[module])):
                symbols.append(symbol)

            if symbols:
                self._seenSyms.update([self.trans_opers(s) for s in symbols])
                self._importMap.update([(self.trans_opers(s), module) for s in symbols])
                if module not in outDict:
                    outDict[module] = []

                outDict[module].extend(symbols)

        return OrderedDict(imports=outDict), tuple(sorted(imports))

    # noinspection PyMethodMayBeStatic
    def gen_label(self, symbol: str) -> str:
        """Return the original MIB name for a symbol that had to be renamed.

        Args:
            symbol: symbol name as written in the MIB

        Returns:
            The name when it contains a hyphen, otherwise an empty string.
        """
        return ("-" in symbol and symbol) or ""

    def add_to_exports(self, symbol: str, moduleIdentity: bool = False) -> None:
        """Note that a symbol has been defined.

        The JSON document lists no exports; this only guards against a module
        defining the same symbol twice.

        Args:
            symbol: symbol name
            moduleIdentity: unused; accepted for interface compatibility
        """
        self._seenSyms.add(symbol)

    # noinspection PyUnusedLocal
    def reg_sym(
        self,
        symbol: str,
        outDict: "OrderedDict[str, Any]",
        parentOid: str | None = None,
        moduleIdentity: bool = False,
        moduleCompliance: bool = False,
    ) -> None:
        """Record the JSON rendered for a symbol.

        The symbol's OID is also collected, and the first OID under the private
        enterprises arc establishes the module's enterprise.

        Args:
            symbol: symbol name
            outDict: JSON rendered for it
            parentOid: OID it hangs off
            moduleIdentity: the symbol is this module's MODULE-IDENTITY
            moduleCompliance: the symbol is a MODULE-COMPLIANCE clause

        Raises:
            PySmiSemanticError: the module defines this symbol twice, or
                declares a second module identity.
        """
        if symbol in self._seenSyms and symbol not in self._importMap:
            raise error.PySmiSemanticError(f"Duplicate symbol found: {symbol}")

        self.add_to_exports(symbol, moduleIdentity)
        self._out[symbol] = outDict

        if "oid" in outDict:
            self._oids.add(outDict["oid"])

            if not self._enterpriseOid and outDict["oid"].startswith("1.3.6.1.4.1."):
                self._enterpriseOid = ".".join(outDict["oid"].split(".")[:7])

            if moduleIdentity:
                if self._moduleIdentityOid:
                    raise error.PySmiSemanticError("Duplicate module identity")
                self._moduleIdentityOid = outDict["oid"]

            if moduleCompliance:
                self._complianceOids.append(outDict["oid"])

            # Both NOTIFICATION-TYPE and a converted TRAP-TYPE land here, which
            # is what makes a trap findable by OID rather than only by name.
            if outDict.get("class") == "notificationtype":
                self._notificationOids.append(outDict["oid"])

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
    def gen_agent_capabilities(self, data: Any) -> Any:
        """Render an AGENT-CAPABILITIES clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, productRelease, status, description, reference, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "agentcapabilities"

        if productRelease:
            outDict["productrelease"] = productRelease

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_module_identity(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a MODULE-IDENTITY clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, lastUpdated, organization, contactInfo, description, revisions, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "moduleidentity"

        if revisions:
            outDict["revisions"] = revisions

            self._moduleRevision = revisions[0]["revision"]

        if self.genRules["text"]:
            if lastUpdated:
                outDict["lastupdated"] = lastUpdated
            if organization:
                outDict["organization"] = organization
            if contactInfo:
                outDict["contactinfo"] = contactInfo
            if description:
                outDict["description"] = description

        self.reg_sym(name, outDict, parentOid, moduleIdentity=True)

        return outDict

    # noinspection PyUnusedLocal
    def gen_module_compliance(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a MODULE-COMPLIANCE clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, status, description, reference, compliances, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "modulecompliance"

        compliances, refinements = compliances or ([], [])

        if compliances:
            outDict["modulecompliance"] = compliances

        if refinements:
            outDict["refinements"] = refinements

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid, moduleCompliance=True)

        return outDict

    # noinspection PyUnusedLocal
    def gen_notification_group(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a NOTIFICATION-GROUP clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, objects, status, description, reference, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid
        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "notificationgroup"

        if objects:
            outDict["objects"] = [
                {"module": self._importMap.get(obj, self.moduleName[0]), "object": self.trans_opers(obj)}
                for obj in objects
            ]

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_notification_type(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a NOTIFICATION-TYPE clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, objects, status, description, reference, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid
        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "notificationtype"

        if objects:
            outDict["objects"] = [
                {"module": self._importMap.get(obj, self.moduleName[0]), "object": self.trans_opers(obj)}
                for obj in objects
            ]

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_object_group(self, data: Any) -> "OrderedDict[str, Any]":
        """Render an OBJECT-GROUP clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, objects, status, description, reference, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid
        outDict = OrderedDict({"name": name, "oid": oidStr, "class": "objectgroup"})

        if objects:
            outDict["objects"] = [
                {"module": self._importMap.get(obj, self.moduleName[0]), "object": self.trans_opers(obj)}
                for obj in objects
            ]

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_object_identity(self, data: Any) -> Any:
        """Render an OBJECT-IDENTITY clause.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, status, description, reference, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "objectidentity"

        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_object_type(self, data: Any) -> "OrderedDict[str, Any]":
        """Render an OBJECT-TYPE clause.

        What kind of node it is depends on what the object turned out to be: a
        column if the symbol table recorded it as one, a table or row if its
        syntax says so, and a scalar otherwise.

        Note:
            An SMIv1 index that names a bare type rather than a column needs a
            synthetic column, which this backend does not yet emit. Such a MIB
            fails to render as JSON; see issue #37.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, syntax, units, maxaccess, status, description, reference, augmentation, index, defval, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid
        # gen_table_index returns lists throughout, so an absent INDEX stands in
        # as empty ones rather than as the empty strings pysnmp source uses.
        indexStr: list[Any]
        fakeStrlist: list[OrderedDict[str, Any]]
        fakeSyms: list[str]
        indexStr, fakeStrlist, fakeSyms = index or ([], [], [])

        defval = self.gen_def_val(defval, objname=name)

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr

        if syntax[0]:
            nodetype = (syntax[0] == "Bits" and "scalar") or syntax[0]  # Bits hack
            nodetype = (name in self.symbolTable[self.moduleName[0]]["_symtable_cols"] and "column") or nodetype
            outDict["nodetype"] = nodetype

        outDict["class"] = "objecttype"

        if syntax[1]:
            outDict["syntax"] = syntax[1]
        if defval:
            outDict["default"] = defval
        if units:
            outDict["units"] = units
        if maxaccess:
            outDict["maxaccess"] = maxaccess
        if indexStr:
            outDict["indices"] = indexStr
        if self.genRules["text"] and reference:
            outDict["reference"] = reference
        if augmentation:
            augmentation = self.trans_opers(augmentation)
            outDict["augmentation"] = OrderedDict()
            outDict["augmentation"]["name"] = name
            outDict["augmentation"]["module"] = self.moduleName[0]
            outDict["augmentation"]["object"] = augmentation
        if status:
            outDict["status"] = status

        if self.genRules["text"] and description:
            outDict["description"] = description

        self.reg_sym(name, outDict, parentOid)

        if fakeSyms:  # fake symbols for INDEX to support SMIv1
            for idx, fakeSym in enumerate(fakeSyms):
                fakeOutDict = fakeStrlist[idx]
                fakeOutDict["oid"] = fakeOutDict["oid"] % oidStr
                self.reg_sym(fakeSym, fakeOutDict, oidStr)

        return outDict

    # noinspection PyUnusedLocal
    def gen_trap_type(self, data: Any) -> Any:
        """Render a TRAP-TYPE clause as a notification.

        SMIv1 traps have no OID of their own; theirs is derived from the
        ENTERPRISE clause and the trap number, which is how SMIv2 names the
        same notification. See ``trap_type_oid``.

        Args:
            data: converted clause values

        Returns:
            The clause as a JSON object.
        """
        name, enterprise, variables, description, reference, value = data

        self.gen_label(name)
        name = self.trans_opers(name)

        enterpriseStr, parentOid = enterprise
        enterpriseOid = tuple(int(subId) for subId in enterpriseStr.split("."))

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = ".".join(str(subId) for subId in trap_type_oid(enterpriseOid, value))
        outDict["class"] = "notificationtype"

        if variables:
            outDict["objects"] = [
                {"module": self._importMap.get(obj, self.moduleName[0]), "object": self.trans_opers(obj)}
                for obj in variables
            ]

        if self.genRules["text"] and description:
            outDict["description"] = description

        if self.genRules["text"] and reference:
            outDict["reference"] = reference

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # noinspection PyUnusedLocal
    def gen_type_declaration(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a type declaration.

        Args:
            data: converted clause values

        Returns:
            The declaration as a JSON object.
        """
        name, declaration = data

        outDict = OrderedDict()
        outDict["name"] = name
        outDict["class"] = "type"

        if declaration:
            parentType, attrs = declaration
            if parentType:  # skipping SEQUENCE case
                name = self.trans_opers(name)
                outDict.update(attrs)
                self.reg_sym(name, outDict)

        return outDict

    # noinspection PyUnusedLocal
    def gen_value_declaration(self, data: Any) -> "OrderedDict[str, Any]":
        """Render a plain OID assignment.

        Args:
            data: converted clause values

        Returns:
            The assignment as a JSON object.
        """
        name, oid = data

        self.gen_label(name)
        name = self.trans_opers(name)

        oidStr, parentOid = oid
        outDict = OrderedDict()
        outDict["name"] = name
        outDict["oid"] = oidStr
        outDict["class"] = "objectidentity"

        self.reg_sym(name, outDict, parentOid)

        return outDict

    # Subparts generation functions

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_bit_names(self, data: SymbolsClause) -> Any:
        """Return the names listed in a BITS or enumeration clause.

        Args:
            data: converted clause values

        Returns:
            The names, in the order they were written.
        """
        names = data[0]
        return names

    def gen_bits(self, data: NamedNumbersClause) -> tuple[str, OrderedDict[str, Any]]:
        """Render a BITS clause.

        Args:
            data: converted clause values

        Returns:
            The ``scalar`` node type and the syntax, naming ``Bits`` and its
            bits, keyed by name.
        """
        bits = data[0]

        outDict: OrderedDict[str, Any] = OrderedDict()
        outDict["type"] = "Bits"
        outDict["class"] = "type"
        outDict["bits"] = OrderedDict()

        for name, bit in sorted(bits, key=lambda x: x[1]):
            outDict["bits"][name] = bit

        return "scalar", outDict

    # noinspection PyUnusedLocal
    def gen_compliances(self, data: ComplianceClause) -> tuple[list[Any], list[Any]]:
        """Render what a MODULE-COMPLIANCE requires, and how it refines it.

        Args:
            data: converted clause values

        Returns:
            The objects the compliance requires, one entry each naming the
            object and its module, and the GROUP and OBJECT sub-clauses that
            qualify them.
        """
        compliances = []
        refinements = []

        for complianceModule in data[0]:
            name = complianceModule[0] or self.moduleName[0]
            compliances += [{"object": self.trans_opers(compl), "module": name} for compl in complianceModule[1]]

            for refinement in complianceModule[2][1]:
                rendered = self.gen_compliance_refinement(name, refinement)
                if rendered:
                    refinements.append(rendered)

        return compliances, refinements

    def gen_compliance_refinement(
        self, module: str, refinement: ComplianceRefinement
    ) -> "OrderedDict[str, Any] | None":
        """Render one GROUP or OBJECT sub-clause of a MODULE-COMPLIANCE.

        Args:
            module: the module the sub-clause names, already defaulted
            refinement: the tagged sub-clause

        Returns:
            The sub-clause as a JSON object, or ``None`` when its texts are
            suppressed and it refines nothing.
        """
        outDict: OrderedDict[str, Any] = OrderedDict()
        outDict["module"] = module

        if refinement[0] == "ComplianceGroup":
            outDict["object"] = self.trans_opers(refinement[1])
            outDict["kind"] = "group"

            # A GROUP says nothing but the condition it applies under, so
            # without its description there is nothing left to report.
            if not self.genRules["text"]:
                return None

            outDict["description"] = self.textFilter("description", refinement[2])

            return outDict

        _tag, name, syntax, writeSyntax, minAccess, description = refinement

        outDict["object"] = self.trans_opers(name[1][0])
        outDict["kind"] = "object"

        if syntax:
            outDict["syntax"] = self.gen_refined_syntax(syntax)

        if writeSyntax:
            outDict["writesyntax"] = self.gen_refined_syntax(writeSyntax[1])

        if minAccess:
            outDict["minaccess"] = minAccess[1]

        if self.genRules["text"] and description:
            outDict["description"] = self.textFilter("description", description)

        return outDict

    def gen_refined_syntax(self, syntax: Any) -> Any:
        """Render the SYNTAX of a compliance refinement as an object type does.

        The syntax handlers return the node type alongside the type itself,
        which a refinement has no use for -- it names an existing object
        rather than declaring a new one.

        Args:
            syntax: the unconverted syntax subtree

        Returns:
            The type as a JSON object.
        """
        rendered = self.prep_data([syntax])[0]

        if isinstance(rendered, tuple) and len(rendered) == 2:
            return rendered[1]

        return rendered

    # noinspection PyUnusedLocal
    def gen_conceptual_table(self, data: Any) -> tuple[Any, ...]:
        """Note the row a table contains and return the table's node type.

        The row name is remembered so that :py:meth:`gen_row` can recognise it
        later as a row rather than an ordinary type.

        Args:
            data: converted clause values

        Returns:
            The ``table`` node type and no syntax.
        """
        row = data[0]

        if row[1] and row[1][-2:] == "()":
            row = row[1][:-2]
            self._rows.add(row)

        return "table", ""

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_contact_info(self, data: TextClause) -> str:
        """Render a CONTACT-INFO clause.

        Args:
            data: converted clause values

        Returns:
            The contact information.
        """
        text = data[0]
        return self.textFilter("contact-info", text)

    # noinspection PyUnusedLocal
    def gen_display_hint(self, data: TextClause) -> str:
        """Render a DISPLAY-HINT.

        Args:
            data: converted clause values

        Returns:
            The display hint.
        """
        return data[0]

    # noinspection PyUnusedLocal
    def gen_def_val(self, data: DefValClause | None, objname: str | None = None) -> "dict[str, Any] | list[Any]":
        """Render a DEFVAL as a value of the object's own type.

        The default is interpreted according to the base type the object
        resolves to, which is also how several common MIB errors are absorbed:
        a hexadecimal or binary default written for an integer is converted to
        one, and an empty string given for a non-string type is dropped rather
        than rendered.

        Args:
            data: converted clause values
            objname: object the default belongs to; without it the value is
                returned unrendered

        Returns:
            The default value, paired with the format it was written in.

        Raises:
            PySmiSemanticError: the default names an unknown symbol or bit, or
                the object's type cannot carry a default.
        """
        if not data:
            return {}
        if not objname:
            return cast("dict[str, Any] | list[Any]", data)

        outDict: OrderedDict[str, Any] = OrderedDict()

        defval = data[0]
        defvalType = self.get_base_type(objname, self.moduleName[0])

        if isinstance(defval, int):  # number
            outDict.update(value=defval, format="decimal")

        elif self.is_hex(defval):  # hex
            if defvalType[0][0] in ("Integer32", "Integer"):  # common bug in MIBs
                # The digits are a number here, not octets, so they are reported
                # as one. Saying "hex" would have a reader decode them a second
                # time and arrive at a different value.
                outDict.update(value=int((len(defval) > 3 and defval[1:-2]) or "0", 16), format="decimal")
            else:
                outDict.update(value=defval[1:-2], format="hex")

        elif self.is_binary(defval):  # binary
            binval = defval[1:-2]
            if defvalType[0][0] in ("Integer32", "Integer"):  # common bug in MIBs
                outDict.update(value=int(binval or "0", 2), format="decimal")
            else:
                hexval = (binval and hex(int(binval, 2))[2:]) or ""
                outDict.update(value=hexval, format="hex")

        elif defval[0] == defval[-1] and defval[0] == '"':  # quoted string
            if defval[1:-1] == "" and defvalType[0][0] != "OctetString":  # common bug
                # a warning should be here
                return {}  # we will set no default value
            outDict.update(value=defval[1:-1], format="string")

        else:  # symbol (oid as defval) or name for enumeration member
            # A bits list reaching an OID-typed object is a broken MIB; the
            # membership tests below would raise TypeError on the unhashable
            # list, so leave it to the branches that handle a list.
            if (
                defvalType[0][0] == "ObjectIdentifier"
                and isinstance(defval, str)
                and (defval in self.symbolTable[self.moduleName[0]] or defval in self._importMap)
            ):  # oid
                module = self._importMap.get(defval, self.moduleName[0])

                try:
                    val = str(self.gen_numeric_oid(self.symbolTable[module][defval]["oid"]))
                    outDict.update(value=val, format="oid")
                except (KeyError, error.PySmiSemanticError) as exc:
                    # or no module if it will be borrowed later
                    raise error.PySmiSemanticError(f'no symbol "{defval}" in module "{module}"') from exc

            # enumeration
            elif defvalType[0][0] in ("Integer32", "Integer") and isinstance(defvalType[1], list):
                if isinstance(defval, list):  # buggy MIB: DEFVAL { { ... } }
                    defval = [dv for dv in defval if dv in dict(defvalType[1])]
                    if defval:
                        outDict.update(value=defval[0], format="enum")
                elif defval in dict(defvalType[1]):  # good MIB: DEFVAL { ... }
                    outDict.update(value=defval, format="enum")

            elif defvalType[0][0] == "Bits":
                defvalBits = []

                bits = dict(defvalType[1])

                for bit in defval:
                    bitValue = bits.get(bit)
                    if bitValue is not None:
                        defvalBits.append((bit, bitValue))
                    else:
                        raise error.PySmiSemanticError(f'no such bit as "{bit}" for symbol "{objname}"')

                outDict.update(value=self.gen_bits([defvalBits])[1], format="bits")

                return outDict

            else:
                raise error.PySmiSemanticError(
                    f'unknown type "{defvalType}" for defval "{defval}" of symbol "{objname}"'
                )

        return outDict

    # noinspection PyMethodMayBeStatic
    def gen_description(self, data: TextClause) -> str:
        """Render a DESCRIPTION clause.

        Args:
            data: converted clause values

        Returns:
            The description text.
        """
        return self.textFilter("description", data[0])

    # noinspection PyMethodMayBeStatic
    def gen_reference(self, data: TextClause) -> str:
        """Render a REFERENCE clause.

        Args:
            data: converted clause values

        Returns:
            The reference text.
        """
        return self.textFilter("reference", data[0])

    # noinspection PyMethodMayBeStatic
    def gen_status(self, data: TextClause) -> str:
        """Render a STATUS clause.

        Args:
            data: converted clause values

        Returns:
            The status as written.
        """
        return data[0]

    def gen_product_release(self, data: TextClause) -> Any:
        """Render a PRODUCT-RELEASE clause.

        Args:
            data: converted clause values

        Returns:
            The product release text.
        """
        return data[0]

    def gen_enum_spec(self, data: NamedNumbersClause) -> dict[str, Any]:
        """Render an enumeration.

        Args:
            data: converted clause values

        Returns:
            The members, keyed by name.
        """
        items = data[0]
        return {"enumeration": dict(items)}

    # noinspection PyUnusedLocal
    def gen_table_index(self, data: IndexClause) -> tuple[Any, ...]:
        """Render an INDEX clause as the row's indices.

        Args:
            data: converted clause values

        Returns:
            One entry per index naming the column and its module, the
            synthetic columns an SMIv1 index needs, and their names.
            :py:meth:`gen_object_type` emits the synthetic columns once it knows
            the OID of the row they hang off.
        """

        def genFakeSyms(fakeidx: int, idxType: str) -> tuple["OrderedDict[str, Any]", str]:
            """Render a synthetic column for an SMIv1 index.

            Args:
                fakeidx: sub-identifier to give the column
                idxType: type the index named in place of a column

            Returns:
                The column as a JSON object, with its parent OID left as a
                template to be filled in, and the name it was given.
            """
            fakeSymName = f"pysmiFakeCol{fakeidx}"

            objType = self.typeClasses.get(idxType, idxType)
            objType = self.trans_opers(objType)

            outDict: OrderedDict[str, Any] = OrderedDict()
            outDict["name"] = fakeSymName
            # The row's OID is not known here, so leave a template for
            # gen_object_type to fill in, as the pysnmp backend does.
            outDict["oid"] = "%s." + str(fakeidx)
            outDict["nodetype"] = "column"
            outDict["class"] = "objecttype"
            outDict["syntax"] = OrderedDict([("type", objType), ("class", "type")])

            return outDict, fakeSymName

        indexes = data[0]
        idxStrlist, fakeSyms, fakeStrlist = [], [], []

        for idx in indexes:
            isImplied = idx[0]
            idxName = idx[1]
            if idxName in self.smiv1IdxTypes:  # SMIv1 support
                idxType = idxName
                fakeSymStr, idxName = genFakeSyms(self.fakeidx, idxType)
                fakeStrlist.append(fakeSymStr)
                fakeSyms.append(idxName)
                self.fakeidx += 1

            index: OrderedDict[str, Any] = OrderedDict()
            index["module"] = self._importMap.get(idxName, self.moduleName[0])
            index["object"] = idxName
            index["implied"] = isImplied
            idxStrlist.append(index)

        return idxStrlist, fakeStrlist, fakeSyms

    def gen_integer_sub_type(self, data: RangesClause) -> dict[str, Any]:
        """Render an integer range restriction.

        Args:
            data: converted clause values

        Returns:
            The permitted ranges.
        """
        ranges = []
        for rng in data[0]:
            vmin, vmax = (len(rng) == 1 and (rng[0], rng[0])) or rng
            vmin, vmax = self.str2int(vmin), self.str2int(vmax)
            ran = OrderedDict()
            ran["min"] = vmin
            ran["max"] = vmax
            ranges.append(ran)

        return {"range": ranges}

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_max_access(self, data: TextClause) -> str:
        """Render a MAX-ACCESS clause.

        Args:
            data: converted clause values

        Returns:
            The access level as written.
        """
        return data[0]

    def gen_octet_string_sub_type(self, data: RangesClause) -> dict[str, Any]:
        """Render an octet string size restriction.

        Args:
            data: converted clause values

        Returns:
            The permitted sizes.
        """
        sizes = []
        for rng in data[0]:
            vmin, vmax = (len(rng) == 1 and (rng[0], rng[0])) or rng
            vmin, vmax = self.str2int(vmin), self.str2int(vmax)

            size = OrderedDict()
            size["min"] = vmin
            size["max"] = vmax
            sizes.append(size)

        return {"size": sizes}

    # noinspection PyUnusedLocal
    def gen_oid(self, data: OidClause) -> tuple[Any, ...]:
        """Resolve an OID and render it in dotted form.

        Args:
            data: converted clause values

        Returns:
            The numeric OID, and the name it hangs off.

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

        return ".".join([str(x) for x in self.gen_numeric_oid(out)]), parent

    # noinspection PyUnusedLocal
    def gen_objects(self, data: SymbolsClause) -> list[Any]:
        """Return the names in an OBJECTS or NOTIFICATIONS list.

        Args:
            data: converted clause values

        Returns:
            The translated names, empty when the list is.
        """
        if data[0]:
            return [self.trans_opers(obj) for obj in data[0]]  # XXX self.trans_opers or not??
        return []

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_time(self, data: TextClause) -> list[Any]:
        """Render MIB timestamps as readable dates.

        Args:
            data: timestamps as written in the MIB

        Returns:
            One formatted date per timestamp.
        """
        return [format_ext_utc_time(timeStr, self.moduleName[0]) for timeStr in data]

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_last_updated(self, data: TextClause) -> str:
        """Render a LAST-UPDATED clause.

        Args:
            data: converted clause values

        Returns:
            The timestamp as a formatted date.
        """
        return format_ext_utc_time(data[0], self.moduleName[0])

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_organization(self, data: TextClause) -> str:
        """Render an ORGANIZATION clause.

        Args:
            data: converted clause values

        Returns:
            The organization text.
        """
        return self.textFilter("organization", data[0])

    # noinspection PyUnusedLocal
    def gen_revisions(self, data: RevisionsClause) -> list[Any]:
        """Render a module's revision history.

        Args:
            data: converted clause values

        Returns:
            One entry per revision, with its date and description.
        """
        revisions = []
        for x in data[0]:
            revision = OrderedDict()
            revision["revision"] = self.gen_time([x[0]])[0]
            revision["description"] = self.textFilter("description", x[1][1])
            revisions.append(revision)
        return revisions

    def gen_row(self, data: TextClause) -> tuple[Any, ...]:
        """Render the node type of a table row.

        A name the symbol table recorded as a table's row is a row; anything
        else is an ordinary type and is rendered as one.

        Args:
            data: converted clause values

        Returns:
            The ``row`` node type with no syntax, or whatever
            :py:meth:`gen_simple_syntax` makes of the name.
        """
        row = data[0]
        row = self.trans_opers(row)

        return (
            row in self.symbolTable[self.moduleName[0]]["_symtable_rows"] and ("row", "")
        ) or self.gen_simple_syntax(data)

    # noinspection PyUnusedLocal
    def gen_sequence(self, data: SequenceClause) -> tuple[Any, ...]:
        """Record the columns of a SEQUENCE.

        Args:
            data: converted clause values

        Returns:
            Empty node type and syntax; a SEQUENCE is not rendered itself.
        """
        cols = data[0]
        self._cols.update(cols)
        return "", ""

    def gen_simple_syntax(self, data: Any) -> tuple[Any, ...]:
        """Render a type reference.

        SMIv1 type names are mapped to their SMIv2 equivalents, and any subtype
        restriction is carried alongside.

        Args:
            data: converted clause values

        Returns:
            The ``scalar`` node type and the syntax, naming the type and any
            constraints on it.
        """
        objType = data[0]
        objType = self.typeClasses.get(objType, objType)
        objType = self.trans_opers(objType)

        subtype = (len(data) == 2 and data[1]) or {}

        outDict = OrderedDict()
        outDict["type"] = objType
        outDict["class"] = "type"

        if subtype:
            outDict["constraints"] = subtype

        return "scalar", outDict

    # noinspection PyUnusedLocal
    def gen_type_declaration_rhs(self, data: Any) -> "OrderedDict[str, Any] | tuple[Any, ...]":
        """Render the body of a type declaration.

        A textual convention carries display hint, status and text alongside its
        syntax and is marked as such.

        Args:
            data: converted clause values

        Returns:
            The type derived from and the body, or an empty object for a
            declaration with no attributes.
        """
        if len(data) == 1:
            parentType, attrs = data[0]

            outDict: OrderedDict[str, Any] = OrderedDict()
            if not attrs:
                return outDict
            # just syntax
            outDict["type"] = attrs

        else:
            # Textual convention
            display, status, description, reference, syntax = data
            parentType, attrs = syntax

            outDict = OrderedDict()
            outDict["type"] = attrs
            outDict["class"] = "textualconvention"
            if display:
                outDict["displayhint"] = display
            if status:
                outDict["status"] = status
            if self.genRules["text"] and description:
                outDict["description"] = description
            if self.genRules["text"] and reference:
                outDict["reference"] = reference

        return parentType, outDict

    # noinspection PyMethodMayBeStatic,PyUnusedLocal
    def gen_units(self, data: TextClause) -> str:
        """Render a UNITS clause.

        Args:
            data: converted clause values

        Returns:
            The units text.
        """
        text = data[0]
        return self.textFilter("units", text)

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
        "PRODUCT-RELEASE": gen_product_release,
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
        """Render one parsed MIB module as a JSON document.

        Args:
            ast: parse tree of a single module
            symbolTable: symbols of this module and everything it imports

        Keyword Args:
            genTexts: carry human-readable texts into the output
            textFilter: callable applied to each text before it is rendered;
                by default runs of whitespace are collapsed
            comments: lines to record in the document

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and the document.

        Raises:
            PySmiCodegenError: a symbol in the symbol table was never rendered.
            PySmiSemanticError: the module is not internally consistent.
        """
        self.genRules["text"] = kwargs.get("genTexts", False)
        self.textFilter = kwargs.get("textFilter") or (lambda symbol, text: re.sub(r"\s+", " ", text))
        self.symbolTable = symbolTable
        self._rows.clear()
        self._cols.clear()
        self._seenSyms.clear()
        self._importMap.clear()
        self._out.clear()
        self._moduleIdentityOid = None
        self._enterpriseOid = None
        self._oids = set()
        self._complianceOids = []
        self._notificationOids = []
        self.moduleName[0], moduleOid, imports, declarations = ast

        outDict, importedModules = self.gen_imports((imports and imports) or {})

        for declr in declarations or []:
            if declr:
                self.handlersTable[declr[0]](self, self.prep_data(declr[1:]))

        for sym in self.symbolTable[self.moduleName[0]]["_symtable_order"]:
            if sym not in self._out:
                raise error.PySmiCodegenError(f"No generated code for symbol {sym}")

            outDict[sym] = self._out[sym]

        if "comments" in kwargs:
            outDict["meta"] = OrderedDict()
            outDict["meta"]["comments"] = kwargs["comments"]
            outDict["meta"]["module"] = self.moduleName[0]

        logger.debug(
            "canonical MIB name %s (%s), imported MIB(s) %s, Python code size %d bytes",
            self.moduleName[0],
            moduleOid,
            ",".join(importedModules) or "<none>",
            len(outDict),
            extra={
                "mib": self.moduleName[0],
                "oid": str(moduleOid),
                "imported": list(importedModules),
                "size": len(outDict),
            },
        )

        return MibInfo(
            oid=moduleOid,
            identity=self._moduleIdentityOid,
            name=self.moduleName[0],
            revision=self._moduleRevision,
            oids=self._oids,
            enterprise=self._enterpriseOid,
            compliance=self._complianceOids,
            notification=self._notificationOids,
            imported=tuple(x for x in importedModules if x not in self.fakeMibs),
        ), json.dumps(outDict, indent=2)

    def gen_index(self, processed: dict[str, Any], **kwargs: Any) -> str:
        """Render an index of the modules compiled and what they define.

        An existing index may be passed in, in which case this run's modules
        are merged into it rather than replacing it.

        Args:
            processed: compilation outcome per module, as reported by
                :py:class:`~pysmi.compiler.MibCompiler`

        Keyword Args:
            old_index_data: an index to merge into, as JSON
            comments: lines to record in the document

        Returns:
            The index as a JSON document.

        Raises:
            PySmiCodegenError: the index passed in could not be read.
        """
        outDict: dict[str, Any] = {
            "meta": {},
            "identity": {},
            "enterprise": {},
            "compliance": {},
            "notification": {},
            "oids": {},
        }
        if kwargs.get("old_index_data"):
            try:
                outDict.update(json.loads(kwargs["old_index_data"]))

            except (TypeError, ValueError) as exc:
                raise error.PySmiCodegenError(f"Index load error: {exc}") from exc

        def order(top: Any) -> Any:
            """Sort a decoded index into a stable order, recursively.

            Object keys sort numerically when they are all OIDs, and
            lexicographically otherwise. Lists are sorted and de-duplicated. This
            is what keeps the index reproducible across runs.

            Args:
                top: decoded JSON value

            Returns:
                The same value, ordered.
            """
            if isinstance(top, dict):
                new_top: Any = OrderedDict()
                try:
                    # first try to sort keys as OIDs
                    for k in sorted(top, key=lambda x: [int(y) for y in x.split(".")]):
                        new_top[k] = order(top[k])

                except ValueError:
                    for k in sorted(top):
                        new_top[k] = order(top[k])

                return new_top
            elif isinstance(top, list):
                new_top = []
                for e in sorted(set(top)):
                    new_top.append(order(e))

                return new_top

            return top

        for module, status in processed.items():
            modData = outDict["identity"]
            identity_oid = getattr(status, "identity", None)
            if identity_oid:
                if identity_oid not in modData:
                    modData[identity_oid] = []

                modData[identity_oid].append(module)

            modData = outDict["enterprise"]
            enterprise_oid = getattr(status, "enterprise", None)
            if enterprise_oid:
                if enterprise_oid not in modData:
                    modData[enterprise_oid] = []

                modData[enterprise_oid].append(module)

            modData = outDict["compliance"]
            compliance_oids = getattr(status, "compliance", ())
            for compliance_oid in compliance_oids:
                if compliance_oid not in modData:
                    modData[compliance_oid] = []
                modData[compliance_oid].append(module)

            modData = outDict["notification"]
            notification_oids = getattr(status, "notification", ())
            for notification_oid in notification_oids:
                if notification_oid not in modData:
                    modData[notification_oid] = []
                modData[notification_oid].append(module)

            modData = outDict["oids"]
            objects_oids = getattr(status, "oids", ())
            for object_oid in objects_oids:
                if object_oid not in modData:
                    modData[object_oid] = []

                modData[object_oid].append(module)

            if modData:
                unique_prefixes: dict[str, Any] = {}
                for oid in sorted(modData, key=lambda x: x.count(".")):
                    for oid_prefix, modules in unique_prefixes.items():
                        if oid.startswith(oid_prefix) and set(modules).issuperset(modData[oid]):
                            break
                    else:
                        unique_prefixes[oid] = modData[oid]

                outDict["oids"] = unique_prefixes

        if "comments" in kwargs:
            outDict["meta"]["comments"] = kwargs["comments"]

        logger.debug("OID->MIB index built, %d entries", len(processed), extra={"entries": len(processed)})

        return json.dumps(order(outDict), indent=2)
