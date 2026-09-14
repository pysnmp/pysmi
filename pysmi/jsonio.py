#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: https://github.com/pysnmp/pysmi/blob/main/LICENSE.rst
#
"""Writing and reading the JSON a corpus publishes.

Two decisions live here, and they are worth very different amounts.

**The documents are written compactly.** ``json/`` is a generated tree that
nobody reads by eye, and indenting it costs about 30% of its size on disk --
roughly 50 MB over the corpus pysnmp/mibs publishes. It costs build time too:
pretty-printing is the expensive part of :py:func:`json.dumps`, about four
times the cost of writing the same document compactly. Gzipped the difference
is 8%, because gzip already eats indentation, so this is a saving on a
checkout, an image and a Pages site rather than on bandwidth.

Human-facing JSON is not written through here and stays indented: a build
report is read by a person looking at a failed build, and the precedence and
conformance vectors are fixtures reviewed in diffs.

**A faster implementation is used when one is installed, and never required.**
``pysmi[fast]`` pulls in orjson; msgspec is taken if it is there instead.
Either is roughly 14x on writing a document and 1.7x on reading one, and both
together are about 4% of a real build, because SMI parsing dominates
everything else -- :py:mod:`pysmi.corpus.driver` puts parsing at about three
quarters of a pass. 4% does not buy a wheel with a compiled extension in it
for everyone, so this is an extra with a stdlib fallback.

The constraint that shapes the module: **the bytes must not depend on which
implementation is installed.** A corpus build is fingerprinted byte for byte,
and a build with the extra that disagreed with one without it would end the
reproducibility the driver opens on. The stdlib is the reference, the faster
encoders are used only where they agree with it, and
``tests/test_jsonio.py`` asserts the agreement over every document the
bundled corpus produces rather than trusting that it holds.

That is also why :py:data:`SEPARATORS` goes with ``ensure_ascii=False``.
Neither orjson nor msgspec can escape a non-ASCII character, so writing UTF-8
as itself is the only setting all three agree on -- and it is the one
:py:mod:`pysmi.codegen.normalized` already fingerprints with.
"""

import json
from collections.abc import Callable
from typing import Any

#: No space after ``,`` or ``:``, which is what compact means. The same pair
#: :py:mod:`pysmi.corpus.db` writes its stored type specifications with.
SEPARATORS = (",", ":")

#: Implementations in the order they are taken, fastest first. The stdlib is
#: last and always present, so this never comes up empty.
PREFERENCE = ("orjson", "msgspec", "json")


def _stdlib_dumps(value: Any) -> str:
    """The reference rendering. Every other encoder has to match this."""
    return json.dumps(value, separators=SEPARATORS, ensure_ascii=False)


#: Encoder per implementation name, holding only the ones importable here.
#: A test walks it to check they agree; nothing else should need it.
ENCODERS: dict[str, Callable[[Any], str]] = {"json": _stdlib_dumps}

#: Decoder per implementation name, alongside :py:data:`ENCODERS`.
DECODERS: dict[str, Callable[[str], Any]] = {"json": json.loads}

try:
    import orjson

except ImportError:
    pass

else:
    # orjson writes compact UTF-8 and nothing else, so there is nothing to
    # configure: its one rendering is the one the stdlib is asked for above.
    ENCODERS["orjson"] = lambda value: orjson.dumps(value).decode("utf-8")
    DECODERS["orjson"] = orjson.loads

try:
    import msgspec.json

except ImportError:
    pass

else:
    _ENCODER = msgspec.json.Encoder()
    _DECODER = msgspec.json.Decoder()

    ENCODERS["msgspec"] = lambda value: _ENCODER.encode(value).decode("utf-8")
    DECODERS["msgspec"] = _DECODER.decode

#: The implementation in use, one of :py:data:`PREFERENCE`. Reported on a
#: build so that a run can be told apart from one that resolved differently.
IMPLEMENTATION: str = next(name for name in PREFERENCE if name in ENCODERS)


def dumps(value: Any) -> str:
    """Render a corpus document compactly.

    Args:
        value: what to write -- a jsondoc, or an index of them.

    Returns:
        The JSON, on one line, with UTF-8 written as itself. The same bytes
        whichever implementation is installed.
    """
    if IMPLEMENTATION != "json":
        try:
            return ENCODERS[IMPLEMENTATION](value)

        except (TypeError, ValueError):
            # Something the faster encoder will not take and the stdlib will,
            # a non-string mapping key being the usual one. Falling back keeps
            # an installed extra from turning a document into an error.
            pass

    return _stdlib_dumps(value)


def loads(text: str) -> Any:
    """Read a corpus document back.

    Args:
        text: the JSON, as a document or an index was written.

    Returns:
        What it holds.

    Raises:
        ValueError: it is not JSON. Which implementation read it does not
            change that, though the message it carries differs.
    """
    return DECODERS[IMPLEMENTATION](text)
