.. _patches:

MIB patches
===========

.. automodule:: pysmi.patches

Applying a patch
----------------

.. autofunction:: pysmi.patches.apply_patch

.. autofunction:: pysmi.patches.parse_patch

.. autoclass:: pysmi.patches.Hunk
  :members:

What happened to the text
-------------------------

.. autodata:: pysmi.patches.APPLIED

.. autodata:: pysmi.patches.ALREADY_APPLIED

.. autodata:: pysmi.patches.NOT_APPLICABLE

.. autodata:: pysmi.patches.UNPATCHED

Choosing which patches a reader offers
--------------------------------------

.. autoclass:: pysmi.patches.PatchSet
  :members:
