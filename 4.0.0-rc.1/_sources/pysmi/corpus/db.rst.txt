.. _corpus.db:

Corpus database
---------------

The SMI model laid out for lookup rather than for reading: one row per node,
keyed by OID and by name and ordered so a GETNEXT walk is a range query. The
file format is specified in :doc:`/corpus-schema`, and its consumer reads it
with stdlib ``sqlite3`` rather than by importing any of this.

The writer
~~~~~~~~~~

.. automodule:: pysmi.corpus.db
  :members:

Conformance
~~~~~~~~~~~

A fixed corpus and the answers any reader of it must give, so that a reader
written against :doc:`/corpus-schema` can be checked against the writer that
produces real corpora rather than against itself.

.. automodule:: pysmi.corpus.conformance
  :members:
