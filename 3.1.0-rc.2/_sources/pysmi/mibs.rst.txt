
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

Carried and held
----------------

The manifest covers more modules than the package ships. Those with the same
provenance as the rest but which nothing in the corpus imports are *held*, in
``pysmi/mibs/future/`` in the repository: not installed, not searched, not
compiled into the wheel, and not re-fetched by the freshness check. Their
manifest entries stay, so pysmi can still say what such a module is and where
its text comes from, and promoting one back is a single command.

:py:func:`pysmi.mibs.bundled` and :py:func:`pysmi.mibs.future` are how a caller
tells the two apart. Anything reasoning about what an install can actually
supply wants ``bundled()``, not ``manifest()``:

.. code-block:: python

   from pysmi.mibs import bundled, future, manifest

   "IF-MIB" in bundled()          # True -- the package carries this one
   "TOKENRING-MIB" in bundled()   # False
   "TOKENRING-MIB" in future()    # True -- known, but not shipped
   "TOKENRING-MIB" in manifest()  # True -- both tiers

See :ref:`bundled-mib-future` for the full list and for how to promote one.

Runtime behavior
----------------

A third directory, ``pysmi/mibs/behavior/``, holds no MIB text at all. What is
in it is the Python for the few runtime relations SMIv2 has no syntax to
express, so that no code generator can derive them: RFC 4001 section 4 makes
the encoding of an ``InetAddress`` index depend on the value of the
``InetAddressType`` index preceding it in the same row, and states that only in
a DESCRIPTION clause, in prose.

One file per module, named exactly as the module.
:py:class:`~pysmi.codegen.pysnmp.PySnmpCodeGen` appends it to what it renders for that
module, after the exports, so it runs in the generated module's own namespace
and reaches every symbol the MIB defined by name.

This is deliberately not a patch on generated output. The module above a
fragment is regenerated from the ASN.1 on every compile and the fragment is
appended to whatever that produced, so the two cannot drift apart -- which is
what happened to the hand-edited copies that motivated the mechanism. See
``pysmi/mibs/behavior/README.md`` for what belongs there, and what is a code
generator bug instead.

.. autofunction:: pysmi.mibs.manifest

.. autofunction:: pysmi.mibs.bundled

.. autofunction:: pysmi.mibs.future

.. autofunction:: pysmi.mibs.successors

.. autofunction:: pysmi.mibs.successor_for

.. autofunction:: pysmi.mibs.behavior
