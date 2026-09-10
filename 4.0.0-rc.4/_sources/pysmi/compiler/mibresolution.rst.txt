.. _reader.compiler.MibResolution:

Source resolution
-----------------

*MibResolution* is what :py:meth:`~pysmi.compiler.MibCompiler.resolve` reports:
which copy of a module the configured sources supply, which copies were passed
over, and the rule that chose between them -- answered without compiling
anything, so a build publishing the ASN.1 beside the compiled output can make
the two agree by construction.

.. autoclass:: pysmi.compiler.MibResolution
  :members:

.. _compiler.rank_by_revision:

The rule itself
~~~~~~~~~~~~~~~

The ranking is exposed separately from the resolution that reports it, because
pysnmp implements the same rule over its own candidates and
:py:mod:`pysmi.corpus.precedence` publishes vectors that both sides run. A rule
kept private is a rule the vectors can only approximate.

.. autofunction:: pysmi.compiler.rank_by_revision

.. autodata:: pysmi.compiler.PRECEDENCE_NEWEST_REVISION

.. autodata:: pysmi.compiler.PRECEDENCE_EQUAL_REVISIONS

.. autodata:: pysmi.compiler.PRECEDENCE_NO_REVISION
