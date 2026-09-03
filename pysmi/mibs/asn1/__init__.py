"""RFC-frozen base ASN.1 MIB sources, read by
:py:class:`~pysmi.reader.package.PackageReader`.

Every file here is named exactly as the MIB module it holds, with no
extension -- the same convention its canonical source at
https://pysnmp.github.io/mibs/asn1/ uses. Add a module here only once it is
frozen -- an actively revised MIB bundled here would silently serve a stale
copy whenever the real source is unreachable. See pysnmp/pysmi#113.
"""
