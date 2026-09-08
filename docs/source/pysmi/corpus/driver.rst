.. _corpus.driver:

Corpus driver
-------------

Builds a whole corpus from a declared set of source namespaces, so that two
runs over the same inputs produce the same bytes. :ref:`mibcorpus` is the
command-line frontend to it.

.. automodule:: pysmi.corpus
  :no-members:

The input set
~~~~~~~~~~~~~

.. automodule:: pysmi.corpus.namespace
  :members:

The build
~~~~~~~~~

.. automodule:: pysmi.corpus.driver
  :members:
  :exclude-members: CorpusOutputs, CorpusReport, Destination

Where the artifacts go, and what the build did:

.. autoclass:: pysmi.corpus.driver.Destination

.. autoclass:: pysmi.corpus.driver.CorpusOutputs

.. autoclass:: pysmi.corpus.driver.CorpusReport

