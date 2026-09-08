#
# This file is part of pysmi software.
#
# Copyright (c) 2015-2019, Ilya Etingof <etingof@gmail.com>
# License: http://snmplabs.com/pysmi/license.html
#
"""Interface shared by the parse caches, and what a provider must guarantee."""

from typing import Any

from pysmi._aliases import deprecated_camel_case


@deprecated_camel_case
class AbstractParseCache:
    """Base class for parse-tree caches.

    :py:meth:`~pysmi.compiler.MibCompiler.compile` parses a module's ASN.1 text
    into a tree before generating anything from it, and the same text is
    routinely presented again -- every namespace of a corpus build imports the
    same standard modules. A cache holds those trees so the text is parsed once
    per build rather than once per namespace.

    Subclasses implement :py:meth:`get` and :py:meth:`set`.

    **What the compiler guarantees.** The key it supplies is derived from the
    ASN.1 text itself together with the identity of the parser and the pysmi
    version that would parse it. So an entry is only ever offered back for
    byte-identical text parsed by the same producer: two modules sharing a name
    across vendor trees have different keys, and an entry written by a different
    pysmi release is never read by this one. A provider does not need to reason
    about invalidation, and must not attempt its own.

    **What a provider must guarantee.** A value handed back must be equal to the
    value stored, and must not be shared with the copy the compiler already
    holds -- the compiler copies what it receives, so returning a live reference
    to a stored tree is safe, but returning a partially reconstructed one is
    not. A miss is reported by returning ``None``; that is always allowed, so a
    provider may evict, expire or fail soft at will. A cache is an optimisation
    and never a source of truth.

    **Trust.** A provider that serializes -- anything storing trees outside this
    process -- reconstructs arbitrary Python objects on read. Point one only at
    storage you control. The compiler never resolves a provider by name, from an
    entry point, or from configuration: it uses the object it was handed, so the
    trust boundary is the caller's own code.
    """

    def get(self, key: str) -> list[Any] | None:
        """The parse trees stored under *key*, or ``None`` if there are none.

        Args:
            key: opaque cache key supplied by the compiler

        Returns:
            The stored parse trees, or ``None`` on a miss.
        """
        raise NotImplementedError

    def set(self, key: str, trees: list[Any]) -> None:
        """Store *trees* under *key*.

        A provider that cannot store the value -- too large, backend
        unreachable -- should return without raising. Failing to cache is not
        a compilation failure.

        Args:
            key: opaque cache key supplied by the compiler
            trees: parse trees to store
        """
        raise NotImplementedError

    def clear(self) -> None:
        """Discard everything held.

        Never required for correctness, since keys are content-derived. It is
        here for a caller that wants the space back at a known point.
        """
        raise NotImplementedError
