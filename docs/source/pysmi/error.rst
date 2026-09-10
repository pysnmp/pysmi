
.. _error:

Exceptions
==========

Every error PySMI raises derives from :py:exc:`~pysmi.error.PySmiError`, so a
caller that has no interest in which stage failed can catch that one class.

The stages raise their own subclasses. A searcher reports that a MIB need not
be compiled by raising :py:exc:`~pysmi.error.PySmiFileNotModifiedError` or
:py:exc:`~pysmi.error.PySmiFileNotFoundError`; a reader reports the same
conditions about a source file with
:py:exc:`~pysmi.error.PySmiReaderFileNotModifiedError` and
:py:exc:`~pysmi.error.PySmiReaderFileNotFoundError`. Those are part of the
normal flow of a compilation run, not failures.

.. autoexception:: pysmi.error.PySmiError
  :members:

Lexer and parser
----------------

.. autoexception:: pysmi.error.PySmiLexerError
  :members:

.. autoexception:: pysmi.error.PySmiParserError
  :members:

.. autoexception:: pysmi.error.PySmiSyntaxError
  :members:

Searcher
--------

.. autoexception:: pysmi.error.PySmiSearcherError
  :members:

.. autoexception:: pysmi.error.PySmiFileNotModifiedError
  :members:

.. autoexception:: pysmi.error.PySmiFileNotFoundError
  :members:

Reader
------

.. autoexception:: pysmi.error.PySmiReaderError
  :members:

.. autoexception:: pysmi.error.PySmiReaderFileNotModifiedError
  :members:

.. autoexception:: pysmi.error.PySmiReaderFileNotFoundError
  :members:

Code generator
--------------

.. autoexception:: pysmi.error.PySmiCodegenError
  :members:

.. autoexception:: pysmi.error.PySmiSemanticError
  :members:

Writer
------

.. autoexception:: pysmi.error.PySmiWriterError
  :members:
