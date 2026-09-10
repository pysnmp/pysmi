.. _corpus.index:

OID index ranking
-----------------

Which module owns an OID that more than one of them defines.
:py:meth:`~pysmi.codegen.jsondoc.JsonCodeGen.gen_index` records every module
that defines a given OID; this is the projection of that fact a consumer
resolving an OID to one module to load needs.

.. automodule:: pysmi.corpus.index
  :members:

.. _corpus.precedence:

Precedence vectors
------------------

The ranking rule above, and the one
:py:meth:`~pysmi.compiler.MibCompiler.compile` applies to a module found in
several sources, published as data so that pysnmp's three copies of it cannot
drift from these. See :doc:`/corpus-schema`.

.. automodule:: pysmi.corpus.precedence
  :members:
