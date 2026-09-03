
PySMI library
=============

The *MibCompiler* object is the top-most interface to PySMI library features.
It holds together the otherwise isolated pieces of the compiler infrastructure
and manages the workflow of ASN.1 MIB transformation.

This example showcases some of its features:

.. code-block:: python

   from pysmi.reader import HttpReader
   from pysmi.searcher import StubSearcher
   from pysmi.writer import CallbackWriter
   from pysmi.parser import SmiStarParser
   from pysmi.codegen import JsonCodeGen
   from pysmi.compiler import MibCompiler

   inputMibs = ['IF-MIB', 'IP-MIB']

   httpSources = ['https://pysnmp.github.io/mibs/asn1/@mib@']

   # store compiled MIBs by calling this function
   def store_mibs(mibName, jsonDoc, cbCtx):
       print('# MIB module %s' % mibName)
       print(jsonDoc)

   mibCompiler = MibCompiler(
       SmiStarParser(), JsonCodeGen(), CallbackWriter(store_mibs)
   )

   # pull ASN.1 MIBs over HTTP
   mibCompiler.add_sources(*[HttpReader(x) for x in httpSources])

   # never recompile MIBs with ASN.1 MACROs
   mibCompiler.add_searchers(StubSearcher(*JsonCodeGen.baseMibs))

   status = mibCompiler.compile(*inputMibs)

   print(status)

.. toctree::
   :maxdepth: 2

   /pysmi/compiler/mibcompiler
   /pysmi/compiler/mibstatus

.. _camel-case-deprecation:

Method naming
-------------

PySMI's methods were camelCase -- ``addSources``, ``getMibVariants``,
``putData`` and so on. They are snake_case now, as :pep:`8` calls for:
``add_sources``, ``get_mib_variants``, ``put_data``.

Every renamed method keeps its old name, so existing code goes on working:

.. code-block:: python

   mibCompiler.addSources(HttpReader(url))   # works, warns
   mibCompiler.add_sources(HttpReader(url))  # the same thing, quietly

Calling the old name raises a :py:exc:`DeprecationWarning`, which Python hides
by default. To see where your code still uses the old spelling, run it with
warnings turned on::

   python -W always::DeprecationWarning your_script.py

The old names will be removed in a future major release.

If you subclass a PySMI class and override a method under its old name, PySMI
installs your override under the new name and warns, so it still runs. Renaming
the override silences the warning.

MIB sources
-----------

PySMI offers a handful of distinct transport mechanisms for fetching MIBs by
name from specific locations. In all cases MIB module name to file name match
may not be exact -- some name fuzzying can be performed to mitigate
possible changes to MIB file name.

.. toctree::
   :maxdepth: 2

   /pysmi/reader/localfile/filereader
   /pysmi/reader/zipreader/zipreader
   /pysmi/reader/httpclient/httpreader
   /pysmi/reader/callback/callbackreader
   /pysmi/reader/package/packagereader

Conditional compilation
-----------------------

There are cases when MIB transformation may or must not be performed.
Such cases include:

* foundation MIBs containing manually implemented pieces or ASN.1 MACRO's
* obsolete MIBs fully reimplemented within modern MIBs
* already transformed MIBs

:ref:`MibCompiler <compiler.MibCompiler>` expects user to supply a
*searcher* object that would allow or skip MIB transformation for particular
name based on whatever reason it is aware of.

In general, *searcher* logic is specific to target format. At the time being,
only `pysnmp <https://github.com/pysnmp/pysnmp>`_ code generation backend requires
such filtering.

.. toctree::
   :maxdepth: 2

   /pysmi/searcher/pyfile/pyfilesearcher
   /pysmi/searcher/pypackage/pypackagesearcher
   /pysmi/searcher/stub/stubsearcher

Parser configuration
--------------------

MIBs may be written in one of the two major SMI language versions (v1 and v2).
Some MIBs may contain typical errors.

PySMI offers a way to customize the parser to consume either of the major SMI
grammars as well as to recover from well-known errors in MIB files.

.. toctree::
   :maxdepth: 2

   /pysmi/parser/smi/parserfactory
   /pysmi/parser/smi/dialect

Code generators
---------------

Once ASN.1 MIB is parsed up, AST is passed to a code generator which turns
AST into desired representation of the MIB.

.. toctree::
   :maxdepth: 2

   /pysmi/codegen/jsondoc/jsoncodegen
   /pysmi/codegen/pysnmp/pysnmpcodegen
   /pysmi/codegen/null/nullcodegen
   /pysmi/codegen/symtable/symtablecodegen

Borrow pre-compiled MIBs
------------------------

Some MIBs in circulation appear broken beyond automatic repair. To
handle such cases PySMI introduces the *MIB borrowing*
functionality. When :ref:`MibCompiler <compiler.MibCompiler>`
gives up compiling a MIB, it can try to go out and take a copy of
already transformed MIB to complete the request successfully.

.. toctree::
   :maxdepth: 2

   /pysmi/borrower/anyfile/anyfileborrower
   /pysmi/borrower/pyfile/pyfileborrower

Write compiled MIBs
-------------------

Successfully transformed MIB modules' contents will be passed to *writer*
object given to :ref:`MibCompiler <compiler.MibCompiler>` on instantiation.

.. toctree::
   :maxdepth: 2

   /pysmi/writer/localfile/filewriter
   /pysmi/writer/pyfile/pyfilewriter
   /pysmi/writer/callback/callbackwriter

Extending PySMI
---------------

Each stage of the compiler is defined by a small interface, so a MIB source,
searcher, parser, code generator or writer of your own can be dropped in
beside the ones PySMI ships.

.. toctree::
   :maxdepth: 2

   /pysmi/extending

Exceptions
----------

Every stage reports failure by raising an exception of its own, all of them
derived from a single base class.

.. toctree::
   :maxdepth: 2

   /pysmi/error

Examples
--------

The following examples focus on various feature of the PySMI library.

.. toctree::
   :maxdepth: 2

   /examples/download-and-compile-smistar-mibs-into-json.rst
   /examples/build-json-index.rst
   /examples/download-and-compile-smistar-mibs-into-pysnmp-files.rst
   /examples/compile-smistar-mibs-into-pysnmp-files-if-needed.rst
   /examples/compile-smiv2-mibs-from-text-into-pysnmp-code.rst
   /examples/borrow-precompiled-pysnmp-files-on-failure.rst
   /examples/always-borrow-precompiled-pysnmp-files.rst

In case of any troubles or confusion, try enabling PySMI debugging
and watch the output:

.. code-block:: python

   from pysmi import debug

   debug.enableDebugLogging('all')

Pass the names of the subsystems you are interested in to keep the
output down, prefixing a name with ``!`` to leave that one out:

.. code-block:: python

   debug.enableDebugLogging('reader', 'compiler')
   debug.enableDebugLogging('all', '!grammar')

PySMI logs through the standard :mod:`logging` module, and each
subsystem logs to the logger named after its package, so an
application that already configures logging can select and route
this output itself without going through PySMI at all:

.. code-block:: python

   import logging

   logging.getLogger('pysmi.compiler').setLevel(logging.DEBUG)

Messages carry their variable parts as structured fields on the log
record -- the name of the MIB being worked on as ``mib``, the file
being read or written as ``path``, and so on -- so a handler can pick
them out individually:

.. code-block:: python

   class MibHandler(logging.Handler):
       def emit(self, record):
           print(record.getMessage(), getattr(record, 'mib', None))

.. note::

   ``debug.setLogger()`` and ``debug.Debug()`` still work, but are
   deprecated in favour of ``debug.enableDebugLogging()``.

