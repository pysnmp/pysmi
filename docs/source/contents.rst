
SNMP SMI compiler
=================

.. toctree::
   :maxdepth: 2

The PySMI library and tools are designed to parse, verify and transform
`SNMP SMI <https://en.wikipedia.org/wiki/Management_information_base>`_ MIB
modules from their original ASN.1 form into JSON or `pysnmp
<https://pysnmp.github.io/pysnmp/>`_ representation.

pysnmp drives it for you: ask an engine to resolve a name in a module it does
not have and pysmi is what compiles that module. You reach for it directly to
compile MIBs outside an engine, with :doc:`mibdump </mibdump>`, or to build a
whole corpus from a manifest, with :doc:`mibcorpus </mibcorpus>` -- which is
what builds the `MIB distribution <https://pysnmp.github.io/mibs/>`_ this
organization publishes.

It installs as ``pysnmp-pysmi``, and pysnmp's ``compile`` extra pulls it in.
The `organization site <https://pysnmp.github.io/>`_ describes how the four
projects fit together.

Documentation
-------------

.. toctree::
   :maxdepth: 2

   /documentation

Source code & Changelog
-----------------------

Project source code is hosted at `GitHub <https://github.com/pysnmp/pysmi>`_.
Everyone is welcome to fork and contribute back!

We maintain the detailed :doc:`log of changes </changelog>` to our software.

Download & Install
------------------

.. toctree::
   :maxdepth: 2

   /download

Development
-----------

How changes reach a release: the branches, what CI runs, and how a version is
cut and published.

.. toctree::
   :maxdepth: 2

   /ci-and-releases

Changes
-------

The changelog is generated from the commit history at release time. The
narrative history of the project through 1.0.5 is kept separately.

.. toctree::
   :maxdepth: 1

   /changelog
   /changelog-history

License
-------

The SNMP SMI library software is distributed under 2-clause BSD License.

.. toctree::
   :maxdepth: 2

   /license

MIB files archive
-----------------

The PySMI project maintains a `collection <https://pysnmp.github.io/mibs/asn1>`_
of publicly available ASN.1 MIB files collected on the Internet. You are
welcome to use this MIBs archive however we can't guarantee any degree
of consistency or reliability when it comes to these MIB modules.

The *mibdump* tool as well as many other utilities based on PySMI
are programmed to use this MIB repository for automatic download and
dependency resolution.

You can always reconfigure PySMI to use some other remote MIB repository
instead or in addition to this one.

Contact
-------

In case of questions or troubles using SNMP SMI library, please open up an
`issue <https://github.com/pysnmp/pysmi/issues>`_ at GitHub or ask at
`Stack Overflow <http://stackoverflow.com/questions/tagged/pysmi>`_ .
