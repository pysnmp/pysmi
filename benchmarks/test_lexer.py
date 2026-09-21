#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Tokenising ASN.1, which every other stage is downstream of.

Measured on its own because the parse figures next door cannot say whether a
change moved the scanner or the grammar, and the two are tuned differently.
"""

from typing import Any

import pytest

from benchmarks.workload import LARGE, MEDIUM, SMALL, mib_text
from pysmi.lexer.smi import lexerFactory
from pysmi.parser.dialect import smiV1Relaxed

#: The widest dialect pysmi scans, and the one the compiler reaches for when
#: it does not know what it has been handed.
RelaxedLexer = lexerFactory(**smiV1Relaxed)


def tokenize(lexer: Any, text: str) -> int:
    """Scan *text* to its end, returning how many tokens it held."""
    lexer.reset()
    lexer.lexer.input(text)

    count = 0
    while lexer.lexer.token() is not None:
        count += 1

    return count


@pytest.mark.parametrize("mibname", [SMALL, MEDIUM, LARGE])
def test_tokenize(benchmark: Any, mibname: str) -> None:
    """Scan a bundled MIB into tokens."""
    lexer = RelaxedLexer()
    text = mib_text(mibname)

    count = benchmark(tokenize, lexer, text)

    assert count > 0


def test_lexer_construction(benchmark: Any) -> None:
    """Build a lexer for the relaxed dialect.

    PLY compiles the master regexp on every construction, and the parser
    builds one of these -- so this is part of what a ``mibdump`` invocation
    pays before it has read a byte of MIB.
    """
    lexer = benchmark(RelaxedLexer)

    assert lexer.lexer is not None
