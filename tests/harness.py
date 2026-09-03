#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://www.pysnmp.com/pysmi/license.html
#
"""Render a MIB through both backends and hand back both artifacts."""

import json

from pysnmp.smi.builder import MibBuilder

from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.codegen.symtable import SymtableCodeGen
from pysmi.parser.smi import parserFactory


def parse(mib, **dialect):
    """Parse *mib*, optionally with parser relaxation options."""
    return parserFactory(**dialect)().parse(mib)[0]


def symbol_table(mib, deps=(), genTexts=True, **dialect):
    """Build the symbol table for *mib*, resolving *deps* into it first.

    A DEFVAL or a sub-typed textual convention makes the codegens walk the
    imported type back to its base, so any module named in IMPORTS has to be in
    the table. See tests.mibs for the stubs that stand in for the standard ones.

    Returns:
        A tuple of the parsed AST, the module name and the whole symbol table.
    """
    table = {}
    for dep in deps:
        depInfo, depTable = SymtableCodeGen().gen_code(parse(dep, **dialect), dict(table), genTexts=genTexts)
        table[depInfo.name] = depTable

    ast = parse(mib, **dialect)
    mibInfo, symtable = SymtableCodeGen().gen_code(ast, dict(table), genTexts=genTexts)
    table[mibInfo.name] = symtable

    return ast, mibInfo.name, table


def render_json(mib, deps=(), genTexts=True, **dialect):
    """Compile *mib* through the JSON backend and decode the document."""
    ast, _, table = symbol_table(mib, deps=deps, genTexts=genTexts, **dialect)
    _, doc = JsonCodeGen().gen_code(ast, table, genTexts=genTexts)
    return json.loads(doc)


def render_source(mib, deps=(), genTexts=True, **dialect):
    """Compile *mib* through the pysnmp backend and hand back the source.

    The generated module is the product. ``render_pysnmp`` hands back only what
    executing it built, which cannot show how a line was written -- whether a
    setter carries its ``mibBuilder.loadTexts`` guard, say.
    """
    ast, _, table = symbol_table(mib, deps=deps, genTexts=genTexts, **dialect)
    _, pycode = PySnmpCodeGen().gen_code(ast, table, genTexts=genTexts)
    return pycode


def render_pysnmp(mib, deps=(), genTexts=True, **dialect):
    """Compile *mib* through the pysnmp backend and execute the generated module."""
    pycode = render_source(mib, deps=deps, genTexts=genTexts, **dialect)

    mibBuilder = MibBuilder()
    mibBuilder.loadTexts = genTexts
    ctx = {"mibBuilder": mibBuilder}
    exec(compile(pycode, "test", "exec"), ctx, ctx)
    return ctx


def render(mib, deps=(), genTexts=True, **dialect):
    """Compile *mib* through both backends.

    Returns:
        A tuple of the decoded JSON document and the pysnmp module scope.
    """
    return (
        render_json(mib, deps=deps, genTexts=genTexts, **dialect),
        render_pysnmp(mib, deps=deps, genTexts=genTexts, **dialect),
    )
