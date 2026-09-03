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

Either way you also get the ``mibdump`` and ``mibcopy`` command-line tools. To
run them without installing anything permanently:

.. code-block:: bash

   $ uvx --from pysnmp-pysmi mibdump --help

PySMI needs Python 3.10 or newer.

Alternatively, you can download the latest release from
`GitHub <https://github.com/pysnmp/pysmi/releases>`_
or `PyPI <https://pypi.org/project/pysnmp-pysmi/>`_.
