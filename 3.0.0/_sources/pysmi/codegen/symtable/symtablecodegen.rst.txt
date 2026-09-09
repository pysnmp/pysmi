
.. _codegen.symtable.SymtableCodeGen:

Symbol table generator
----------------------

Before a MIB is rendered, it is walked once by *SymtableCodeGen*, which
collects the symbols the module defines and exports. The compiler does this
for the module being compiled and for everything it imports, then hands the
result to the real code generator as its *symbolTable* argument.

.. autoclass:: pysmi.codegen.symtable.SymtableCodeGen
   :members:
