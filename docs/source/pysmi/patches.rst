
.. _patches:

MIB patches
===========

A published MIB that does not compile is repaired by a diff against its text.
That is a durable, reviewable form for a repair: it names the defect, it
carries the correction, and it lives in version control where it can be read
before anything runs.

:py:mod:`pysmi.patches` reads, applies and writes those diffs.
:py:mod:`pysmi.patchgen` derives them, working out the same corrections
``pysmi.codegen.symtable`` would otherwise make in memory as a module
compiles. The ``mibpatch`` tool is the command line over both -- see
:ref:`mibpatch` for the workflow.

Nothing here runs while a MIB is compiled. PySMI reads what a source actually
holds and does not patch anything on the way past; patching a tree is something
done to it beforehand, deliberately, with the diffs to show for it.

Applying a patch set
--------------------

.. code-block:: python

   from pysmi.patches import ALREADY_APPLIED, APPLIED, PatchSet

   patches = PatchSet.from_directory("./mib-patches")

   text, status = patches.apply("HPR-MIB", source_text)

The status tells apart the three things that can happen to text a patch is
offered. :py:data:`~pysmi.patches.APPLIED` means it was repaired just now;
:py:data:`~pysmi.patches.ALREADY_APPLIED` means the text already carried the
repair, which is what a patched tree gives back; and
:py:data:`~pysmi.patches.NOT_APPLICABLE` means the patch was cut against
different text, which is how a publisher moving under you is detected rather
than papered over.

Reading why a repair exists
---------------------------

A patch opens with the defect it repairs, above the diff, as an identifier and
the page documenting it:

.. code-block:: python

   for defect in patches.defects_for("HPR-MIB"):
       print(defect.id, defect.url)

:doc:`/mib-defects` is that catalogue, and :py:mod:`pysmi.defects` is it in
Python. An identifier PySMI does not know is read the same way, so a tree with
repairs and a catalogue of its own needs no configuring here.

A patch naming no defect is still a patch --
:py:meth:`~pysmi.patches.PatchSet.header_for` gives back an empty
:py:class:`~pysmi.patches.PatchHeader` for it, and ``None`` only when there is
no patch at all. Everything that reads a diff skips the block, so this is a
convention over the format rather than a change to it.

Deriving one
------------

.. code-block:: python

   from pysmi.patchgen import REPAIRABLE, inspect

   defect = inspect(source_text, mibname="ACME-MIB")

   if defect.status == REPAIRABLE:
       print(defect.patch)

.. automodule:: pysmi.patches

.. automodule:: pysmi.patchgen

.. automodule:: pysmi.scripts.mibpatch

Statuses
--------

.. autodata:: pysmi.patches.APPLIED

.. autodata:: pysmi.patches.ALREADY_APPLIED

.. autodata:: pysmi.patches.NOT_APPLICABLE

.. autodata:: pysmi.patches.UNPATCHED

Reading and applying
--------------------

.. autoclass:: pysmi.patches.PatchSet
  :members:

.. autofunction:: pysmi.patches.apply_patch

.. autofunction:: pysmi.patches.parse_patch

.. autofunction:: pysmi.patches.make_patch

.. autoclass:: pysmi.patches.Hunk
  :members:

Defects
-------

.. automodule:: pysmi.defects

.. autoclass:: pysmi.patches.PatchHeader
  :members:

.. autofunction:: pysmi.patches.split_patch

.. autofunction:: pysmi.patches.format_header

.. autoclass:: pysmi.defects.DefectRef
  :members:

.. autoclass:: pysmi.defects.DefectClass
  :members:

.. autodata:: pysmi.defects.CATALOGUE
  :no-value:

.. autofunction:: pysmi.defects.ref

.. autofunction:: pysmi.defects.url

.. autofunction:: pysmi.defects.summary

Deriving
--------

.. autodata:: pysmi.patchgen.REPAIRABLE

.. autodata:: pysmi.patchgen.CLEAN

.. autodata:: pysmi.patchgen.UNPARSEABLE

.. autoclass:: pysmi.patchgen.Defect
  :members:

.. autofunction:: pysmi.patchgen.inspect

.. autofunction:: pysmi.patchgen.missing_imports

.. autofunction:: pysmi.patchgen.repair_imports

.. autofunction:: pysmi.patchgen.repair_defects
