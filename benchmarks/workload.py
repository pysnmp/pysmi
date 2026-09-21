#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""The MIBs the benchmarks are measured on, and what it takes to stage them.

Everything here reads the ASN.1 bundled in ``pysmi/mibs/asn1``: it ships with
the package, so a benchmark run fetches nothing, and it is the same text on
every machine, so a measurement is comparable across runs.

Three modules stand for three scales, all of them real standard MIBs rather
than fixtures written for the occasion:

* :py:data:`SMALL` -- one table and a handful of scalars.
* :py:data:`MEDIUM` -- the module nearly every other MIB imports from, and the
  one ``mibdump`` is pointed at most often.
* :py:data:`LARGE` -- a module with many tables, textual conventions and
  conformance statements, where the parser rather than the code generator
  dominates.

Staging is cached, since only the measured call belongs in a measurement: the
parse tree and the symbol table a code generator needs are built once per
process and handed to every benchmark that asks for them.
"""

import importlib.resources
from functools import cache, lru_cache
from typing import Any

from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser import SmiV1CompatParser
from pysmi.parser.base import AbstractParser

#: A module small enough that per-module overhead is visible in the figure.
SMALL = "TCP-MIB"

#: The interface MIB: medium sized, imported nearly everywhere, and the most
#: commonly compiled module there is.
MEDIUM = "IF-MIB"

#: One of the largest standard MIBs, at roughly 220 kB of ASN.1.
LARGE = "RMON2-MIB"

#: Several unrelated modules compiled in one call, which is what a consumer
#: asking for a handful of MIBs actually does -- and what exercises the
#: compiler's dependency resolution rather than one module's code path.
BATCH = ("IF-MIB", "ENTITY-MIB", "TCP-MIB", "UDP-MIB")


@cache
def mib_text(mibname: str) -> str:
    """Return the bundled ASN.1 text of *mibname*."""
    source = importlib.resources.files("pysmi.mibs") / "asn1" / mibname
    return source.read_text(encoding="utf-8")


@cache
def texts(*mibnames: str) -> dict[str, str]:
    """Return the bundled text of *mibnames* and of everything they import."""
    collected: dict[str, str] = {}

    pending = list(mibnames)
    while pending:
        mibname = pending.pop()
        if mibname in collected:
            continue

        collected[mibname] = mib_text(mibname)
        pending.extend(imports_of(mibname))

    return collected


@lru_cache(maxsize=1)
def parser() -> AbstractParser:
    """Return the shared relaxed SMIv1 parser.

    Building one costs more than parsing a small MIB with it, and it holds no
    state between modules -- :py:meth:`pysmi.parser.smi.SmiV2Parser.parse`
    resets the lexer as it returns -- so every benchmark shares this one.
    """
    return SmiV1CompatParser()


@cache
def ast_of(mibname: str) -> Any:
    """Return the parse tree of the bundled *mibname*."""
    return parser().parse(mib_text(mibname))[0]


@cache
def imports_of(mibname: str) -> tuple[str, ...]:
    """Return the modules *mibname* imports from."""
    mibInfo, _ = SymtableCodeGen().gen_code(ast_of(mibname), {})
    return tuple(mibInfo.imported)


@cache
def symbol_table(mibname: str, genTexts: bool = True) -> dict[str, Any]:
    """Return the symbol table a code generator needs for *mibname*.

    Every module in the IMPORTS closure is resolved into it, depth first, so
    that a DEFVAL or a sub-typed textual convention can be walked back to its
    base type. A cycle between two modules is broken by taking whichever was
    reached first, which is what the compiler does with one too.
    """
    table: dict[str, Any] = {}
    _resolve(mibname, table, set(), genTexts)
    return table


def _resolve(
    mibname: str, table: dict[str, Any], visiting: set[str], genTexts: bool
) -> None:
    """Add *mibname* and its imports to *table*, dependencies first."""
    if mibname in table or mibname in visiting:
        return

    visiting.add(mibname)

    for dependency in imports_of(mibname):
        _resolve(dependency, table, visiting, genTexts)

    mibInfo, symtable = SymtableCodeGen().gen_code(
        ast_of(mibname), dict(table), genTexts=genTexts
    )
    table[mibInfo.name] = symtable
