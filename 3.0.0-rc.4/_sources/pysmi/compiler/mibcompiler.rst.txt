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
modules.

The parse cache belongs to the compiler, so it is kept across
:py:meth:`~pysmi.compiler.MibCompiler.compile` calls and the standard tree is
parsed once. What loses it is building a new compiler per namespace -- and a
shell loop, which starts a fresh process each time, can do nothing else. That
is the shape the standard tree ends up parsed once per namespace in.

:py:meth:`~pysmi.compiler.MibCompiler.set_sources` replaces the configured
sources on a compiler that is already built, so one compiler can be driven
across every namespace instead:

.. code-block:: python

   from pysmi.codegen import JsonCodeGen
   from pysmi.compiler import MibCompiler
   from pysmi.parser import SmiV1CompatParser
   from pysmi.reader import FileReader
   from pysmi.writer import CallbackWriter

   documents = {}

   def store(mibname, data, cbCtx):
       documents[mibname] = data

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

Choosing where the trees are kept
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The cache is a component, passed to the constructor. The *Parse caches* section
of the library reference lists the ones pysmi ships and the interface a provider
implements.

:py:class:`~pysmi.cache.memory.InMemoryParseCache` is the default: bounded,
least-recently-used evicted, so the shared modules stay resident while
per-namespace ones do not accumulate. It is the right answer whenever the whole
build runs in one process.

:py:class:`~pysmi.cache.file.FileParseCache` keeps trees in a directory, so they
outlive the process that built them. That is what a build driven as a shell loop
needs -- a fresh interpreter per namespace has nothing in memory to reuse:

.. code-block:: python

   from pysmi.cache import FileParseCache

   compiler = MibCompiler(
       SmiV1CompatParser(),
       JsonCodeGen(),
       CallbackWriter(store),          # as above
       parseCache=FileParseCache("/var/cache/pysmi"),
   )

Reading that cache unpickles, which reconstructs arbitrary Python objects, so
point it only at a directory your own build writes. The in-memory provider has
no such boundary. A provider is always used as passed and never resolved by
name, from an entry point or from configuration -- the trust boundary is the
calling code.

:py:class:`~pysmi.cache.null.NullParseCache` turns caching off, which is the
behaviour of every release before it existed.

To write your own -- Redis, memcached, a shared filesystem, whatever a build
already runs -- implement
:py:class:`~pysmi.cache.base.AbstractParseCache`. No registration step exists
because none is needed. Two things a provider does *not* have to do:
invalidation, since the key already carries the text together with the identity
of what would parse it -- the pysmi version, the parser class, its grammar
relaxations and its start symbol -- so an entry written by another release, or
by a different SMI dialect, is never read by this one; and defensive copying,
since the compiler copies whatever it receives.

The dialect matters as much as the version here. ``parserFactory`` names every
specialization it builds ``SmiParser``, so all three shipped parsers share a
class identity while accepting different grammars: a trailing comma in
``IMPORTS`` parses under ``SmiV1CompatParser`` and raises under
``SmiV2Parser``.

:py:meth:`~pysmi.compiler.MibCompiler.clear_parse_cache` empties whichever
provider is configured. It is never needed for correctness.
