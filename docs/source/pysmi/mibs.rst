
.. _mibs:

Bundled MIB manifest
====================

PySMI bundles the ASN.1 text of the modules every real-world MIB ultimately
depends on, and ``bundled_mibs.json`` beside them records where each one's text
comes from and -- for the ones a later RFC replaced -- which module took over.

The manifest ships inside the package, so an installed wheel answers the same
as a checkout, and a caller can ask about supersession without a network round
trip. The question turns up at runtime: an agent walking an old device answers
with OIDs whose defining module was obsoleted years ago, and the caller wants
to know what defines them now.

.. code-block:: python

   from pysmi.mibs import successor_for

   # a device that still answers out of MIB-II
   successor_for("RFC1213-MIB", "1.3.6.1.2.1.2.2.1.10")   # 'IF-MIB'
   successor_for("RFC1213-MIB", "1.3.6.1.2.1.6.9")        # 'TCP-MIB'

   # nothing took this subtree over
   successor_for("RFC1213-MIB", "1.3.6.1.2.1.8.1")        # None

Modules replaced whole answer for any OID, so the second argument can be left
off:

.. code-block:: python

   from pysmi.mibs import successors, successor_for

   successor_for("DSA-MIB")     # 'DIRECTORY-SERVER-MIB'
   successors("DSA-MIB")        # {'RFC2605': 'DIRECTORY-SERVER-MIB'}

See :ref:`bundled-mib-historical` for which modules carry a successor and why.

.. autofunction:: pysmi.mibs.manifest

.. autofunction:: pysmi.mibs.successors

.. autofunction:: pysmi.mibs.successor_for
