#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
# Build an internally used symbol table for each passed MIB.
#
"""Building the symbol table of a MIB module.

This backend produces no output of its own. It records what a module defines
and what it refers to, which is what the other backends consult to resolve
symbols across modules.
"""

import logging
from collections.abc import Sequence
from keyword import iskeyword
from typing import Any, cast

from pysmi import error
from pysmi._aliases import deprecated_camel_case
from pysmi.codegen.base import AbstractCodeGen, dorepr
from pysmi.mibinfo import MibInfo

logger = logging.getLogger(__name__)


@deprecated_camel_case
class SymtableCodeGen(AbstractCodeGen):
    """Collect the symbols a MIB module defines and refers to.

    This generator renders no source. It walks the same parse tree as the
    other backends, but instead of emitting code it records, for each symbol,
    its type, OID, syntax and the symbols it depends on. The result is the
    symbol table that :py:class:`~pysmi.codegen.pysnmp.PySnmpCodeGen` and
    :py:class:`~pysmi.codegen.jsondoc.JsonCodeGen` consult to resolve
    references into other modules.

    Because only names, OIDs, types and parentage matter here, the handlers
    for purely descriptive clauses (DESCRIPTION, REFERENCE, UNITS and the
    rest) deliberately return an empty string.
    """

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

    def __init__(self) -> None:
        self._rows: set[str] = set()
        self._cols: dict[str, str] = {}  # k, v = name, datatype
        self._exports: set[str] = set()
        self._postponedSyms: dict[str, Any] = {}  # k, v = symbol, (parents, properties)
        self._parentOids: set[str] = set()
        self._importMap: dict[str, str] = {}  # k, v = symbol, MIB
        self._symsOrder: list[str] = []
        self._out: dict[str, Any] = {}  # k, v = symbol, properties
        self.moduleName: list[str] = ["DUMMY"]
        self._moduleRevision: str | None = None
        self.genRules = {"text": True}

    def sym_trans(self, symbol: str) -> tuple[Any, ...]:
        """Map an SMI construct name onto the MIB symbols it introduces.

        Args:
            symbol: name as it appears in the MIB, such as ``OBJECT-TYPE``

        Returns:
            The symbols that construct defines, or the name unchanged when it
            is not an SMI construct.
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
        :py:attr:`handlersTable` and replaced by whatever that handler returns.
        Children are converted before their parent, so by the time a clause
        handler runs, its ``data`` holds finished values rather than raw nodes.

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
        # convertion to SNMPv2
        """Record which module each imported symbol comes from.

        SMIv1 imports are rewritten to their SMIv2 equivalents, and the implicit
        imports every module needs are merged in, before the symbol-to-module
        map is built.

        Args:
            imports: imported symbols, keyed by the module they come from

        Returns:
            An empty mapping (this backend renders nothing) and the names of
            the modules imported, sorted.
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

        for module in sorted(imports):
            symbols: tuple[Any, ...] = ()
            for symbol in set(imports[module]):
                symbols += self.sym_trans(symbol)

            if symbols:
                self._importMap.update([(self.trans_opers(s), module) for s in symbols])

        return {}, tuple(sorted(imports))

    def all_parents_exists(self, parents: Sequence[Any]) -> bool:
        """Report whether every parent of a symbol is already known.

        A parent counts as known if this module has defined it, imports it, or
        it is a base type or one of the conceptual-table classes.

        Args:
            parents: symbols the pending symbol depends on

        Returns:
            True when all of them can be resolved.
        """
        parentsExists = True
        for parent in parents:
            if not (
                parent in self._out
                or parent in self._importMap
                or parent in self.baseTypes
                or parent in ("MibTable", "MibTableRow", "MibTableColumn")
                or parent in self._rows
            ):
                parentsExists = False
                break

        return parentsExists

    def reg_sym(self, symbol: str, symProps: dict[str, Any], parents: Sequence[Any] = ()) -> None:
        """Add a symbol to the table, or hold it until its parents are known.

        MIBs may define a symbol before the symbols it derives from. A symbol
        whose parents are not all known yet is set aside and registered later,
        once they are.

        Args:
            symbol: Python-safe symbol name
            symProps: what is known about the symbol: type, OID, syntax
            parents: symbols it derives from

        Raises:
            PySmiSemanticError: the module defines this symbol twice.
        """
        if symbol in self._out or symbol in self._postponedSyms:  # add to strict mode - or symbol in self._importMap:
            raise error.PySmiSemanticError(f"Duplicate symbol found: {symbol}")

        if self.all_parents_exists(parents):
            self._out[symbol] = symProps
            self._symsOrder.append(symbol)
            self.reg_postponed_syms()

        else:
            self._postponedSyms[symbol] = (parents, symProps)

    def reg_postponed_syms(self) -> None:
        """Register any held-back symbols whose parents have since appeared.

        Registering one symbol can resolve another, so this runs after every
        successful registration.
        """
        regedSyms = []
        for sym, val in self._postponedSyms.items():
            parents, symProps = val

            if self.all_parents_exists(parents):
                self._out[sym] = symProps
                self._symsOrder.append(sym)
                regedSyms.append(sym)

        for sym in regedSyms:
            self._postponedSyms.pop(sym)

        # Clause handlers

    # noinspection PyUnusedLocal
    def gen_agent_capabilities(self, data: Any, classmode: bool = False) -> None:
        """Record an AGENT-CAPABILITIES clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _release, _status, _description, _reference, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "AgentCapabilities", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_module_identity(self, data: Any, classmode: bool = False) -> None:
        """Record a MODULE-IDENTITY clause and note the module's latest revision.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _lastUpdated, _organization, _contactInfo, _description, revisions, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "ModuleIdentity", "oid": oid, "origName": origName}

        if revisions:
            self._moduleRevision = revisions[0]

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_module_compliance(self, data: Any, classmode: bool = False) -> None:
        """Record a MODULE-COMPLIANCE clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _status, _description, _reference, _compliances, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "ModuleCompliance", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_notification_group(self, data: Any, classmode: bool = False) -> None:
        """Record a NOTIFICATION-GROUP clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _objects, _status, _description, _reference, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "NotificationGroup", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_notification_type(self, data: Any, classmode: bool = False) -> None:
        """Record a NOTIFICATION-TYPE clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _objects, _status, _description, _reference, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "NotificationType", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_object_group(self, data: Any, classmode: bool = False) -> None:
        """Record an OBJECT-GROUP clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _objects, _status, _description, _reference, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "ObjectGroup", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_object_identity(self, data: Any, classmode: bool = False) -> None:
        """Record an OBJECT-IDENTITY clause.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, _status, _description, _reference, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "ObjectIdentity", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_object_type(self, data: Any, classmode: bool = False) -> None:
        """Record an OBJECT-TYPE clause and the symbols it depends on.

        The object's syntax names its parent type, and AUGMENTS names another
        row, so both are registered as parents. An SMIv1 index that names a bare
        type rather than a column also causes a synthetic column to be recorded
        here, matching what :py:meth:`gen_index_clause` worked out.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, syntax, _units, _maxaccess, _status, _description, _reference, augmention, index, defval, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {
            "type": "ObjectType",
            "oid": oid,
            "syntax": syntax,  # (type, module), subtype
            "origName": origName,
        }

        parents = [syntax[0][0]]

        if augmention:
            parents.append(self.trans_opers(augmention))

        if defval:  # XXX
            symProps["defval"] = defval

        if index and index[1]:
            namepart, fakeIndexes, fakeSymSyntax = index
            for fakeIdx, fakeSyntax in zip(fakeIndexes, fakeSymSyntax, strict=False):
                fakeName = namepart + str(fakeIdx)

                fakeSymProps = {
                    "type": "fakeColumn",
                    "oid": (*oid, fakeIdx),
                    "syntax": fakeSyntax,
                    "origName": fakeName,
                }

                self.reg_sym(fakeName, fakeSymProps)

        self.reg_sym(pysmiName, symProps, parents)

    # noinspection PyUnusedLocal
    def gen_trap_type(self, data: Any, classmode: bool = False) -> None:
        """Record a TRAP-TYPE clause as a notification.

        SMIv1 traps have no OID of their own; theirs is built from the
        enterprise OID, a zero, and the trap number, which is how SMIv2 names
        the same notification.

        Args:
            data: converted clause values
            classmode: unused; the clause never appears in a type declaration
        """
        origName, enterprise, _variables, _description, _reference, value = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "NotificationType", "oid": (*enterprise, 0, value), "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # noinspection PyUnusedLocal
    def gen_type_declaration(self, data: Any, classmode: bool = False) -> None:
        """Record a type declaration and the type it derives from.

        A declaration with no parent type is a SEQUENCE, which defines no symbol
        of its own and is skipped.

        Args:
            data: converted clause values
            classmode: unused
        """
        origName, declaration = data

        pysmiName = self.trans_opers(origName)

        if declaration:
            parentType, _attrs = declaration
            if parentType:  # skipping SEQUENCE case
                symProps = {
                    "type": "TypeDeclaration",
                    "syntax": declaration,  # (type, module), subtype
                    "origName": origName,
                }

                self.reg_sym(pysmiName, symProps, [declaration[0][0]])

    # noinspection PyUnusedLocal
    def gen_value_declaration(self, data: Any, classmode: bool = False) -> None:
        """Record a plain OID assignment.

        Args:
            data: converted clause values
            classmode: unused
        """
        origName, oid = data

        pysmiName = self.trans_opers(origName)

        symProps = {"type": "MibIdentifier", "oid": oid, "origName": origName}

        self.reg_sym(pysmiName, symProps)

    # Subparts generation functions
    # noinspection PyUnusedLocal,PyMethodMayBeStatic
    def gen_bit_names(self, data: Any, classmode: bool = False) -> Any:
        """Return the names listed in a BITS or enumeration clause.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The names, in the order they were written.
        """
        names = data[0]
        return names

    # noinspection PyUnusedLocal,PyMethodMayBeStatic
    def gen_bits(self, data: Any, classmode: bool = False) -> tuple[tuple[str, str], list[Any]]:
        """Return the syntax of a BITS clause.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The ``Bits`` type, with no defining module, and the bits
            themselves, each a name and its value.
        """
        bits = data[0]
        return ("Bits", ""), bits

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_compliances(self, data: Any, classmode: bool = False) -> str:
        """Ignore a MODULE-COMPLIANCE body; it defines no symbols.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal
    def gen_conceptual_table(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Note the row a table contains and return the table's syntax.

        The row name is remembered so that :py:meth:`gen_row` can recognise it
        later as a row rather than an ordinary type.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The ``MibTable`` type, with no defining module, and no subtype.
        """
        row = data[0]
        if row[0] and row[0][0]:
            self._rows.add(self.trans_opers(row[0][0]))
        return ("MibTable", ""), ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_contact_info(self, data: Any, classmode: bool = False) -> str:
        """Ignore CONTACT-INFO text.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_display_hint(self, data: Any, classmode: bool = False) -> str:
        """Ignore a DISPLAY-HINT.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal
    def gen_def_val(self, data: Any, classmode: bool = False) -> str | list[Any]:  # XXX should be fixed, see pysnmp.py
        """Render a DEFVAL as the Python source for that value.

        Numbers, hexadecimal and binary strings, quoted strings, bit lists and
        references to other symbols each render differently.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            Python source for the default value.
        """
        defval = data[0]
        val: str | list[Any]

        if isinstance(defval, int):  # number
            val = str(defval)

        elif self.is_hex(defval):  # hex
            val = 'hexValue="' + defval[1:-2] + '"'  # not working for Integer baseTypes

        elif self.is_binary(defval):  # binary
            binval = defval[1:-2]
            hexval = (binval and hex(int(binval, 2))[2:]) or ""
            val = 'hexValue="' + hexval + '"'

        elif isinstance(defval, list):  # bits list
            val = defval

        elif defval[0] == defval[-1] and defval[0] == '"':  # quoted strimg
            val = dorepr(defval[1:-1])

        else:  # symbol (oid as defval) or name for enumeration member
            val = defval + ".getName()" if defval in self._out or defval in self._importMap else dorepr(defval)

        return val

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_description(self, data: Any, classmode: bool = False) -> str:
        """Ignore DESCRIPTION text.

        Returns:
            An empty string.
        """
        return ""

    def gen_reference(self, data: Any, classmode: bool = False) -> str:
        """Ignore REFERENCE text.

        Returns:
            An empty string.
        """
        return ""

    def gen_status(self, data: Any, classmode: bool = False) -> str:
        """Ignore a STATUS clause.

        Returns:
            An empty string.
        """
        return ""

    def gen_product_release(self, data: Any, classmode: bool = False) -> str:
        """Ignore a PRODUCT-RELEASE clause.

        Returns:
            An empty string.
        """
        return ""

    def gen_enum_spec(self, data: Any, classmode: bool = False) -> list[Any]:
        """Return the names of an enumeration's members.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The members, each a name and its value.
        """
        return self.gen_bits(data, classmode=classmode)[1]

    def gen_index_clause(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Work out which INDEX entries need a synthetic column.

        SMIv1 allows an index to name a bare type instead of a column. Such an
        index has no column to point at, so one is invented here and recorded by
        :py:meth:`gen_object_type`.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The prefix used to name synthetic columns, the sub-identifier of
            each one, and its syntax.
        """
        indexes = data[0]

        fakeIdxName = "pysmiFakeCol"
        fakeIndexes, fakeSymsSyntax = [], []

        for idx in indexes:
            idxName = idx[1]
            if idxName in self.smiv1IdxTypes:  # SMIv1 support
                idxType = idxName

                objType = self.typeClasses.get(idxType, idxType)
                objType = self.trans_opers(objType)

                fakeIndexes.append(self.fakeidx)
                fakeSymsSyntax.append((("MibTableColumn", ""), objType))
                self.fakeidx += 1

        return fakeIdxName, fakeIndexes, fakeSymsSyntax

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_integer_sub_type(self, data: Any, classmode: bool = False) -> str:
        """Ignore an integer range restriction.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_max_access(self, data: Any, classmode: bool = False) -> str:
        """Ignore a MAX-ACCESS clause.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_octet_string_sub_type(self, data: Any, classmode: bool = False) -> str:
        """Ignore an octet string size restriction.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal
    def gen_oid(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Resolve an OID into sub-identifiers and the modules they come from.

        Each name in the OID is recorded as a parent, so that a symbol is not
        registered before the symbols its OID is relative to.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            One element per sub-identifier: a number, or a name paired with the
            module that defines it.

        Raises:
            PySmiSemanticError: a sub-identifier is neither a name nor a number.
        """
        out: tuple[Any, ...] = ()
        for el in data[0]:
            if isinstance(el, str):
                parent = self.trans_opers(el)
                self._parentOids.add(parent)
                out += ((parent, self._importMap.get(parent, self.moduleName[0])),)

            elif isinstance(el, int):
                out += (el,)

            elif isinstance(el, tuple):
                out += (el[1],)  # XXX Do we need to create a new object el[0]?

            else:
                raise error.PySmiSemanticError(f"unknown datatype for OID: {el}")

        return out

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_objects(self, data: Any, classmode: bool = False) -> str:
        """Ignore an OBJECTS or NOTIFICATIONS list.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_time(self, data: Any, classmode: bool = False) -> str:
        """Ignore a timestamp.

        Returns:
            An empty string.
        """
        return ""

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_last_updated(self, data: Any, classmode: bool = False) -> str:
        """Return the LAST-UPDATED timestamp.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The timestamp as written.
        """
        return cast(str, data[0])

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_organization(self, data: Any, classmode: bool = False) -> str:
        """Return the ORGANIZATION text.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The organization as written.
        """
        return cast(str, data[0])

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_revisions(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Return the module's most recent revision.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The revision date and its description.
        """
        lastRevision, lastDescription = data[0][0][0], data[0][0][1][1]
        return lastRevision, lastDescription

    def gen_row(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Return the syntax of a table row.

        A name already seen as a table's row is a row; anything else is an
        ordinary type and is resolved as one.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The ``MibTableRow`` type with no subtype, or whatever
            :py:meth:`gen_simple_syntax` makes of the name.
        """
        row = data[0]
        row = self.trans_opers(row)
        return (row in self._rows and (("MibTableRow", ""), "")) or self.gen_simple_syntax(data, classmode=classmode)

    # noinspection PyUnusedLocal
    def gen_sequence(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Record the columns of a SEQUENCE.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            Empty type and subtype; a SEQUENCE defines no symbol itself.
        """
        cols = data[0]
        self._cols.update(cols)
        return "", ""

    # noinspection PyUnusedLocal
    def gen_simple_syntax(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Resolve a type name to the type and the module that defines it.

        SMIv1 type names are mapped to their SMIv2 equivalents. A base type has
        no defining module; anything else is attributed to the module it was
        imported from, or to this one.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The type paired with its module, and any subtype restriction.
        """
        objType = data[0]

        module = ""

        objType = self.typeClasses.get(objType, objType)
        objType = self.trans_opers(objType)

        if objType not in self.baseTypes:
            module = self._importMap.get(objType, self.moduleName[0])

        subtype = (len(data) == 2 and data[1]) or ""

        return (objType, module), subtype

    # noinspection PyUnusedLocal,PyMethodMayBeStatic
    def gen_type_declaration_rhs(self, data: Any, classmode: bool = False) -> tuple[Any, ...]:
        """Return the parent type and attributes of a type declaration.

        A textual convention carries display hint, status and text before its
        syntax; a plain declaration is just the syntax.

        Args:
            data: converted clause values
            classmode: unused

        Returns:
            The type derived from and its attributes.
        """
        if len(data) == 1:
            parentType, attrs = data[0]  # just syntax

        else:
            # Textual convention
            _display, _status, _description, _reference, syntax = data
            parentType, attrs = syntax

        return parentType, attrs

    # noinspection PyUnusedLocal,PyUnusedLocal,PyMethodMayBeStatic
    def gen_units(self, data: Any, classmode: bool = False) -> str:
        """Ignore a UNITS clause.

        Returns:
            An empty string.
        """
        return ""

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
        "INDEX": gen_index_clause,
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
    }

    def gen_code(self, ast: Any, symbolTable: dict[str, Any], **kwargs: Any) -> tuple[MibInfo, dict[str, Any]]:
        """Build the symbol table for one parsed MIB module.

        Args:
            ast: parse tree of a single module
            symbolTable: unused; this backend builds the table rather than
                consulting one

        Keyword Args:
            genTexts: accepted for interface compatibility; texts are not
                recorded in the symbol table

        Returns:
            The module's :py:class:`~pysmi.mibinfo.MibInfo` and its symbol
            table. Alongside one entry per symbol, the table carries the order
            symbols were defined in, and the names of the table columns and
            rows the module declares.

        Raises:
            PySmiSemanticError: a symbol is defined twice, an OID names a
                symbol that is never defined, or a symbol derives from one
                that is.
        """
        self.genRules["text"] = kwargs.get("genTexts", False)
        self._rows.clear()
        self._cols.clear()
        self._parentOids.clear()
        self._symsOrder = []
        self._postponedSyms.clear()
        self._importMap.clear()
        self._out = {}  # should be new object, do not use `clear` method
        self.moduleName[0], moduleOid, imports, declarations = ast

        _out, importedModules = self.gen_imports(imports or {})

        for declr in declarations or []:
            if declr:
                clausetype = declr[0]
                classmode = clausetype == "typeDeclaration"
                self.handlersTable[declr[0]](self, self.prep_data(declr[1:], classmode), classmode)

        if self._postponedSyms:
            raise error.PySmiSemanticError("Unknown parents for symbols: {}".format(", ".join(self._postponedSyms)))

        for sym in self._parentOids:
            if sym not in self._out and sym not in self._importMap:
                raise error.PySmiSemanticError(f"Unknown parent symbol: {sym}")

        self._out["_symtable_order"] = list(self._symsOrder)
        self._out["_symtable_cols"] = list(self._cols)
        self._out["_symtable_rows"] = list(self._rows)

        logger.debug(
            "canonical MIB name %s (%s), imported MIB(s) %s, Symbol table size %d symbols",
            self.moduleName[0],
            moduleOid,
            ",".join(importedModules) or "<none>",
            len(self._out),
            extra={
                "mib": self.moduleName[0],
                "oid": str(moduleOid),
                "imported": list(importedModules),
                "symbols": len(self._out),
            },
        )

        return MibInfo(
            oid=None, name=self.moduleName[0], revision=self._moduleRevision, imported=tuple(x for x in importedModules)
        ), self._out
