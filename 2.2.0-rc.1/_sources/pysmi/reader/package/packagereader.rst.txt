.. _reader.package.PackageReader:

Package reader
--------------

*PackageReader* class instance looks up MIB files bundled inside a Python
package, through :py:mod:`importlib.resources`. Unlike *FileReader*, this
works whether the package is installed as a directory or sits inside a
zipped wheel.

.. autoclass:: pysmi.reader.package.PackageReader
  :members:
