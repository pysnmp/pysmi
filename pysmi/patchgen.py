#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Turning a repair pysmi would make in memory into a diff against the source.

``pysmi.codegen.symtable`` repairs a module that uses an SMIv2 base symbol
without naming it in IMPORTS, and does so as the module compiles: the repair
lives for the length of the run that made it and leaves the source alone. That
is the right default for consuming a MIB and the wrong one for owning a tree of
them, where the same defect is rediscovered on every run and nobody ever sees
the correction written down.

This module makes the other choice available. It finds the same defect the
compiler does, works out the same correction, and then writes it into the
module's *text* rather than into a symbol table -- so it can be handed to
:py:func:`~pysmi.patches.make_patch` and kept as a diff. Patch a tree once, and
the repair is in version control, visible before anything runs, and the compiler
can be told to stop repairing anything at all.

What can be generated is exactly what can be *decided*. A missing base-SMI
import can be: the symbol is undefined, unimported, and exactly one base module
exports it, so there is nothing to guess at. A MIB that does not parse cannot
be, because there is no symbol table to reason from -- those repairs are still
written by hand, and :py:class:`Defect` reports them as needing one.
"""

import logging
import re
from typing import NamedTuple

from pysmi import error
from pysmi.codegen.base import REPAIRED_IMPORTS_KEY
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory
from pysmi.patches import make_patch

logger = logging.getLogger(__name__)

#: The module did parse, and every repair it needed could be worked out.
REPAIRABLE = "repairable"

#: The module did parse and needs nothing -- no patch is written for it.
CLEAN = "clean"

#: The module does not parse, so there is no symbol table to reason from and
#: no repair can be derived. A patch for it has to be written by hand.
UNPARSEABLE = "unparseable"

_IMPORTS = re.compile(r"^[ \t]*IMPORTS\b[ \t]*(--.*)?$")

_FROM = re.compile(r"^([ \t]*)FROM[ \t]+([A-Za-z0-9-]+)[ \t]*(;)?[ \t]*(--.*)?$")

_BEGIN = re.compile(r"\bDEFINITIONS\b.*::=[ \t]*BEGIN\b")

#: Indentation for a symbol list and its ``FROM``, used only when the module
#: has no IMPORTS clause to copy the shape of. Four and eight spaces is what
#: the RFC-published modules overwhelmingly use.
_SYMBOL_INDENT = "    "
_FROM_INDENT = "        "


class Defect(NamedTuple):
    """What one module in a scanned tree needs, and whether it can be given it."""

    #: The module's name, taken from its text rather than its file name.
    mibname: str

    #: :py:data:`REPAIRABLE`, :py:data:`CLEAN` or :py:data:`UNPARSEABLE`.
    status: str

    #: Base-SMI symbols the module uses without importing, mapped to the module
    #: that exports each. Empty unless *status* is :py:data:`REPAIRABLE`.
    imports: dict[str, str]

    #: Why the module could not be read, when *status* is
    #: :py:data:`UNPARSEABLE`. Empty otherwise.
    reason: str

    #: The diff that repairs it, or ``""`` when there is nothing to write.
    patch: str


def _clause_bounds(lines: list[str]) -> tuple[int, int] | None:
    """Find the IMPORTS clause, as the half-open line range it spans.

    Returns:
        The line the ``IMPORTS`` keyword is on and the line after the ``;``
        that ends the clause, or ``None`` when the module has no IMPORTS
        clause at all.
    """
    for index, line in enumerate(lines):
        if not _IMPORTS.match(line):
            continue

        for end in range(index + 1, len(lines)):
            # A ';' inside a comment does not end the clause, and the clause
            # holds nothing else a ';' could hide in -- no strings, no OIDs.
            if ";" in re.sub(r"--.*", "", lines[end]):
                return index, end + 1

        return index, len(lines)

    return None


def _add_to_existing_group(
    lines: list[str], start: int, end: int, module: str, symbol: str
) -> bool:
    """Append *symbol* to the ``FROM`` group for *module*, if there is one.

    Appending to the symbol line rather than opening a new one keeps the diff
    to the single line that actually changed.

    Returns:
        Whether a group for *module* was found and amended.
    """
    for index in range(start, end):
        found = _FROM.match(lines[index])

        if not found or found[2] != module:
            continue

        # The symbol list is whatever sits above the FROM, so the last line
        # with anything on it is the one to extend.
        for above in range(index - 1, start - 1, -1):
            stripped = re.sub(r"--.*", "", lines[above]).rstrip()

            if stripped and not stripped.endswith(","):
                lines[above] = f"{stripped}, {symbol}"
                return True

            if stripped.endswith(","):
                lines[above] = f"{stripped} {symbol},"
                return True

        return False

    return False


def _add_new_group(
    lines: list[str], start: int, end: int, module: str, symbols: list[str]
) -> None:
    """Open a ``FROM`` group for *module* at the end of the clause.

    The ``;`` that ended the clause moves onto the new group, which is what
    makes this a three-line diff rather than a rewrite of the whole clause.
    """
    symbol_indent, from_indent = _SYMBOL_INDENT, _FROM_INDENT
    terminator = end - 1

    for index in range(end - 1, start - 1, -1):
        found = _FROM.match(lines[index])

        if found:
            from_indent = found[1]
            terminator = index
            break

    for index in range(terminator - 1, start - 1, -1):
        if re.sub(r"--.*", "", lines[index]).strip():
            symbol_indent = lines[index][
                : len(lines[index]) - len(lines[index].lstrip())
            ]
            break

    lines[terminator] = lines[terminator].replace(";", "", 1).rstrip()
    lines.insert(terminator + 1, f"{from_indent}FROM {module};")
    lines.insert(terminator + 1, f"{symbol_indent}{', '.join(symbols)}")


def _open_clause(lines: list[str], missing: dict[str, str]) -> bool:
    """Write a whole IMPORTS clause into a module that has none.

    Returns:
        Whether the module's ``DEFINITIONS ::= BEGIN`` could be found to put
        the clause after. A module without one did not parse, so in practice
        this only fails on text this module was never given.
    """
    for index, line in enumerate(lines):
        if not _BEGIN.search(re.sub(r"--.*", "", line)):
            continue

        clause = ["", "IMPORTS"]

        for module, symbols in _grouped(missing).items():
            clause.append(f"{_SYMBOL_INDENT}{', '.join(symbols)}")
            clause.append(f"{_FROM_INDENT}FROM {module}")

        clause[-1] += ";"

        lines[index + 1 : index + 1] = clause

        return True

    return False


def _grouped(missing: dict[str, str]) -> dict[str, list[str]]:
    """Turn ``{symbol: module}`` into ``{module: [symbol]}``, both sorted."""
    grouped: dict[str, list[str]] = {}

    for symbol, module in sorted(missing.items()):
        grouped.setdefault(module, []).append(symbol)

    return {module: grouped[module] for module in sorted(grouped)}


def repair_imports(text: str, missing: dict[str, str]) -> str:
    """Write the missing imports into a module's text.

    Args:
        text: the module's ASN.1 source.
        missing: base-SMI symbols it omits, mapped to the module exporting
            each -- what :py:meth:`~pysmi.codegen.symtable.SymtableCodeGen.missing_canonical_imports`
            found.

    Returns:
        The text with its IMPORTS clause amended, or unchanged when *missing*
        is empty or the clause could not be located.
    """
    if not missing:
        return text

    crlf = "\r\n" in text
    lines = text.replace("\r\n", "\n").split("\n")

    bounds = _clause_bounds(lines)

    if bounds is None:
        if not _open_clause(lines, missing):
            return text

    else:
        start, end = bounds

        for module, symbols in _grouped(missing).items():
            fresh = [
                symbol
                for symbol in symbols
                if not _add_to_existing_group(lines, start, end, module, symbol)
            ]

            if fresh:
                _add_new_group(lines, start, end, module, fresh)
                end += 2

    out = "\n".join(lines)

    return out.replace("\n", "\r\n") if crlf else out


def missing_imports(text: str) -> tuple[str, dict[str, str]]:
    """Parse a module and report the base-SMI imports it leaves out.

    The same question ``pysmi.codegen.symtable`` asks itself as it
    compiles, asked here without compiling anything: the symbol table is built
    for this module alone, which is all
    :py:meth:`~pysmi.codegen.symtable.SymtableCodeGen.missing_canonical_imports`
    consults.

    Args:
        text: the module's ASN.1 source.

    Returns:
        The module's name and the symbols it omits, mapped to the module that
        exports each. The mapping is empty for a module that imports
        everything it uses.

    Raises:
        PySmiError: the module does not parse, or parses into something the
            symbol table cannot be built from.
    """
    ast = parserFactory()().parse(text)[0]

    info, table = SymtableCodeGen().gen_code(ast, {}, repairImports=True)

    return info.name, dict(table.get(REPAIRED_IMPORTS_KEY) or {})


def inspect(text: str, mibname: str = "") -> Defect:
    """Work out what one module needs and cut the diff that gives it.

    Args:
        text: the module's ASN.1 source.
        mibname (str): what to call it if it cannot be parsed, since an
            unparseable module cannot be asked its own name. The name in the
            text wins whenever there is one.

    Returns:
        The :py:class:`Defect`, carrying a diff when one could be derived.
    """
    try:
        name, missing = missing_imports(text)

    except error.PySmiError as exc:
        logger.info(
            "MIB %s does not parse, so no repair can be derived from it: %s",
            mibname or "<unnamed>",
            exc,
            extra={"mib": mibname, "error": str(exc)},
        )

        return Defect(mibname, UNPARSEABLE, {}, str(exc), "")

    if not missing:
        return Defect(name, CLEAN, {}, "", "")

    repaired = repair_imports(text, missing)

    if repaired == text:
        return Defect(
            name,
            UNPARSEABLE,
            missing,
            "its IMPORTS clause could not be located in the text",
            "",
        )

    return Defect(name, REPAIRABLE, missing, "", make_patch(name, text, repaired))
