.. _corpus.driver:

Corpus driver
-------------

Builds a whole corpus from a declared set of source namespaces, so that two
runs over the same inputs produce the same bytes. :ref:`mibcorpus` is the
command-line frontend to it.

.. autoclass:: pysmi.corpus.namespace.Namespace
  :members:

.. autofunction:: pysmi.corpus.namespace.load_manifest

.. autoclass:: pysmi.corpus.driver.CorpusDriver
  :members:

.. autoclass:: pysmi.corpus.driver.CorpusOutputs
  :members:

.. autoclass:: pysmi.corpus.driver.CorpusReport
  :members:

.. autofunction:: pysmi.corpus.driver.check_disjoint
