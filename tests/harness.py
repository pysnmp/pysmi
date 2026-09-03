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


def render_json(mib, genTexts=True, **dialect):
    """Compile *mib* through the JSON backend and decode the document."""
    ast = parse(mib, **dialect)
    mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=genTexts)
    _, doc = JsonCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=genTexts)
    return json.loads(doc)


def render_pysnmp(mib, genTexts=True, **dialect):
    """Compile *mib* through the pysnmp backend and execute the generated module."""
    ast = parse(mib, **dialect)
    mibInfo, symtable = SymtableCodeGen().gen_code(ast, {}, genTexts=genTexts)
    _, pycode = PySnmpCodeGen().gen_code(ast, {mibInfo.name: symtable}, genTexts=genTexts)

    mibBuilder = MibBuilder()
    mibBuilder.loadTexts = genTexts
    ctx = {"mibBuilder": mibBuilder}
    exec(compile(pycode, "test", "exec"), ctx, ctx)
    return ctx


def render(mib, genTexts=True, **dialect):
    """Compile *mib* through both backends.

    Returns:
        A tuple of the decoded JSON document and the pysnmp module scope.
    """
    return render_json(mib, genTexts=genTexts, **dialect), render_pysnmp(mib, genTexts=genTexts, **dialect)
