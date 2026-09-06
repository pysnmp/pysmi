"""RFC-frozen base ASN.1 MIB sources, read by
:py:class:`~pysmi.reader.package.PackageReader`.

Every file here is named exactly as the MIB module it holds, with no
extension -- the same convention its canonical source at
https://pysnmp.github.io/mibs/asn1/ uses. Add a module here only once it is
frozen. A copy here is preferred over a caller's own whenever the caller's
carries no newer MODULE-IDENTITY revision, so an actively revised MIB bundled
here would serve a stale copy to callers who do have a current one. See
pysnmp/pysmi#113.
"""
