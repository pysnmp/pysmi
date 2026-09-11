Download & Install
==================

The SNMP SMI library is published to PyPI as ``pysnmp-pysmi``. Note the name:
``pysmi`` is the original, unmaintained package.

With `uv <https://docs.astral.sh/uv/>`_:

.. code-block:: bash

   $ uv add pysnmp-pysmi

Or with ``pip``:

.. code-block:: bash

   $ python -m venv venv
   $ source venv/bin/activate
   $ pip install pysnmp-pysmi

Either way you also get the command-line tools: :doc:`mibdump </mibdump>` to
compile a module, :doc:`mibcopy </mibcopy>` to normalize a source tree,
:doc:`mibpatch </mibpatch>` to apply a recorded repair, and
:doc:`mibcorpus </mibcorpus>` to build a whole corpus from a manifest -- which
is what produces the `MIB distribution <https://pysnmp.github.io/mibs/>`_. To
run one without installing anything permanently:

.. code-block:: bash

   $ uvx --from pysnmp-pysmi mibdump --help

PySMI needs Python 3.10 or newer.

Alternatively, you can download the latest release from
`GitHub <https://github.com/pysnmp/pysmi/releases>`_
or `PyPI <https://pypi.org/project/pysnmp-pysmi/>`_.
