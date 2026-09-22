#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Rendering a parse tree, once the symbol table is already built.

Each generator is measured on a tree and a table staged beforehand, so the
figure is the rendering and nothing else. Both destination formats are here:
they walk the same tree through separate code, and a change to the shared base
class can move one without moving the other.
"""

from typing import Any

import pytest

from benchmarks.workload import LARGE, MEDIUM, SMALL, ast_of, symbol_table
from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen


def render(codegen: Any, ast: Any, table: dict[str, Any], genTexts: bool) -> str:
    """Render *ast* with a fresh generator, as the compiler does per module."""
    _, output = codegen().gen_code(ast, dict(table), genTexts=genTexts)
    return output


@pytest.mark.parametrize("mibname", [SMALL, MEDIUM, LARGE])
def test_symbol_table(benchmark: Any, mibname: str) -> None:
    """Build one module's symbol table over a resolved closure.

    The table for everything the module imports is staged first, so what is
    measured is the pass that indexes the module itself.
    """
    ast = ast_of(mibname)
    table = dict(symbol_table(mibname))
    table.pop(mibname, None)

    benchmark(lambda: SymtableCodeGen().gen_code(ast, dict(table), genTexts=True))


@pytest.mark.parametrize("mibname", [SMALL, MEDIUM, LARGE])
def test_json_codegen(benchmark: Any, mibname: str) -> None:
    """Render a MIB as a JSON document, descriptions included."""
    document = benchmark(
        render, JsonCodeGen, ast_of(mibname), symbol_table(mibname), True
    )

    assert document


@pytest.mark.parametrize("mibname", [SMALL, MEDIUM, LARGE])
def test_pysnmp_codegen(benchmark: Any, mibname: str) -> None:
    """Render a MIB as a pysnmp module, descriptions included."""
    source = benchmark(
        render, PySnmpCodeGen, ast_of(mibname), symbol_table(mibname), True
    )

    assert source


def test_json_codegen_without_texts(benchmark: Any) -> None:
    """Render a MIB as JSON with the prose left out.

    ``--generate-mib-texts`` is off by default, so this is the path most
    builds take, and the descriptions it drops are the bulk of the bytes.
    """
    document = benchmark(
        render, JsonCodeGen, ast_of(MEDIUM), symbol_table(MEDIUM, genTexts=False), False
    )

    assert document
