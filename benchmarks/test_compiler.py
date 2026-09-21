#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Compiling a MIB end to end: fetch, parse, index, render, write.

This is what ``mibdump`` does and what pysnmp calls when a MIB is missing, so
it is the figure a user would recognise. The MIB text is served from memory
through a :py:class:`~pysmi.reader.CallbackReader` and the output is dropped
by a :py:class:`~pysmi.writer.CallbackWriter`: a benchmark has no business
measuring the filesystem, and the bundled source is read once at staging
rather than once per iteration.
"""

from typing import Any

from benchmarks.workload import BATCH, MEDIUM, parser, texts
from pysmi.codegen import JsonCodeGen, PySnmpCodeGen
from pysmi.compiler import MibCompiler
from pysmi.reader import CallbackReader
from pysmi.writer import CallbackWriter


def compile_mibs(codegen: Any, sources: dict[str, str], mibnames: tuple[str, ...]):
    """Compile *mibnames* out of *sources* with a compiler of its own.

    A compiler remembers what it has already resolved, so reusing one would
    measure the second compile rather than the first. Building one costs a
    dictionary and two objects -- the parser, which is what is expensive to
    build, is shared.
    """
    mibCompiler = MibCompiler(
        parser(),
        codegen(),
        CallbackWriter(lambda mibname, contents, context: None),
        useBundledMibs=False,
    )
    mibCompiler.add_sources(
        CallbackReader(lambda mibname, context: sources.get(mibname))
    )

    return mibCompiler.compile(*mibnames)


def test_compile_to_json(benchmark: Any) -> None:
    """Compile one MIB and its IMPORTS closure into JSON documents."""
    sources = texts(MEDIUM)

    processed = benchmark(compile_mibs, JsonCodeGen, sources, (MEDIUM,))

    assert str(processed[MEDIUM]) == "compiled"


def test_compile_to_pysnmp(benchmark: Any) -> None:
    """Compile one MIB and its IMPORTS closure into pysnmp modules."""
    sources = texts(MEDIUM)

    processed = benchmark(compile_mibs, PySnmpCodeGen, sources, (MEDIUM,))

    assert str(processed[MEDIUM]) == "compiled"


def test_compile_batch(benchmark: Any) -> None:
    """Compile several unrelated MIBs in one call.

    Their closures overlap, which is the case the compiler's own bookkeeping
    exists for: a module reached twice must be parsed once.
    """
    sources = texts(*BATCH)

    processed = benchmark(compile_mibs, JsonCodeGen, sources, BATCH)

    assert all(str(processed[mibname]) == "compiled" for mibname in BATCH)
