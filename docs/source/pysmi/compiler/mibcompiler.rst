.. _compiler.MibCompiler:

MIB compiler
------------

.. autoclass:: pysmi.compiler.MibCompiler
  :members:

.. _compiler.batch:

Compiling many source sets
~~~~~~~~~~~~~~~~~~~~~~~~~~

A corpus build compiles a few hundred vendor namespaces, each with its own
source directory, and every one of them imports the same handful of standard
modules. Driven as a shell loop -- a fresh process per namespace -- that
standard tree is parsed once per namespace, because the parse cache lives in
:py:meth:`~pysmi.compiler.MibCompiler.compile` and dies with the call.

:py:meth:`~pysmi.compiler.MibCompiler.set_sources` replaces the configured
sources on a compiler that is already built, so one compiler can be driven
across every namespace instead:

.. code-block:: python

   from pysmi.codegen import JsonCodeGen
   from pysmi.compiler import MibCompiler
   from pysmi.parser import SmiV1CompatParser
   from pysmi.reader import FileReader
   from pysmi.writer import CallbackWriter

   compiler = MibCompiler(
       SmiV1CompatParser(), JsonCodeGen(), CallbackWriter(store)
   )

   for namespace in namespaces:
       compiler.set_sources(FileReader(namespace.path))
       compiler.compile(*namespace.modules)

Only :py:meth:`~pysmi.compiler.MibCompiler.add_sources` readers are replaced.
The :py:meth:`~pysmi.compiler.MibCompiler.add_priority_sources` ones -- pysmi's
bundled base MIBs among them -- stay registered, because they are the part that
does not vary between namespaces.

Measured over eight namespaces against the bundled sources:

.. list-table::
   :header-rows: 1

   * -
     - wall
     - parses
     - distinct
   * - a fresh compiler each
     - 0.85s
     - 45
     - 14
   * - one compiler, sources swapped
     - 0.45s
     - 14
     - 14

Every parse in the second row is of text not parsed before in that build. The
saving grows with the namespace count, since the shared tree is a fixed cost
paid once rather than once per namespace.

Why swapping sources cannot serve a stale answer
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The cache is keyed by the digest of the text that was parsed, never by module
name. Two namespaces carrying different modules under one name -- ordinary in a
vendor corpus, where a MIB name recurs across trees at different revisions --
are different bytes and therefore different keys, so neither can be served the
other's tree.

What a swap does change is which sources are *asked*, and that takes effect at
once: a module only the previous source set had stops resolving.

The cache is bounded by the ``parseCacheSize`` constructor argument and evicts
least-recently-used, so the shared modules stay resident while per-namespace
ones do not accumulate. :py:meth:`~pysmi.compiler.MibCompiler.clear_parse_cache`
empties it for a driver that wants the memory back at a known point; it is never
needed for correctness.
