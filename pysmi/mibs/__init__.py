"""Base MIB ASN.1 sources bundled with pysmi, for the modules every
real-world MIB ultimately depends on.

These are searched alongside the caller's own sources rather than only when
the caller has none: for a module bundled here, the newest MODULE-IDENTITY
revision wins, and the bundled copy takes it when the caller's copy is older,
undated, or absent. See :py:meth:`pysmi.compiler.MibCompiler.compile`.
"""
