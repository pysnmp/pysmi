#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2020, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""What a corpus build does to a document once the compiler has produced one.

Writing it, reading it back, and hashing its canonical form: the three things
:py:mod:`pysmi.corpus.db` does for every module in a corpus of several
thousand, so a change here is multiplied by the size of the corpus.

Also here are the text scans the readers run over every file they index --
they never parse a MIB, but they do touch every byte of one.
"""

import json
from typing import Any

from benchmarks.workload import LARGE, MEDIUM, ast_of, mib_text, symbol_table
from pysmi import jsonio
from pysmi.codegen import JsonCodeGen
from pysmi.codegen.normalized import canonical_form, content_hash, structure_hash
from pysmi.mibinfo import module_names, source_digest, strip_comments


def document(mibname: str) -> dict[str, Any]:
    """Return the JSON document the compiler renders *mibname* into."""
    _, rendered = JsonCodeGen().gen_code(
        ast_of(mibname), dict(symbol_table(mibname)), genTexts=True
    )
    return json.loads(rendered)


def test_jsonio_dumps(benchmark: Any) -> None:
    """Write a module's JSON document out compactly."""
    doc = document(MEDIUM)

    text = benchmark(jsonio.dumps, doc)

    assert text.startswith("{")


def test_jsonio_loads(benchmark: Any) -> None:
    """Read a module's JSON document back."""
    text = jsonio.dumps(document(MEDIUM))

    doc = benchmark(jsonio.loads, text)

    assert doc


def test_canonical_form(benchmark: Any) -> None:
    """Reduce a document to the bytes its identity is computed over."""
    doc = document(MEDIUM)

    canonical = benchmark(canonical_form, doc)

    assert canonical


def test_content_hash(benchmark: Any) -> None:
    """Hash a document's canonical form, prose included."""
    doc = document(MEDIUM)

    digest = benchmark(content_hash, doc)

    assert len(digest) == 64


def test_structure_hash(benchmark: Any) -> None:
    """Hash a document's canonical form with the prose dropped."""
    doc = document(MEDIUM)

    digest = benchmark(structure_hash, doc)

    assert len(digest) == 64


def test_module_names(benchmark: Any) -> None:
    """Read the module headers out of a file, as a reader indexing a directory does."""
    text = mib_text(LARGE)

    names = benchmark(module_names, text)

    assert LARGE in names


def test_strip_comments(benchmark: Any) -> None:
    """Strip ASN.1 comments, which is how LAST-UPDATED is read without parsing."""
    text = mib_text(LARGE)

    stripped = benchmark(strip_comments, text)

    assert stripped


def test_source_digest(benchmark: Any) -> None:
    """Digest MIB text, which the compiler does for every source it fetches."""
    text = mib_text(LARGE)

    digest = benchmark(source_digest, text)

    assert digest
