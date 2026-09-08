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
