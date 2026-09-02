.. _extending:

Extension points
================

Every stage of the compiler is pluggable. The classes below define what a
replacement has to implement; the concrete classes documented elsewhere in
this reference are all built on them.

A component is only ever asked for what its stage needs, so a custom reader
that pulls MIBs out of a database, or a writer that posts them to a service,
fits alongside the ones shipped with PySMI without touching anything else.

MIB sources
-----------

.. autoclass:: pysmi.reader.base.AbstractReader
   :members:

Conditional compilation
-----------------------

A searcher answers whether a compiled MIB is current, and reports the answer
by raising rather than returning.

.. autoclass:: pysmi.searcher.base.AbstractSearcher
   :members:

Parsers and lexers
------------------

.. autoclass:: pysmi.parser.base.AbstractParser
   :members:

.. autoclass:: pysmi.lexer.base.AbstractLexer
   :members:

Code generators
---------------

.. autoclass:: pysmi.codegen.base.AbstractCodeGen
   :members: genCode, genIndex, isBinary, isHex, str2int

Borrowers
---------

.. autoclass:: pysmi.borrower.base.AbstractBorrower
   :members:

Writers
-------

.. autoclass:: pysmi.writer.base.AbstractWriter
   :members:

MIB metadata
------------

.. autoclass:: pysmi.mibinfo.MibInfo
   :members:

Building readers from URLs
--------------------------

.. autofunction:: pysmi.reader.url.getReadersFromUrls
