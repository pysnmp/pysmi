#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Parsing ASN.1 into a parse tree.

:py:mod:`pysmi.corpus.driver` puts parsing at about three quarters of a corpus
build, so these are the figures that move a build time.
"""

from typing import Any

import pytest

from benchmarks.workload import LARGE, MEDIUM, SMALL, mib_text, parser
from pysmi.parser import SmiV1CompatParser, SmiV2Parser


@pytest.mark.parametrize("mibname", [SMALL, MEDIUM, LARGE])
def test_parse(benchmark: Any, mibname: str) -> None:
    """Parse a bundled MIB with the relaxed SMIv1 grammar."""
    smiParser = parser()
    text = mib_text(mibname)

    ast = benchmark(smiParser.parse, text)

    assert ast


def test_parse_strict_smiv2(benchmark: Any) -> None:
    """Parse an SMIv2 module with the strict grammar.

    The relaxed grammar carries productions the strict one does not, which
    makes for a larger table and more states to walk. Measuring both says
    what tolerating the dialects costs on text that does not need it.
    """
    smiParser = SmiV2Parser()
    text = mib_text("SNMPv2-MIB")

    ast = benchmark(smiParser.parse, text)

    assert ast


def test_parser_construction(benchmark: Any) -> None:
    """Build the relaxed SMIv1 parser.

    PLY assembles the LALR tables from the grammar every time, since pysmi
    passes no cache directory by default. Every ``mibdump`` run and every
    pysnmp process that compiles a MIB pays this once, before any MIB is
    read.
    """
    smiParser = benchmark(SmiV1CompatParser)

    assert smiParser.tokens
